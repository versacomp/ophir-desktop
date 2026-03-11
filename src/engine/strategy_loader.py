import sys
import os
import importlib.util
import inspect


def load_strategy(file_path: str) -> object:
    """
    Loads a strategy class from disk with full multi-file hot-reload support.

    Steps:
      1. Resolve the strategy's root directory.
      2. Evict all modules physically inside that directory from sys.modules,
         forcing Python to re-read them from disk instead of returning stale cache.
      3. Temporarily prepend the directory to sys.path so that sibling files
         (e.g. indicators.py) can be imported natively inside the strategy.
      4. Load the entry-point file, discover the strategy class by duck-typing,
         and return a live instance.
      5. Restore sys.path in all cases via finally.

    Raises:
      ValueError  — if no class with an 'evaluate' method is found.
      Any exception raised during module execution propagates normally.
    """
    strategy_dir = os.path.dirname(os.path.abspath(file_path))

    # --- CACHE EVICTION ---
    # Remove any module whose physical file lives inside the strategy directory.
    # This guarantees fresh reads on every load without touching stdlib or site-packages.
    to_evict = [
        name for name, mod in list(sys.modules.items())
        if getattr(mod, '__file__', None)
        and os.path.abspath(mod.__file__).startswith(strategy_dir)
    ]
    for name in to_evict:
        del sys.modules[name]

    # --- sys.path INJECTION ---
    # Prepend the strategy directory so `import indicators` resolves to
    # strategy_dir/indicators.py rather than anything on the global path.
    original_path = sys.path.copy()
    if strategy_dir not in sys.path:
        sys.path.insert(0, strategy_dir)

    try:
        spec = importlib.util.spec_from_file_location("_ophir_strategy", file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if callable(getattr(obj, "evaluate", None)):
                return obj()

        raise ValueError(
            f"No valid strategy class found in '{file_path}'. "
            f"Ensure the file contains a class with an 'evaluate' method."
        )

    finally:
        # Always restore sys.path so the IDE namespace stays clean.
        sys.path = original_path
