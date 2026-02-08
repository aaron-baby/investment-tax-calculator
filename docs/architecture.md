# Investment Tax Calculator — Architecture Overview

## Module Dependency Graph

```
┌─────────────────────────────────────────────────────────┐
│                        cli.py                           │
│                   (用户交互 & 编排)                       │
└──────┬──────────────┬───────────────┬───────────────────┘
       │              │               │
       ▼              ▼               ▼
┌────────────┐ ┌─────────────┐ ┌──────────────┐
│ LongBridge │ │    Tax       │ │   Config     │
│ Client     │ │ Calculator   │ │              │
│            │ │ (编排层)      │ │              │
└─────┬──────┘ └──┬───┬───┬──┘ └──────────────┘
      │           │   │   │
      │           ▼   │   ▼
      │  ┌────────────┐│┌───────────────────┐
      │  │ Settlement  │││   CostPool        │
      │  │ Calculator  │││ (纯计算,零依赖)    │
      │  └──────┬──────┘│└───────────────────┘
      │         │       │
      │         ▼       │
      │  ┌─────────────┐│
      │  │ Exchange     ││
      │  │ Rate Manager ││
      │  └──────┬──────┘│
      │         │       │
      ▼         ▼       ▼
    ┌─────────────────────┐
    │   DatabaseManager   │
    │   (数据存取层)       │
    └─────────────────────┘
           │
           ▼
    ┌─────────────┐
    │  SQLite DB  │
    └─────────────┘
```

## Module Responsibilities

### CostPool (`src/cost_pool.py`)
- 加权平均成本池，纯内存计算
- 零外部依赖：不知道汇率、佣金、数据库的存在
- 输入：已结算的 CNY 金额
- 输出：卖出时的成本基础
- 可独立单元测试

### SettlementCalculator (`src/settlement.py`)
- 将原始交易"结算"为报税币种 (CNY) 下的净金额
- 封装汇率转换 + 佣金处理
- 买入：`(数量 × 价格 + 佣金) × 汇率 = 成本 CNY`
- 卖出：`(数量 × 价格 - 佣金) × 汇率 = 收入 CNY`

### TaxCalculator (`src/calculator.py`)
- 纯编排层：拿数据 → 喂给结算 → 喂给成本池 → 算税
- 不做任何汇率/佣金/成本计算
- 负责确定哪些卖出属于当年应税

### DatabaseManager (`src/database.py`)
- 数据存取，新增：
  - `get_orders_until(symbol, end_year)` — 取历史全量
  - `get_symbols_with_sells(year)` — 取当年有卖出的标的

### LongBridgeClient (`src/longbridge_client.py`)
- `fetch_orders(start, end)` — 支持任意日期范围
- 不再绑定单一年份

### ExchangeRateManager (`src/exchange_rate.py`)
- 汇率获取与缓存（不变）

## Data Flow (计算 2025 年税)

```
1. cli: calculate --year 2025
2. TaxCalculator.calculate(2025)
3.   db.get_symbols_with_sells(2025) → [SPY.US, 1378.HK]
4.   for each symbol:
5.     db.get_orders_until(symbol, 2025) → 全部历史订单(按时间排序)
6.     pool = CostPool(symbol)
7.     for each order (时间顺序):
8.       if BUY:
9.         settled = settlement.settle_buy(order)  → CNY 成本
10.        pool.buy(qty, settled)
11.      if SELL:
12.        cost_basis = pool.sell(qty)              → CNY 成本基础
13.        proceeds = settlement.settle_sell(order) → CNY 收入
14.        if order in 2025:
15.          gain_loss = proceeds - cost_basis      → 记录
16.  汇总 → 报告
```

## Data Flow (导入数据)

```
1. cli: import-data --year 2025 --since 2023-01-01
2. LongBridgeClient.fetch_orders(2023-01-01, 2025-12-31)
3. db.save_orders(orders)
4. ExchangeRateManager.batch_fetch(dates)
```

## Verification Plan

### 1. Unit Test: CostPool
- 买入100股@10 → avg_cost=10, qty=100
- 再买100股@20 → avg_cost=15, qty=200
- 卖出50股 → cost_basis=750, 剩余qty=150, avg_cost=15
- 边界：卖出超过持仓 → raise error

### 2. Unit Test: SettlementCalculator
- mock 汇率，验证买入成本 = (qty*price+fees)*rate
- mock 汇率，验证卖出收入 = (qty*price-fees)*rate

### 3. Integration Test: 用 SPY.US 真实数据
- 2024: 买60@X, 卖30@Y → 验证剩余持仓成本
- 2025: 卖30@Z → 验证 cost_basis 使用历史加权平均成本，而非0

### 4. CLI Smoke Test
- `python cli.py calculate --year 2024` → 对比旧结果
- `python cli.py calculate --year 2025` → 验证历史成本正确引入
