# Investment Tax Calculator — Architecture

## Module Graph

```
cli.py                        (user interaction, command orchestration)
  ├── LongBridgeClient        (API: fetch orders, fetch order detail/fees)
  ├── TaxCalculator           (orchestration: replay history → collect taxable events)
  │     ├── SettlementCalc    (convert trades to CNY: rate × multiplier ± fees)
  │     │     └── ExchangeRate (rate fetch + cache)
  │     └── CostPool          (weighted avg cost, long + short, zero dependencies)
  └── DatabaseManager         (SQLite CRUD)
```

## Module Responsibilities

| Module | Does | Does NOT |
|---|---|---|
| `cost_pool.py` | Weighted avg cost math, long & short positions | Know about currencies, rates, fees, DB |
| `settlement.py` | CNY conversion: `(qty × price × multiplier ± fees) × rate` | Know about cost pools or tax |
| `calculator.py` | Replay full history through pool, collect year's taxable events | Compute rates, fees, or cost math |
| `database.py` | SQLite read/write, order & rate storage | Business logic |
| `exchange_rate.py` | Rate fetch (API + cache + fallback) | Anything else |
| `longbridge_client.py` | Longbridge API calls (orders, order detail) | Data storage or calculation |

## Key Design Decisions

**Historical cost pool**: `get_orders_until(symbol, year)` fetches all trades from first purchase to year-end. The pool is replayed chronologically so sells in any year use the correct weighted average cost.

**Options multiplier**: `get_multiplier(symbol)` detects US options by symbol pattern (`TICKER+YYMMDD+C/P+STRIKE.US`) and returns 100. Applied in settlement's `_gross()` calculation. CostPool is unaware.

**Short positions (sell-to-open)**: CostPool tracks negative quantity. `sell()` on empty pool opens short (records proceeds), `buy()` on short pool closes it (returns locked-in proceeds as cost_basis). Calculator computes gain = proceeds_at_open - cost_to_close.

**Fees as separate step**: `cli.py update-fees` calls order detail API per-order, stores in `fees_json`. Decoupled from order import. Settlement reads fees automatically via `_extract_fees()`.

## CLI Workflow

```bash
# First time: pull full history
python cli.py import-data --year 2025 --since 2020-01-01

# Fetch commission fees (separate, idempotent)
python cli.py update-fees --year 2025

# Calculate tax
python cli.py calculate --year 2025
```
