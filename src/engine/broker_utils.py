"""
Pure utility functions for broker symbol/interval translation.

These functions are kept in a separate module so they can be imported and
unit-tested without pulling in network or authentication dependencies.
"""

import re


# Futures base-ticker symbols that have no expiration code but still map to =F
_FUTURES_BASE_SYMBOLS = frozenset({
    "ES", "MES", "NQ", "MNQ", "RTY", "M2K", "YM", "MYM",
    "GC", "MGC", "CL", "MCL",
})

# Regex that detects a ticker with an attached expiration code, e.g. MNQH6, ESZ25
_FUTURES_EXPIRY_RE = re.compile(r'^([A-Z]+)[FGHJKMNQUVXZ]\d{1,2}$')


def translate_symbol_for_yfinance(symbol: str) -> str:
    """
    Translates a tastytrade symbol to a Yahoo Finance compatible ticker.

    Handles three cases:
    - Futures with expiration codes (e.g. /MNQH6  -> MNQ=F)
    - Raw base futures symbols      (e.g. NQ      -> NQ=F)
    - Equities / other symbols are returned unchanged (e.g. AAPL -> AAPL)
    """
    yf_symbol = symbol.upper().lstrip('/')

    match = _FUTURES_EXPIRY_RE.match(yf_symbol)
    if match:
        base = match.group(1)
        return f"{base}=F"

    if yf_symbol in _FUTURES_BASE_SYMBOLS:
        return f"{yf_symbol}=F"

    return yf_symbol


def get_lookback_days(interval: str) -> int:
    """
    Returns the number of calendar days to look back for a given candle interval.

    Chosen to ensure at least 200 candles are available for the Alpha Engine:

    ======== =========
    Interval Days back
    ======== =========
    1m       3
    5m       5
    15m      15
    1h       45
    other    5
    ======== =========
    """
    _MAP = {"1m": 3, "5m": 5, "15m": 15, "1h": 45}
    return _MAP.get(interval, 5)
