"""CSV report generation — pure output formatting, no business logic."""

import csv
from pathlib import Path
from typing import Dict


def export_csv(results: Dict, output_dir: Path,
               tax_rate: float,
               dividend_results: Dict | None = None) -> Path:
    """Export combined tax report to a single CSV file.

    Layout:
      1. Transaction details
      2. Per-symbol summary
      3. Capital gains totals
      4. Dividend details + tax (if any)
      5. Overall tax summary
    """
    output_dir.mkdir(exist_ok=True)
    year = results['year']
    report_path = output_dir / f'tax_report_{year}.csv'

    with open(report_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)

        _write_transactions(writer, results)
        _write_symbol_summary(writer, results)
        _write_capital_gains(writer, results, tax_rate)
        div_tax = _write_dividends(writer, dividend_results)
        _write_total(writer, results['total_tax'], div_tax)

    print(f"Exported: {report_path}")
    return report_path


def _write_transactions(writer, results: Dict):
    cols = [
        'order_id', 'symbol', 'date', 'quantity', 'price',
        'currency', 'commission_fee', 'rate', 'proceeds_cny',
        'cost_basis_cny', 'gain_loss',
    ]
    writer.writerow(['[ Transaction Details ]'])
    writer.writerow(cols)
    for tx in results['details']:
        writer.writerow([tx[c] for c in cols])
    writer.writerow([])


def _write_symbol_summary(writer, results: Dict):
    cols = ['Symbol', 'Gains (CNY)', 'Losses (CNY)',
            'Net (CNY)', 'Remaining Qty', 'Remaining Cost (CNY)']
    writer.writerow(['[ Per-Symbol Summary ]'])
    writer.writerow(cols)
    for sym, s in results['summary'].items():
        writer.writerow([
            sym, f"{s['gains']:.2f}", f"{s['losses']:.2f}",
            f"{s['gains'] - s['losses']:.2f}",
            s['remaining_qty'], f"{s['remaining_cost']:.2f}",
        ])
    writer.writerow([])


def _write_capital_gains(writer, results: Dict, tax_rate: float):
    writer.writerow(['[ Capital Gains ]'])
    writer.writerow(['Item', 'Amount (CNY)'])
    writer.writerow(['Total Gains', f"{results['total_gains']:.2f}"])
    writer.writerow(['Total Losses', f"{results['total_losses']:.2f}"])
    writer.writerow(['Net Gains', f"{results['net_gains']:.2f}"])
    writer.writerow(['Tax Rate', f"{tax_rate * 100:.0f}%"])
    writer.writerow(['Capital Gains Tax', f"{results['total_tax']:.2f}"])


def _write_dividends(writer, dividend_results: Dict | None) -> float:
    """Write dividend sections. Returns dividend tax owed."""
    if not dividend_results or not dividend_results['details']:
        return 0.0

    writer.writerow([])
    cols = ['symbol', 'date', 'currency', 'net_amount',
            'gross_amount', 'withheld', 'exchange_rate', 'gross_cny', 'withheld_cny']
    writer.writerow(['[ Dividend Details ]'])
    writer.writerow(cols)
    for d in dividend_results['details']:
        writer.writerow([
            d['symbol'], d['date'], d['currency'],
            f"{d['net_amount']:.2f}", f"{d['gross_amount']:.2f}",
            f"{d['withheld']:.2f}", d['exchange_rate'],
            f"{d['gross_cny']:.2f}", f"{d['withheld_cny']:.2f}",
        ])

    writer.writerow([])
    writer.writerow(['[ Dividend Tax ]'])
    writer.writerow(['Item', 'Amount (CNY)'])
    writer.writerow(['Gross Dividend Income', f"{dividend_results['total_gross_cny']:.2f}"])
    writer.writerow(['Foreign Tax Withheld', f"{dividend_results['total_withheld_cny']:.2f}"])
    writer.writerow(['China Tax (20%)', f"{dividend_results['total_china_tax']:.2f}"])
    writer.writerow(['Foreign Tax Credit', f"{dividend_results['total_credit']:.2f}"])
    writer.writerow(['Dividend Tax Owed', f"{dividend_results['total_tax_owed']:.2f}"])
    return dividend_results['total_tax_owed']


def _write_total(writer, capital_gains_tax: float, dividend_tax: float):
    writer.writerow([])
    writer.writerow(['[ Total Tax Owed ]'])
    writer.writerow(['Item', 'Amount (CNY)'])
    writer.writerow(['Capital Gains Tax', f"{capital_gains_tax:.2f}"])
    writer.writerow(['Dividend Tax', f"{dividend_tax:.2f}"])
    writer.writerow(['Total Tax Owed', f"{capital_gains_tax + dividend_tax:.2f}"])
