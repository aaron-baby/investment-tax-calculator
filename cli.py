#!/usr/bin/env python3
"""CLI interface for the Investment Tax Calculator."""

import sys
import sqlite3
import time
import click
from datetime import datetime

from src.config import Config
from src.database import DatabaseManager
from src.exchange_rate import ExchangeRateManager
from src.longbridge_client import LongBridgeClient
from src.settlement import SettlementCalculator
from src.calculator import TaxCalculator

# Initialize directories
Config.init_dirs()


@click.group()
def cli():
    """Investment Tax Calculator for Long Bridge Securities."""
    pass


@cli.command()
@click.option('--year', type=int, default=Config.DEFAULT_TAX_YEAR, help='Tax year to import')
@click.option('--since', type=str, default=None,
              help='Import from this date (YYYY-MM-DD). Use for first-time setup to pull full history.')
@click.option('--clear', is_flag=True, help='Clear existing data before import')
def import_data(year, since, clear):
    """Import trading data from Long Bridge API.
    
    First-time usage: python cli.py import-data --year 2025 --since 2020-01-01
    Incremental:      python cli.py import-data --year 2025
    """
    try:
        Config.validate()
    except ValueError as e:
        click.echo(f"❌ {e}")
        click.echo("Create a .env file with your API credentials. See: python cli.py setup")
        sys.exit(1)

    db = DatabaseManager(Config.DATABASE_PATH)
    exchange = ExchangeRateManager(db)

    if clear:
        click.echo(f"🗑️  Clearing existing data for {year}...")
        db.clear_year_data(year)

    # Determine date range
    if since:
        start = datetime.strptime(since, '%Y-%m-%d')
    else:
        start = datetime(year, 1, 1)

    end = datetime(year, 12, 31, 23, 59, 59)

    click.echo(f"🔄 Importing data from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}...")

    client = LongBridgeClient(
        Config.LONGBRIDGE_APP_KEY,
        Config.LONGBRIDGE_APP_SECRET,
        Config.LONGBRIDGE_ACCESS_TOKEN
    )

    if not client.test_connection():
        sys.exit(1)

    orders = client.fetch_orders(start, end)

    if not orders:
        click.echo(f"⚠️  No orders found")
        return

    db.save_orders(orders)
    click.echo(f"✅ Imported {len(orders)} orders")

    # Fetch exchange rates for all order dates
    dates = list(set(
        datetime.fromisoformat(o['executed_at']).strftime('%Y-%m-%d')
        for o in orders
    ))
    currencies = list(set(o['currency'] for o in orders if o['currency'] != 'CNY'))

    for currency in currencies:
        exchange.batch_fetch(dates, currency, 'CNY')

    click.echo(f"✅ Import completed!")


@cli.command()
@click.option('--year', type=int, default=Config.DEFAULT_TAX_YEAR, help='Tax year')
@click.option('--export/--no-export', default=True, help='Export to CSV')
def calculate(year, export):
    """Calculate capital gains tax."""
    db = DatabaseManager(Config.DATABASE_PATH)
    exchange = ExchangeRateManager(db)
    settlement = SettlementCalculator(exchange)
    calc = TaxCalculator(db, settlement, Config.CAPITAL_GAINS_TAX_RATE)

    results = calc.calculate(year)

    if not results['details']:
        click.echo(f"⚠️  No taxable transactions for {year}")
        return

    # Display results
    click.echo(f"\n{'='*60}")
    click.echo(f"TAX CALCULATION SUMMARY FOR {year}")
    click.echo(f"{'='*60}")
    click.echo(f"Total Gains:   ¥{results['total_gains']:>12,.2f}")
    click.echo(f"Total Losses:  ¥{results['total_losses']:>12,.2f}")
    click.echo(f"Net Gains:     ¥{results['net_gains']:>12,.2f}")
    click.echo(f"Tax Rate:      {Config.CAPITAL_GAINS_TAX_RATE*100:>12.0f}%")
    click.echo(f"Tax Owed:      ¥{results['total_tax']:>12,.2f}")

    click.echo(f"\nBy Symbol:")
    click.echo("-" * 60)
    for symbol, s in results['summary'].items():
        net = s['gains'] - s['losses']
        click.echo(
            f"  {symbol:<12} Gains: ¥{s['gains']:>10,.2f}  "
            f"Losses: ¥{s['losses']:>10,.2f}  Net: ¥{net:>10,.2f}"
        )
        if s['remaining_qty'] > 0:
            click.echo(
                f"  {'':12} Remaining: {s['remaining_qty']:.0f} shares, "
                f"Cost: ¥{s['remaining_cost']:,.2f}"
            )

    if export:
        calc.export_csv(results, Config.OUTPUT_DIR)

