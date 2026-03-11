"""Unit tests for CitadelEnv (src/ai/env.py)."""

import numpy as np
import pandas as pd
import pytest

from ai.env import CitadelEnv
from ai.risk_engine import AccountState


def _make_env(n_rows: int = 50, seed: int = 7) -> CitadelEnv:
    """Build a CitadelEnv backed by a deterministic OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    prices = 18_000.0 + np.cumsum(rng.normal(0, 5, n_rows))
    df = pd.DataFrame({
        "open": prices,
        "high": prices + rng.uniform(0, 10, n_rows),
        "low": prices - rng.uniform(0, 10, n_rows),
        "close": prices + rng.normal(0, 2, n_rows),
        "volume": rng.uniform(100, 1000, n_rows).astype(float),
    })
    return CitadelEnv(df)


class TestCitadelEnvInit:
    """CitadelEnv should initialise with the correct spaces and attributes."""

    def test_action_space_size(self):
        env = _make_env()
        assert env.action_space.n == 3

    def test_observation_space_shape(self):
        env = _make_env()
        # (5 * 10) + 4 = 54
        assert env.observation_space.shape == (54,)

    def test_max_steps(self):
        env = _make_env(n_rows=50)
        assert env.max_steps == 49  # len(df) - 1

    def test_initial_step_is_zero(self):
        env = _make_env()
        assert env.current_step == 0

    def test_initial_account_is_default(self):
        env = _make_env()
        assert env.account == AccountState()


class TestCitadelEnvReset:
    """reset() should reinitialise the environment to a clean state."""

    def test_reset_returns_tuple(self):
        env = _make_env()
        result = env.reset()
        assert isinstance(result, tuple) and len(result) == 2

    def test_reset_observation_shape(self):
        env = _make_env()
        obs, _ = env.reset()
        assert obs.shape == (54,)

    def test_reset_observation_dtype(self):
        env = _make_env()
        obs, _ = env.reset()
        assert obs.dtype == np.float32

    def test_reset_info_is_empty_dict(self):
        env = _make_env()
        _, info = env.reset()
        assert info == {}

    def test_reset_step_set_to_lookback_window(self):
        env = _make_env()
        env.reset()
        assert env.current_step == env.vectorizer.lookback_window

    def test_reset_restores_default_account(self):
        env = _make_env()
        env.reset()
        env.account.current_balance = 999.0
        env.reset()
        assert env.account == AccountState()

    def test_reset_with_seed(self):
        env = _make_env()
        obs1, _ = env.reset(seed=1)
        obs2, _ = env.reset(seed=1)
        np.testing.assert_array_equal(obs1, obs2)


class TestCitadelEnvStep:
    """step() should compute PnL, update account state, and return the correct tuple."""

    def _price_delta(self, env: CitadelEnv) -> float:
        """Return the price delta that the *next* step will see."""
        step = env.current_step
        return float(env.df.iloc[step + 1]["close"] - env.df.iloc[step]["close"])

    def test_step_returns_five_tuple(self):
        env = _make_env()
        env.reset()
        result = env.step(0)
        assert isinstance(result, tuple) and len(result) == 5

    def test_step_observation_shape(self):
        env = _make_env()
        env.reset()
        obs, *_ = env.step(0)
        assert obs.shape == (54,)

    def test_step_observation_dtype(self):
        env = _make_env()
        env.reset()
        obs, *_ = env.step(0)
        assert obs.dtype == np.float32

    def test_step_flat_action_zero_pnl(self):
        """Action 0 (Flat) has multiplier 0 → step_pnl is always 0."""
        env = _make_env()
        env.reset()
        initial_balance = env.account.current_balance
        _, reward, _, _, info = env.step(0)
        assert reward == pytest.approx(0.0)
        assert info["balance"] == pytest.approx(initial_balance)

    def test_step_micro_long_positive_move(self):
        """Action 1 (Micro) with price_delta=+1 → PnL = 1 * 2 = 2."""
        env = _make_env()
        env.reset()

        # Manually set a guaranteed price delta
        step = env.current_step
        env.df.at[step + 1, "close"] = env.df.at[step, "close"] + 1.0

        _, reward, _, _, info = env.step(1)
        assert reward == pytest.approx(2.0)
        assert info["balance"] == pytest.approx(50_002.0)

    def test_step_mini_long_positive_move(self):
        """Action 2 (Mini) with price_delta=+1 → PnL = 1 * 20 = 20."""
        env = _make_env()
        env.reset()

        step = env.current_step
        env.df.at[step + 1, "close"] = env.df.at[step, "close"] + 1.0

        _, reward, _, _, info = env.step(2)
        assert reward == pytest.approx(20.0)
        assert info["balance"] == pytest.approx(50_020.0)

    def test_step_micro_long_negative_move(self):
        """Action 1 (Micro) with price_delta=-5 → PnL = -5 * 2 = -10."""
        env = _make_env()
        env.reset()

        step = env.current_step
        env.df.at[step + 1, "close"] = env.df.at[step, "close"] - 5.0

        _, reward, _, _, info = env.step(1)
        assert reward == pytest.approx(-10.0)
        assert info["balance"] == pytest.approx(49_990.0)

    def test_step_increments_current_step(self):
        env = _make_env()
        env.reset()
        step_before = env.current_step
        env.step(0)
        assert env.current_step == step_before + 1

    def test_step_updates_position(self):
        env = _make_env()
        env.reset()
        env.step(2)
        assert env.account.current_position == 2

    def test_step_info_contains_balance(self):
        env = _make_env()
        env.reset()
        _, _, _, _, info = env.step(0)
        assert "balance" in info


class TestCitadelEnvHighWaterMark:
    """High-water mark should only increase, never decrease."""

    def test_high_water_mark_updates_on_profit(self):
        env = _make_env()
        env.reset()

        step = env.current_step
        env.df.at[step + 1, "close"] = env.df.at[step, "close"] + 100.0

        env.step(2)  # Mini long: +100 * 20 = +2000
        assert env.account.high_water_mark == pytest.approx(52_000.0)
        assert env.account.current_balance == pytest.approx(52_000.0)

    def test_high_water_mark_does_not_decrease_on_loss(self):
        env = _make_env()
        env.reset()

        step = env.current_step
        env.df.at[step + 1, "close"] = env.df.at[step, "close"] - 10.0

        env.step(1)  # Micro short loss: -10 * 2 = -20
        assert env.account.high_water_mark == pytest.approx(50_000.0)
        assert env.account.current_balance == pytest.approx(49_980.0)


class TestCitadelEnvTermination:
    """Termination and truncation conditions must fire at the right thresholds."""

    def test_terminated_when_balance_below_threshold(self):
        env = _make_env()
        env.reset()

        # Force the balance below the 45k threshold
        env.account.current_balance = 45_001.0

        step = env.current_step
        # A loss of $2 on a micro position (price_delta = -1) → new balance = 44999
        env.df.at[step + 1, "close"] = env.df.at[step, "close"] - 1.0

        _, reward, terminated, _, _ = env.step(1)
        assert terminated is True

    def test_reward_penalised_when_blown(self):
        env = _make_env()
        env.reset()

        env.account.current_balance = 45_001.0
        step = env.current_step
        env.df.at[step + 1, "close"] = env.df.at[step, "close"] - 1.0

        _, reward, terminated, _, _ = env.step(1)
        # step_pnl = -2.0; penalty = -5000; total = -5002
        assert reward == pytest.approx(-5_002.0)

    def test_not_terminated_when_balance_above_threshold(self):
        env = _make_env()
        env.reset()
        _, _, terminated, _, _ = env.step(0)
        assert terminated is False

    def test_truncated_at_final_step(self):
        env = _make_env(n_rows=12)  # max_steps = 11
        env.reset()  # current_step = 10

        # Advance to max_steps
        _, _, _, truncated, _ = env.step(0)
        assert truncated is True

    def test_not_truncated_before_final_step(self):
        env = _make_env(n_rows=50)
        env.reset()
        _, _, _, truncated, _ = env.step(0)
        assert truncated is False


class TestCitadelEnvGetObservation:
    """_get_observation() must produce a well-shaped, finite float32 array."""

    def test_observation_shape_after_reset(self):
        env = _make_env()
        env.reset()
        obs = env._get_observation()
        assert obs.shape == (54,)

    def test_observation_dtype_after_reset(self):
        env = _make_env()
        env.reset()
        obs = env._get_observation()
        assert obs.dtype == np.float32

    def test_observation_is_finite(self):
        env = _make_env()
        env.reset()
        obs = env._get_observation()
        assert np.all(np.isfinite(obs))
