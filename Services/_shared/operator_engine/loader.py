import importlib
import pkgutil
from types import ModuleType

from .registry import OperatorRegistry


def load_registry() -> OperatorRegistry:
    """
    Load plugins from the sibling `plugins` package next to this loader.
    """
    if not __package__:
        raise RuntimeError("Cannot resolve plugin package without package context")

    return load_registry_from_package(f"{__package__}.plugins")


def load_registry_from_package(package: str) -> OperatorRegistry:
    """
    Load all operator plugins from a package.

    Example:
        load_registry_from_package("my_project.operator_engine.plugins")
    """
    registry = OperatorRegistry()

    pkg = importlib.import_module(package)

    for _, module_name, _ in pkgutil.iter_modules(pkg.__path__):
        full_name = f"{package}.{module_name}"
        module = importlib.import_module(full_name)

        _load_from_module(module, registry)

    return registry


def _load_from_module(module: ModuleType, registry: OperatorRegistry):
    if hasattr(module, "PLUGINS"):
        registry.register_many(module.PLUGINS)
        return

    for attr_name in dir(module):
        obj = getattr(module, attr_name)

        if hasattr(obj, "evaluate") and hasattr(obj, "metadata"):
            try:
                instance = obj() if isinstance(obj, type) else obj
                registry.register(instance)
            except Exception:
                pass
