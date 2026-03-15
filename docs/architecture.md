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
  └── DatabaseManager            (SQLite CRUD: orders, exchange_rates, dividends)
```

## Module Responsibilities

| Module | Does | Does NOT |
|---|---|---|
| `cost_pool.py` | Weighted avg cost math, long & short positions | Know about currencies, rates, fees, DB |
| `settlement.py` | CNY conversion: `(qty × price × multiplier ± fees) × rate` | Know about cost pools or tax |
| `calculator.py` | Replay full history through pool, collect year's taxable events, CSV export | Compute rates, fees, or cost math |
| `dividend.py` | Dividend income tax: gross reconstruction, foreign tax credit, CNY conversion | Parse cash flow entries or fetch data |
| `cashflow_parser.py` | Parse cash flow into dividend records, match withholding by timestamp | DB access, API calls, tax calculation |
| `database.py` | SQLite read/write for orders, exchange rates, dividends | Business logic |
| `exchange_rate.py` | Rate fetch (provider API + DB cache + fallback), batch time-series | Anything else |
| `longbridge_client.py` | Long Bridge API calls (orders, order detail, cash flow) | Data storage or calculation |
| `config.py` | Env vars, paths, tax rate constants | Logic |

## Database Tables

| Table | Key Columns | Purpose |
|---|---|---|
| `orders` | order_id (PK), symbol, side, quantity, price, currency, executed_at, fees_json | Trade history |
| `exchange_rates` | (date, from_currency, to_currency) PK, rate, source | Cached FX rates |
| `dividends` | id (auto), symbol, currency, amount, withholding, received_at | Dividend income records |

## Key Design Decisions

**Historical cost pool**: `get_orders_until(symbol, year)` fetches all trades from first purchase to year-end. The pool is replayed chronologically so sells in any year use the correct weighted average cost.

**Options multiplier**: `get_multiplier(symbol)` detects US options by symbol pattern (`TICKER+YYMMDD+C/P+STRIKE.US`) and returns 100. Applied in settlement's `_gross()` calculation. CostPool is unaware.

**Short positions (sell-to-open)**: CostPool tracks negative quantity. `sell()` on empty pool opens short (records proceeds), `buy()` on short pool closes it (returns locked-in proceeds as cost_basis). Calculator computes gain = proceeds_at_open - cost_to_close.

**Fees as separate step**: `update-fees` calls order detail API per-order, stores in `fees_json`. Decoupled from order import. Settlement reads fees automatically via `_extract_fees()`.

**Exchange rates**: `RateProvider` ABC with `FrankfurterProvider` implementation. `ExchangeRateManager` orchestrates DB cache → provider → nearest-before (for weekends) → hardcoded fallback. Batch fetch uses time-series API to minimize requests. Each rate records its `source` (e.g. `frankfurter`, `fallback`).

**Dividend import decoupled from calculation**: `import-dividends` fetches cash flow from API and stores parsed dividend records (with matched withholding) in DB. `calculate` reads from DB and computes tax. No API calls during calculation.

## Dividend Tax Calculation

China taxes dividend income at a flat 20% rate. Foreign withholding tax is credited against the China liability (capped at the China tax amount).

```
gross       = net_received + foreign_withholding
china_tax   = gross_cny × 20%
credit      = min(withheld_cny, china_tax)
tax_owed    = china_tax - credit
```

Withholding data comes from the actual cash flow (Long Bridge "CO Other FEE" entries), not estimated by market. This means:
- US stocks: typically 10% withheld → 10% owed
- HK H-shares: typically 10% withheld → 10% owed
- HK non-H-shares: no withholding → 20% owed
- Scrip dividends (以股代息): not in cash flow, not taxed as dividend income

