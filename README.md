# Investment Tax Calculator

Capital gains and dividend income tax calculator for Chinese residents trading overseas securities through Long Bridge Securities.

## Features

- 🔗 Long Bridge API integration (read-only)
- 💱 Automatic currency conversion (USD/HKD → CNY) via Frankfurter API
- 🧮 Weighted average cost basis calculation (加权平均法)
- 💰 Dividend income tax with foreign tax credit
- 📊 20% capital gains / dividend tax (Chinese tax law)
- 💾 Local SQLite storage
- 📄 CSV export for tax filing

## Quick Start

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure API credentials (READ permissions only)
# Get from https://open.longbridge.com/
cp .env.example .env   # then edit with your keys
```

## Usage

```bash
# 1. Import trade history (first time, pull full history)
python cli.py import-data --year 2025 --since 2020-01-01

# 2. Fetch commission fees
python cli.py update-fees --year 2025

# 3. Import dividend records
python cli.py import-dividends --year 2025 --since 2020-01-01

# 4. Calculate tax and export CSV
python cli.py calculate --year 2025

# Utilities
python cli.py status --year 2025
python cli.py db --table orders --year 2025
python cli.py db --table rates
python cli.py setup          # interactive setup guide
```

## Documentation

- [Architecture & Design](docs/architecture.md) — module graph, design decisions, dividend tax logic
- [Tax Calculation Guide](docs/tax_calculation_guide.md) — Chinese tax law reference for overseas investments

## Disclaimer

This tool is for reference only. Consult a tax professional for official filing.

## License

MIT
