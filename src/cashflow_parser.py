"""Parse Long Bridge cash flow entries into dividend records.

Extracts dividend payments and matches withholding tax entries by
timestamp proximity. Keeps CLI thin and parsing logic testable.

Real data pattern (from Long Bridge API):
  Cash Dividend  | +44.00 USD | desc="OXY.US Cash Dividend: 0.22 USD per Share, Held:200"
  CO Other FEE   | -4.40  USD | desc="OXY.US Cash Dividend: ... Withholding Tax/Dividend Fee"
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


def parse_dividends(entries: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Parse cash flow entries into dividend records with matched withholdings.

    Args:
        entries: Raw cash flow dicts from LongBridgeClient.fetch_cashflow().

    Returns:
        (dividends, unmatched_withholdings)
        Each dividend dict has: symbol, currency, amount, received_at,
        flow_name, description, withholding.
    """
    raw_divs, raw_whs = _split_entries(entries)
    _match_withholdings(raw_divs, raw_whs)

    unmatched = [wh for wh in raw_whs if not wh.get('_matched')]
    return raw_divs, unmatched


def summarize_by_symbol(dividends: List[Dict]) -> Dict[str, float]:
    """Aggregate net dividend amounts by symbol."""
    by_sym: Dict[str, float] = defaultdict(float)
    for d in dividends:
        by_sym[d['symbol']] += d['amount']
    return dict(by_sym)


def _split_entries(entries: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Separate cash flow entries into dividends and withholding taxes."""
    divs: List[Dict] = []
    whs: List[Dict] = []

    for e in entries:
        name = e['transaction_flow_name']
        desc = e.get('description', '')

        if name == 'Cash Dividend' and e['balance'] > 0:
            symbol = _extract_symbol(e['symbol'], desc)
            if not symbol:
                continue
            divs.append({
                'symbol': symbol,
                'currency': e['currency'],
                'amount': e['balance'],
                'received_at': e['business_time'],
                'flow_name': name,
                'description': desc,
                'withholding': 0.0,
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
