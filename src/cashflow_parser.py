"""Parse raw cash flow entries into dividend records.

This is a pure processing layer — it takes raw cash flow dicts (as stored
in the cashflows table) and produces dividend records ready for tax
calculation.  No DB access, no API calls.

Processing steps:
  1. Split entries into dividends (Cash Dividend) and withholdings (CO Other FEE).
  2. For HK H-shares: detect embedded withholding from description (-XX%),
     back-calculate gross from the NET balance.
  3. Match remaining withholding entries to dividends by timestamp proximity.
"""

import re
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple

# Max time gap (seconds) between a dividend and its withholding entry.
_WITHHOLDING_MATCH_WINDOW = timedelta(seconds=120)

# Regex to extract symbol from dividend description.
# Examples: "OXY.US Cash Dividend: ..." → "OXY.US"
#           "#00700 Cash Dividend: ..." → "00700" (HK, # stripped)
_SYMBOL_RE = re.compile(r'^#?(\S+?)[\s(]')

# HK H-share dividends embed the withholding rate in the description.
# Example: "RMB0.56/SH(-10%)" → 10
# The balance is already NET (after deduction), so we back-calculate gross.
_EMBEDDED_WHT_RE = re.compile(r'\(-(\d+)%\)')


def parse_dividends(entries: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Parse raw cash flow entries into dividend records with matched withholdings.

    Args:
        entries: Raw cash flow dicts (from DB cashflows table or API).
                 Each must have: transaction_flow_name, balance, currency,
                 business_time, symbol, description.

    Returns:
        (dividends, unmatched_withholdings)
        Each dividend dict has: symbol, currency, amount (gross),
        received_at, flow_name, description, withholding.
    """
    raw_divs, raw_whs = _split_entries(entries)
    _match_withholdings(raw_divs, raw_whs)

    unmatched = [wh for wh in raw_whs if not wh.get('_matched')]
    return raw_divs, unmatched


def summarize_by_symbol(dividends: List[Dict]) -> Dict[str, float]:
    """Aggregate net dividend amounts by symbol (gross - withholding)."""
    by_sym: Dict[str, float] = defaultdict(float)
    for d in dividends:
        by_sym[d['symbol']] += d['amount'] - d['withholding']
    return dict(by_sym)


def _split_entries(entries: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Separate cash flow entries into dividends and withholding taxes."""
    divs: List[Dict] = []
    whs: List[Dict] = []

    for e in entries:
        name = e['transaction_flow_name']
        desc = e.get('description', '')

        if name == 'Cash Dividend' and e['balance'] > 0:
            symbol = _extract_symbol(e.get('symbol'), desc)
            if not symbol:
                continue

            amount = e['balance']
            withholding = 0.0

            # HK H-shares: withholding is embedded in the description as (-XX%)
            # and already deducted from the balance.  Back-calculate gross.
            embedded_rate = _parse_embedded_wht(desc)
            if embedded_rate:
                gross = amount / (1 - embedded_rate)
                withholding = gross - amount
                amount = gross  # normalize to gross for consistency

            divs.append({
                'symbol': symbol,
                'currency': e['currency'],
                'amount': amount,
                'received_at': e['business_time'],
                'flow_name': name,
                'description': desc,
                'withholding': withholding,
            })

        elif _is_withholding(desc):
            whs.append({
                'amount': abs(e['balance']),
                'received_at': e['business_time'],
                'currency': e['currency'],
                'description': desc,
                '_matched': False,
            })

    return divs, whs


def _extract_symbol(raw_symbol: str | None, description: str) -> str | None:
    """Resolve symbol from the entry's symbol field or description text.

    HK symbols arrive prefixed with '#' (e.g. '#00700') — strip it.
    Symbols without a market suffix get '.US' appended.
    """
    if raw_symbol:
        sym = raw_symbol.lstrip('#')
    else:
        m = _SYMBOL_RE.match(description)
        if not m:
            return None
        sym = m.group(1)

    if '.' not in sym:
        sym += '.US'
    return sym


def _is_withholding(description: str) -> bool:
    """Check if a cash flow description indicates withholding tax."""
    lower = description.lower()
    return 'withholding tax' in lower or 'dividend fee' in lower


def _parse_embedded_wht(description: str) -> float | None:
    """Extract embedded withholding tax rate from HK H-share descriptions.

    Example: "RMB0.56/SH(-10%)" → 0.10
    Returns None if no embedded rate found.
    """
    m = _EMBEDDED_WHT_RE.search(description)
    if m:
        return int(m.group(1)) / 100
    return None


def _match_withholdings(divs: List[Dict], whs: List[Dict]):
    """Match each withholding entry to the nearest dividend by timestamp.

    Mutates dividend dicts in-place (adds to 'withholding' field).
    Mutates withholding dicts (sets '_matched' flag).
    Only matches entries with the same currency within the time window.
    """
    for wh in whs:
        wh_time = datetime.fromisoformat(wh['received_at'])
        best = None
        best_delta = _WITHHOLDING_MATCH_WINDOW + timedelta(seconds=1)

        for div in divs:
            if div['currency'] != wh['currency']:
                continue
            delta = abs(wh_time - datetime.fromisoformat(div['received_at']))
            if delta < best_delta:
                best_delta = delta
                best = div

        if best and best_delta <= _WITHHOLDING_MATCH_WINDOW:
            best['withholding'] += wh['amount']
            wh['_matched'] = True
