import importlib.util
import inspect


def load_strategy(file_path: str) -> object:
    """
    Dynamically loads a strategy class from any .py file.
    Discovers the class by duck-typing: looks for the first class
    that has an 'evaluate' method.
    Returns a live instance, or raises on failure.
    """
    spec = importlib.util.spec_from_file_location("_ophir_strategy", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for _, obj in inspect.getmembers(module, inspect.isclass):
        if callable(getattr(obj, "evaluate", None)):
            return obj()

    raise ValueError(f"No valid strategy class found in '{file_path}'. "
                     f"Ensure the file contains a class with an 'evaluate' method.")
