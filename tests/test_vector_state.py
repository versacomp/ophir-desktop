"""Unit tests for StateVectorizer.process_step() (src/ai/vector_state.py)."""

import numpy as np
import pandas as pd
import pytest

from ai.risk_engine import AccountState
from ai.vector_state import StateVectorizer


@pytest.fixture
def vectorizer() -> StateVectorizer:
    return StateVectorizer(lookback_window=10)


@pytest.fixture
def window_df() -> pd.DataFrame:
    """A 10-row OHLCV window with strictly increasing prices (no zero-division)."""
    rng = np.random.default_rng(0)
    prices = 18_000.0 + np.cumsum(rng.uniform(1, 5, 10))
    return pd.DataFrame({
        "open": prices,
        "high": prices + 3,
        "low": prices - 3,
        "close": prices + rng.uniform(-1, 1, 10),
        "volume": rng.uniform(200, 800, 10).astype(float),
    })


class TestStateVectorizerShape:
    """process_step() must return a 1-D array of the correct length."""

    def test_default_shape(self, vectorizer, window_df, default_account):
        result = vectorizer.process_step(window_df, default_account)
        # (5 features * 10 candles) + 4 account features = 54
        assert result.shape == (54,)

    def test_custom_lookback_shape(self, default_account):
        lb = 5
        v = StateVectorizer(lookback_window=lb)
        rng = np.random.default_rng(1)
        prices = 18_000.0 + np.cumsum(rng.uniform(1, 5, lb))
        df = pd.DataFrame({
            "open": prices, "high": prices + 2,
            "low": prices - 2, "close": prices,
            "volume": rng.uniform(100, 500, lb).astype(float),
        })
        result = v.process_step(df, default_account)
        assert result.shape == ((5 * lb) + 4,)

    def test_shape_attribute_matches_output(self, vectorizer, window_df, default_account):
        result = vectorizer.process_step(window_df, default_account)
        assert result.shape == vectorizer.shape


class TestStateVectorizerDtype:
    """process_step() must return a float32 array (GPU-ready)."""

    def test_dtype_is_float32(self, vectorizer, window_df, default_account):
        result = vectorizer.process_step(window_df, default_account)
        assert result.dtype == np.float32


class TestStateVectorizerAccountFeatures:
    """The last 4 elements represent account state features."""

    def test_zero_drawdown_for_default_account(self, vectorizer, window_df, default_account):
        result = vectorizer.process_step(window_df, default_account)
        # drawdown = (50000 - 50000) / 50000 = 0.0
        assert result[-4] == pytest.approx(0.0)

    def test_negative_drawdown_for_loss(self, vectorizer, window_df):
        account = AccountState(current_balance=48_000.0, high_water_mark=50_000.0)
        result = vectorizer.process_step(window_df, account)
        expected_drawdown = (48_000.0 - 50_000.0) / 50_000.0  # -0.04
        assert result[-4] == pytest.approx(expected_drawdown, rel=1e-5)

    def test_margin_utilization_normalised(self, vectorizer, window_df):
        account = AccountState(open_margin=5_000.0)
        result = vectorizer.process_step(window_df, account)
        # margin_utilization = 5000 / 10000 = 0.5
        assert result[-3] == pytest.approx(0.5, rel=1e-5)

    def test_zero_margin_utilization(self, vectorizer, window_df, default_account):
        result = vectorizer.process_step(window_df, default_account)
        assert result[-3] == pytest.approx(0.0)

    def test_pnl_ratio_positive(self, vectorizer, window_df):
        account = AccountState(unrealized_pnl=500.0)
        result = vectorizer.process_step(window_df, account)
        # pnl_ratio = 500 / 500 = 1.0
        assert result[-2] == pytest.approx(1.0, rel=1e-5)

    def test_pnl_ratio_negative(self, vectorizer, window_df):
        account = AccountState(unrealized_pnl=-250.0)
        result = vectorizer.process_step(window_df, account)
        # pnl_ratio = -250 / 500 = -0.5
        assert result[-2] == pytest.approx(-0.5, rel=1e-5)

    def test_flat_position_scaled(self, vectorizer, window_df, default_account):
        result = vectorizer.process_step(window_df, default_account)
        # position_scaled = 0 / 2 = 0.0
        assert result[-1] == pytest.approx(0.0)

    def test_long_micro_position_scaled(self, vectorizer, window_df):
        account = AccountState(current_position=1)
        result = vectorizer.process_step(window_df, account)
        # position_scaled = 1 / 2 = 0.5
        assert result[-1] == pytest.approx(0.5, rel=1e-5)

    def test_short_mini_position_scaled(self, vectorizer, window_df):
        account = AccountState(current_position=-2)
        result = vectorizer.process_step(window_df, account)
        # position_scaled = -2 / 2 = -1.0
        assert result[-1] == pytest.approx(-1.0, rel=1e-5)


class TestStateVectorizerMarketFeatures:
    """The first (5 * lookback_window) elements encode percentage returns."""

    def test_first_row_is_zero(self, vectorizer, window_df, default_account):
        """pct_change().fillna(0) sets the first row to zero for all columns."""
        result = vectorizer.process_step(window_df, default_account)
        market_part = result[:50]
        np.testing.assert_array_equal(market_part[:5], np.zeros(5, dtype=np.float32))

    def test_constant_price_series_produces_zero_returns(self, vectorizer, default_account):
        df = pd.DataFrame({
            "open": [18_000.0] * 10,
            "high": [18_010.0] * 10,
            "low": [17_990.0] * 10,
            "close": [18_000.0] * 10,
            "volume": [500.0] * 10,
        })
        result = vectorizer.process_step(df, default_account)
        market_part = result[:50]
        np.testing.assert_array_equal(market_part, np.zeros(50, dtype=np.float32))


class TestStateVectorizerNaNInfSafety:
    """process_step() must sanitise any NaN / inf values that arise."""

    def test_nan_replaced_with_zero(self, vectorizer, default_account):
        # A price of 0 followed by any non-zero will produce NaN from pct_change
        df = pd.DataFrame({
            "open": [0.0] + [18_000.0] * 9,
            "high": [0.0] + [18_010.0] * 9,
            "low": [0.0] + [17_990.0] * 9,
            "close": [0.0] + [18_000.0] * 9,
            "volume": [0.0] + [500.0] * 9,
        })
        result = vectorizer.process_step(df, default_account)
        assert not np.any(np.isnan(result))
        assert not np.any(np.isinf(result))

    def test_output_always_finite(self, vectorizer, window_df, default_account):
        result = vectorizer.process_step(window_df, default_account)
        assert np.all(np.isfinite(result))