@cli.command()
@click.option('--year', type=int, default=None, help='Only update fees for orders in this year')
def update_fees(year):
    """Fetch and store commission fees for orders via order detail API.

    This is a separate step from import-data. Run it after importing orders.
    Only fetches fees for orders that don't have fee data yet.
    """
    try:
        Config.validate()
    except ValueError as e:
        click.echo(f"❌ {e}")
        sys.exit(1)

    db = DatabaseManager(Config.DATABASE_PATH)
    missing = db.get_orders_missing_fees(year)

    if not missing:
        click.echo("✅ All orders already have fee data.")
        return

    click.echo(f"🔄 Fetching fees for {len(missing)} orders...")

    client = LongBridgeClient(
        Config.LONGBRIDGE_APP_KEY,
        Config.LONGBRIDGE_APP_SECRET,
        Config.LONGBRIDGE_ACCESS_TOKEN
    )

    updated = 0
    for i, order in enumerate(missing):
        if i > 0 and i % 10 == 0:
            click.echo(f"  Progress: {i}/{len(missing)}")

        fees = client.fetch_order_detail(order['order_id'])
        if fees:
            db.update_order_fees(order['order_id'], fees)
            updated += 1

        time.sleep(0.3)  # rate limit

    click.echo(f"✅ Updated fees for {updated}/{len(missing)} orders")




@cli.command()
@click.option('--year', type=int, help='Filter by year')
def status(year):
    """Show database status."""
    db = DatabaseManager(Config.DATABASE_PATH)

    click.echo("📊 DATABASE STATUS")
    click.echo("=" * 40)

    with sqlite3.connect(db.db_path) as conn:
        if year:
            cursor = conn.execute('''
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN side='BUY' THEN 1 ELSE 0 END) as buys,
                       SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) as sells
                FROM orders WHERE strftime('%Y', executed_at) = ?
            ''', (str(year),))
            row = cursor.fetchone()

            symbols = conn.execute('''
                SELECT DISTINCT symbol FROM orders
                WHERE strftime('%Y', executed_at) = ? ORDER BY symbol
            ''', (str(year),)).fetchall()

            click.echo(f"Year: {year}")
            click.echo(f"Orders: {row[0]} (Buy: {row[1]}, Sell: {row[2]})")
            click.echo(f"Symbols: {', '.join(r[0] for r in symbols)}")
        else:
            cursor = conn.execute("SELECT COUNT(*) FROM orders")
            total = cursor.fetchone()[0]

            cursor = conn.execute("""
                SELECT strftime('%Y', executed_at) as year, COUNT(*)
                FROM orders GROUP BY year ORDER BY year
            """)

            click.echo(f"Total orders: {total}")
            click.echo("\nBy year:")
            for y, count in cursor.fetchall():
                click.echo(f"  {y}: {count} orders")


@cli.command()
@click.option('--table', type=click.Choice(['orders', 'rates']), default='orders')
@click.option('--limit', type=int, default=20)
@click.option('--year', type=int)
def db(table, limit, year):
    """View database contents."""
    db_mgr = DatabaseManager(Config.DATABASE_PATH)

    with sqlite3.connect(db_mgr.db_path) as conn:
        conn.row_factory = sqlite3.Row

        if table == 'orders':
            click.echo("\n📋 ORDERS")
            click.echo("-" * 90)

            query = f"""
                SELECT order_id, symbol, side, quantity, price, currency, 
                       substr(executed_at, 1, 10) as date
                FROM orders 
                {'WHERE strftime("%Y", executed_at) = "' + str(year) + '"' if year else ''}
                ORDER BY executed_at DESC
                LIMIT {limit}
            """
            rows = conn.execute(query).fetchall()

            if rows:
                click.echo(f"{'Order ID':<22} {'Symbol':<12} {'Side':<6} {'Qty':<10} {'Price':<12} {'Curr':<6} {'Date'}")
                click.echo("-" * 90)
                for r in rows:
                    click.echo(
                        f"{r['order_id']:<22} {r['symbol']:<12} {r['side']:<6} "
                        f"{r['quantity']:<10.2f} {r['price']:<12.4f} {r['currency']:<6} {r['date']}"
                    )
            else:
                click.echo("No orders found.")

        elif table == 'rates':
            click.echo("\n💱 EXCHANGE RATES")
            click.echo("-" * 50)

            rows = conn.execute(f"""
                SELECT date, from_currency, to_currency, rate
                FROM exchange_rates ORDER BY date DESC LIMIT {limit}
            """).fetchall()

            if rows:
                click.echo(f"{'Date':<12} {'From':<6} {'To':<6} {'Rate'}")
                click.echo("-" * 40)
                for r in rows:
                    click.echo(f"{r['date']:<12} {r['from_currency']:<6} {r['to_currency']:<6} {r['rate']:.4f}")
            else:
                click.echo("No exchange rates found.")


@cli.command()
def setup():
    """Setup guide for first-time users."""
    click.echo("🚀 INVESTMENT TAX CALCULATOR SETUP")
    click.echo("=" * 50)

    click.echo("\n1. Get Long Bridge API credentials:")
    click.echo("   https://open.longbridge.com/")
    click.echo("   ⚠️  Only request READ permissions!")

    click.echo("\n2. Create .env file:")
    click.echo("   LONGBRIDGE_APP_KEY=your_key")
    click.echo("   LONGBRIDGE_APP_SECRET=your_secret")
    click.echo("   LONGBRIDGE_ACCESS_TOKEN=your_token")

    click.echo("\n3. Import data (first time, pull full history):")
    click.echo("   python cli.py import-data --year 2025 --since 2020-01-01")

    click.echo("\n4. Calculate tax:")
    click.echo("   python cli.py calculate --year 2025")


if __name__ == '__main__':
    cli()
