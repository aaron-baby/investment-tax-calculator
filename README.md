# Investment Tax Calculator

Capital gains tax calculator for Chinese residents trading overseas securities through Long Bridge Securities.

## Features

- 🔗 Long Bridge API integration (read-only)
- 💱 Automatic currency conversion (USD/HKD → CNY)
- 🧮 Weighted average cost basis calculation
- 📊 20% capital gains tax calculation (Chinese tax law)
- 💾 Local SQLite storage
- 📄 CSV export for tax filing

## Project Structure

```
├── cli.py              # Command-line interface
├── src/
│   ├── config.py       # Configuration management
│   ├── database.py     # SQLite operations
│   ├── longbridge_client.py  # Long Bridge API client
│   ├── exchange_rate.py      # Exchange rate fetching
│   └── calculator.py   # Tax calculation engine
├── data/               # Database files (generated)
├── output/             # CSV exports (generated)
├── requirements.txt
└── .env                # API credentials (create this)
```

## Quick Start

### 1. Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure API Credentials

Get credentials from [Long Bridge OpenAPI](https://open.longbridge.com/) (READ permissions only!)

```bash
# Create .env file
cat > .env << EOF
LONGBRIDGE_APP_KEY=your_key
LONGBRIDGE_APP_SECRET=your_secret
LONGBRIDGE_ACCESS_TOKEN=your_token
EOF
```

### 3. Import & Calculate

```bash
# Import trading data
python cli.py import-data --year 2024

# Calculate tax
python cli.py calculate --year 2024
```

## CLI Commands

```bash
# Setup guide
python cli.py setup

# Import data (with optional clear)
python cli.py import-data --year 2024 --clear

# Calculate tax
python cli.py calculate --year 2024

# View database status
python cli.py status
python cli.py status --year 2024

# View database contents
python cli.py db --table orders --limit 20
python cli.py db --table rates
```

## Tax Calculation Logic

1. **Cost Basis**: Weighted average method (加权平均法)
2. **Currency**: Historical exchange rates for each transaction
3. **Tax Rate**: 20% on realized capital gains
4. **Deductions**: Trading fees included in cost basis

## Disclaimer

This tool is for reference only. Consult a tax professional for official filing.

## License

MIT