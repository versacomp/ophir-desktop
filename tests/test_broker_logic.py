"""
Unit tests for the pure helper functions extracted from OphirBroker
(src/engine/broker.py): translate_symbol_for_yfinance() and get_lookback_days().
"""

import pytest

from engine.broker_utils import get_lookback_days, translate_symbol_for_yfinance


class TestTranslateSymbolForYfinance:
    """translate_symbol_for_yfinance() should map tastytrade symbols to YF tickers."""

    # --- Leading-slash removal ---

    def test_slash_prefix_removed(self):
        assert translate_symbol_for_yfinance("/NQ") == "NQ=F"

    def test_no_slash_prefix_unchanged(self):
        assert translate_symbol_for_yfinance("NQ") == "NQ=F"

    def test_slash_with_expiry_code(self):
        assert translate_symbol_for_yfinance("/MNQH6") == "MNQ=F"

    # --- Futures expiration code detection ---

    def test_futures_expiry_mnq(self):
        assert translate_symbol_for_yfinance("MNQH6") == "MNQ=F"

    def test_futures_expiry_es(self):
        assert translate_symbol_for_yfinance("ESZ5") == "ES=F"

    def test_futures_expiry_gc(self):
        assert translate_symbol_for_yfinance("GCQ4") == "GC=F"

    def test_futures_expiry_cl(self):
        assert translate_symbol_for_yfinance("CLF6") == "CL=F"

    def test_futures_expiry_two_digit_year(self):
        assert translate_symbol_for_yfinance("NQM25") == "NQ=F"

    # --- Raw base-symbol list ---

    def test_raw_base_es(self):
        assert translate_symbol_for_yfinance("ES") == "ES=F"

    def test_raw_base_nq(self):
        assert translate_symbol_for_yfinance("NQ") == "NQ=F"

    def test_raw_base_mnq(self):
        assert translate_symbol_for_yfinance("MNQ") == "MNQ=F"

    def test_raw_base_rtty(self):
        assert translate_symbol_for_yfinance("RTY") == "RTY=F"

    def test_raw_base_m2k(self):
        assert translate_symbol_for_yfinance("M2K") == "M2K=F"

    def test_raw_base_ym(self):
        assert translate_symbol_for_yfinance("YM") == "YM=F"

    def test_raw_base_mym(self):
        assert translate_symbol_for_yfinance("MYM") == "MYM=F"

    def test_raw_base_gc(self):
        assert translate_symbol_for_yfinance("GC") == "GC=F"

    def test_raw_base_mgc(self):
        assert translate_symbol_for_yfinance("MGC") == "MGC=F"

    def test_raw_base_cl(self):
        assert translate_symbol_for_yfinance("CL") == "CL=F"

    def test_raw_base_mcl(self):
        assert translate_symbol_for_yfinance("MCL") == "MCL=F"

    # --- Equity symbols should pass through unchanged ---

    def test_equity_aapl(self):
        assert translate_symbol_for_yfinance("AAPL") == "AAPL"

    def test_equity_tsla(self):
        assert translate_symbol_for_yfinance("TSLA") == "TSLA"

    def test_equity_spy(self):
        assert translate_symbol_for_yfinance("SPY") == "SPY"

    # --- Case-insensitivity: input should be upper-cased ---

    def test_lowercase_input_normalised(self):
        assert translate_symbol_for_yfinance("nq") == "NQ=F"

    def test_mixed_case_input_normalised(self):
        assert translate_symbol_for_yfinance("Aapl") == "AAPL"


class TestGetLookbackDays:
    """get_lookback_days() should return the correct calendar-day window."""

    def test_1m_returns_3_days(self):
        assert get_lookback_days("1m") == 3

    def test_5m_returns_5_days(self):
        assert get_lookback_days("5m") == 5

    def test_15m_returns_15_days(self):
        assert get_lookback_days("15m") == 15

    def test_1h_returns_45_days(self):
        assert get_lookback_days("1h") == 45

    def test_unknown_interval_returns_5_days(self):
        assert get_lookback_days("4h") == 5

    def test_empty_string_returns_default(self):
        assert get_lookback_days("") == 5

    def test_daily_interval_returns_default(self):
        assert get_lookback_days("1d") == 5
