"""Unit tests for load_strategy() (src/engine/strategy_loader.py)."""

import textwrap
import pytest

from engine.strategy_loader import load_strategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_py(tmp_path, name: str, source: str):
    """Write *source* to a temporary .py file and return its path."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(source))
    return str(p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadStrategyValidStrategies:
    """load_strategy() should return a live instance when a valid class is present."""

    def test_returns_instance_with_evaluate_method(self, tmp_path):
        path = _write_py(tmp_path, "strategy_valid.py", """
            class MyAlpha:
                def evaluate(self, data):
                    return "buy"
        """)
        instance = load_strategy(path)
        assert hasattr(instance, "evaluate")
        assert callable(instance.evaluate)

    def test_returned_instance_is_correct_class(self, tmp_path):
        path = _write_py(tmp_path, "strategy_class.py", """
            class AlphaStrategy:
                def evaluate(self, data):
                    return 1
        """)
        instance = load_strategy(path)
        assert type(instance).__name__ == "AlphaStrategy"

    def test_evaluate_method_is_callable(self, tmp_path):
        path = _write_py(tmp_path, "strategy_callable.py", """
            class BetaStrategy:
                def evaluate(self, data):
                    return data * 2
        """)
        instance = load_strategy(path)
        assert instance.evaluate(5) == 10

    def test_strategy_with_multiple_classes_picks_one_with_evaluate(self, tmp_path):
        """Only the class with an evaluate method should be returned."""
        path = _write_py(tmp_path, "strategy_multi.py", """
            class HelperUtil:
                def compute(self):
                    pass

            class RealStrategy:
                def evaluate(self, market):
                    return "sell"
        """)
        instance = load_strategy(path)
        assert hasattr(instance, "evaluate")

    def test_strategy_with_extra_attributes(self, tmp_path):
        path = _write_py(tmp_path, "strategy_attrs.py", """
            class RichStrategy:
                name = "rich"

                def evaluate(self, x):
                    return x + self.name
        """)
        instance = load_strategy(path)
        assert instance.evaluate("hello") == "hellorich"

    def test_subclass_with_evaluate_is_loadable(self, tmp_path):
        path = _write_py(tmp_path, "strategy_sub.py", """
            class Base:
                def evaluate(self, x):
                    return x

            class Child(Base):
                pass
        """)
        instance = load_strategy(path)
        assert callable(instance.evaluate)


class TestLoadStrategyInvalidStrategies:
    """load_strategy() should raise ValueError when no valid class is found."""

    def test_raises_for_no_evaluate_method(self, tmp_path):
        path = _write_py(tmp_path, "strategy_no_eval.py", """
            class NotAStrategy:
                def compute(self):
                    pass
        """)
        with pytest.raises(ValueError, match="No valid strategy class found"):
            load_strategy(path)

    def test_raises_for_empty_file(self, tmp_path):
        path = _write_py(tmp_path, "strategy_empty.py", "")
        with pytest.raises(ValueError, match="No valid strategy class found"):
            load_strategy(path)

    def test_raises_for_functions_only(self, tmp_path):
        """A file with only module-level functions (no class) should raise."""
        path = _write_py(tmp_path, "strategy_funcs.py", """
            def evaluate(data):
                return data
        """)
        with pytest.raises(ValueError, match="No valid strategy class found"):
            load_strategy(path)

    def test_error_message_contains_file_path(self, tmp_path):
        path = _write_py(tmp_path, "strategy_bad.py", "x = 1")
        with pytest.raises(ValueError) as exc_info:
            load_strategy(path)
        assert str(path) in str(exc_info.value)
