# Investment Tax Calculator — Architecture

## Module Graph

```
cli.py                           (user interaction, command orchestration)
  ├── LongBridgeClient           (API: orders, order detail, cash flow)
  ├── CashflowParser             (parse dividends + match withholding from cash flow)
  ├── TaxCalculator              (orchestrate capital gains: replay history → taxable events)
  │     ├── SettlementCalc       (convert trades to CNY: rate × multiplier ± fees)
  │     │     └── ExchangeRate   (rate fetch + cache + fallback)
  │     └── CostPool             (weighted avg cost, long + short, zero dependencies)
  ├── DividendCalculator         (dividend income tax with foreign tax credit)
  │     └── ExchangeRate         (shared)
  ├── ReportExporter             (CSV output: transactions, dividends, tax summary)
  └── DatabaseManager            (SQLite CRUD: orders, exchange_rates, cashflows)
```

## Module Responsibilities

| Module | Does | Does NOT |
|---|---|---|
| `cost_pool.py` | Weighted avg cost math, long & short positions | Know about currencies, rates, fees, DB |
| `settlement.py` | CNY conversion: `(qty × price × multiplier ± fees) × rate` | Know about cost pools or tax |
| `calculator.py` | Replay full history through pool, collect year's taxable events | Compute rates, fees, cost math, or report formatting |
| `dividend.py` | Dividend income tax: reads raw cashflows → parser → CNY conversion, foreign tax credit | Parse cash flow entries or fetch data |
| `cashflow_parser.py` | Parse raw cash flow into dividend records, match withholding by timestamp, H-share gross reconstruction | DB access, API calls, tax calculation |
| `database.py` | SQLite read/write for orders, exchange rates, cashflows (raw cache) | Business logic |
| `exchange_rate.py` | Rate fetch (provider API + DB cache + fallback), batch time-series | Anything else |
| `longbridge_client.py` | Long Bridge API calls (orders, order detail, cash flow) | Data storage or calculation |
| `report.py` | CSV export: transaction details, per-symbol summary, dividend tax | Business logic or calculation |
| `config.py` | Env vars, paths, tax rate constants | Logic |

## Database Tables

| Table | Key Columns | Purpose |
|---|---|---|
| `orders` | order_id (PK), symbol, side, quantity, price, currency, executed_at, fees_json | Trade history |
| `exchange_rates` | (date, from_currency, to_currency) PK, rate, source | Cached FX rates |
| `cashflows` | id (auto), transaction_flow_name, direction, balance, currency, business_time, symbol, description | Raw API cash flow cache |

## Key Design Decisions

**Historical cost pool**: `get_orders_until(symbol, year)` fetches all trades from first purchase to year-end. The pool is replayed chronologically so sells in any year use the correct weighted average cost.

**Options multiplier**: `get_multiplier(symbol)` detects US options by symbol pattern (`TICKER+YYMMDD+C/P+STRIKE.US`) and returns 100. Applied in settlement's `_gross()` calculation. CostPool is unaware.

**Short positions (sell-to-open)**: CostPool tracks negative quantity. `sell()` on empty pool opens short (records proceeds), `buy()` on short pool closes it (returns locked-in proceeds as cost_basis). Calculator computes gain = proceeds_at_open - cost_to_close.

**Fees as separate step**: `update-fees` calls order detail API per-order, stores in `fees_json`. Decoupled from order import. Settlement reads fees automatically via `_extract_fees()`.

**Exchange rates**: `RateProvider` ABC with `FrankfurterProvider` implementation. `ExchangeRateManager` orchestrates DB cache → provider → nearest-before (for weekends) → hardcoded fallback. Batch fetch uses time-series API to minimize requests. Each rate records its `source` (e.g. `frankfurter`, `fallback`).

**Dividend import decoupled from calculation**: `import-dividends` fetches cash flow from API and stores raw entries in the `cashflows` table (DB as cache layer, mirrors API response). `calculate` reads raw cash flows, pipes them through `cashflow_parser` (withholding matching, H-share gross reconstruction), then computes tax. No processing at import time — logic changes take effect without re-importing.

## Dividend Tax Calculation

China taxes dividend income at a flat 20% rate. Foreign withholding tax is credited against the China liability (capped at the China tax amount).

```
gross       = net_received + foreign_withholding
china_tax   = gross_cny × 20%
credit      = min(withheld_cny, china_tax)
tax_owed    = china_tax - credit
```

Withholding data comes from the actual cash flow entries:
- US stocks: "CO Other FEE" with Withholding Tax description → matched by timestamp
- HK H-shares: embedded in Cash Dividend description as `(-10%)`, balance is NET → parser back-calculates gross
- HK non-H-shares (red chips, Cayman-registered like BABA-W): no withholding → full 20% owed
- Scrip dividends (以股代息): not in cash flow, not taxed as dividend income

Raw cash flow entries are stored as-is in the `cashflows` table (DB = cache layer). All processing (withholding matching, gross reconstruction) happens at read time in `cashflow_parser.py`.

