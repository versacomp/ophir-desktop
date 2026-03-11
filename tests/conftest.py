"""Shared pytest fixtures for the Ophir unit test suite."""

import numpy as np
import pandas as pd
import pytest

from ai.risk_engine import AccountState


def _make_ohlcv_df(n_rows: int = 20, seed: int = 42) -> pd.DataFrame:
    """Helper that builds a deterministic OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    prices = 18_000.0 + np.cumsum(rng.normal(0, 5, n_rows))
    return pd.DataFrame({
        "open": prices,
        "high": prices + rng.uniform(0, 10, n_rows),
        "low": prices - rng.uniform(0, 10, n_rows),
        "close": prices + rng.normal(0, 2, n_rows),
        "volume": rng.uniform(100, 1000, n_rows).astype(float),
    })


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """A 20-row OHLCV DataFrame suitable for most tests."""
    return _make_ohlcv_df(n_rows=20)


@pytest.fixture
def default_account() -> AccountState:
    """An AccountState at its default (fresh) values."""
    return AccountState()


@pytest.fixture
def profitable_account() -> AccountState:
    """An AccountState that is profitable (balance above high-water mark)."""
    return AccountState(
        current_balance=52_000.0,
        high_water_mark=52_000.0,
        open_margin=1_000.0,
        unrealized_pnl=250.0,
        current_position=1,
    )


@pytest.fixture
def drawdown_account() -> AccountState:
    """An AccountState that is in drawdown (balance below high-water mark)."""
    return AccountState(
        current_balance=48_000.0,
        high_water_mark=50_000.0,
        open_margin=5_000.0,
        unrealized_pnl=-200.0,
        current_position=-1,
    )
