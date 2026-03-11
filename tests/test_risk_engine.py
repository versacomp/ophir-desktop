"""Unit tests for the AccountState dataclass (src/ai/risk_engine.py)."""

from dataclasses import fields

import pytest

from ai.risk_engine import AccountState


class TestAccountStateDefaults:
    """AccountState should be constructed with sensible defaults."""

    def test_default_balance(self):
        account = AccountState()
        assert account.current_balance == 50_000.0

    def test_default_high_water_mark(self):
        account = AccountState()
        assert account.high_water_mark == 50_000.0

    def test_default_open_margin(self):
        account = AccountState()
        assert account.open_margin == 0.0

    def test_default_unrealized_pnl(self):
        account = AccountState()
        assert account.unrealized_pnl == 0.0

    def test_default_current_position(self):
        account = AccountState()
        assert account.current_position == 0

    def test_default_balance_equals_high_water_mark(self):
        """At inception, balance and high-water mark are identical."""
        account = AccountState()
        assert account.current_balance == account.high_water_mark


class TestAccountStateCustomInit:
    """AccountState should accept custom values for all fields."""

    def test_custom_balance(self):
        account = AccountState(current_balance=75_000.0)
        assert account.current_balance == 75_000.0

    def test_custom_high_water_mark(self):
        account = AccountState(high_water_mark=60_000.0)
        assert account.high_water_mark == 60_000.0

    def test_custom_margin(self):
        account = AccountState(open_margin=3_500.0)
        assert account.open_margin == 3_500.0

    def test_custom_unrealized_pnl(self):
        account = AccountState(unrealized_pnl=-250.0)
        assert account.unrealized_pnl == -250.0

    def test_custom_position_long_micro(self):
        account = AccountState(current_position=1)
        assert account.current_position == 1

    def test_custom_position_long_mini(self):
        account = AccountState(current_position=2)
        assert account.current_position == 2

    def test_custom_position_short_micro(self):
        account = AccountState(current_position=-1)
        assert account.current_position == -1

    def test_custom_position_short_mini(self):
        account = AccountState(current_position=-2)
        assert account.current_position == -2


class TestAccountStateDataclassBehaviour:
    """AccountState should behave like a standard Python dataclass."""

    def test_field_count(self):
        assert len(fields(AccountState)) == 5

    def test_field_names(self):
        names = {f.name for f in fields(AccountState)}
        assert names == {
            "current_balance",
            "high_water_mark",
            "open_margin",
            "unrealized_pnl",
            "current_position",
        }

    def test_equality_same_values(self):
        a = AccountState(current_balance=50_000.0)
        b = AccountState(current_balance=50_000.0)
        assert a == b

    def test_equality_different_values(self):
        a = AccountState(current_balance=50_000.0)
        b = AccountState(current_balance=49_999.0)
        assert a != b

    def test_mutable_fields(self):
        """AccountState fields should be mutable (not frozen)."""
        account = AccountState()
        account.current_balance = 55_000.0
        assert account.current_balance == 55_000.0
