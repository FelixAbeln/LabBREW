from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

from ..parameterdb_core.plugin_ui import normalize_ui_spec
from ..parameterdb_core.plugin_ui.spec import augment_type_defaults, augment_type_schema
from .plugin_api import PluginSpec


class PluginRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, PluginSpec] = {}
        self._ui_specs: dict[str, dict[str, Any]] = {}
        self._plugin_paths: dict[str, str] = {}

    def register(
        self,
        spec: PluginSpec,
        *,
        ui_spec: dict[str, Any] | None = None,
        path: str | None = None,
    ) -> None:
        self._specs[spec.parameter_type] = spec
        self._ui_specs[spec.parameter_type] = normalize_ui_spec(
            spec.parameter_type,
            ui_spec,
            display_name=spec.display_name,
            description=spec.description,
        )
        if path is not None:
            self._plugin_paths[spec.parameter_type] = path

    def get(self, parameter_type: str) -> PluginSpec:
        try:
            return self._specs[parameter_type]
        except KeyError as exc:
            raise ValueError(f"Unknown parameter type '{parameter_type}'") from exc

    def list_types(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "display_name": spec.display_name,
                "description": spec.description,
                "default_config": augment_type_defaults(spec.default_config()),
                "schema": augment_type_schema(spec.schema()),
                "has_ui": name in self._ui_specs,
                "plugin_path": self._plugin_paths.get(name),
            }
            for name, spec in sorted(self._specs.items())
        }

    def list_ui(self) -> dict[str, dict[str, Any]]:
        return {
            parameter_type: {
                "parameter_type": spec["parameter_type"],
                "display_name": spec["display_name"],
                "description": spec["description"],
            }
            for parameter_type, spec in sorted(self._ui_specs.items())
        }

    def get_ui_spec(self, parameter_type: str) -> dict[str, Any]:
        try:
            return self._ui_specs[parameter_type]
        except KeyError as exc:
            raise ValueError(f"Unknown parameter type '{parameter_type}'") from exc


def _load_py_module(pyfile: Path):
    module_name = f"plugin_{pyfile.stem}_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, pyfile)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from '{pyfile}'")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_ui_spec(ui_module: Any | None) -> dict[str, Any] | None:
    if ui_module is None:
        return None
    if hasattr(ui_module, "get_ui_spec"):
        spec = ui_module.get_ui_spec()
        if spec is not None and not isinstance(spec, dict):
            raise TypeError("get_ui_spec() must return a dict")
        return spec
    spec = getattr(ui_module, "UI_SPEC", None)
    if spec is not None and not isinstance(spec, dict):
        raise TypeError("UI_SPEC must be a dict")
    return spec


def _folder_to_module_base(path: Path) -> str:
    parts = list(path.parts)
    try:
        start = parts.index("Services")
    except ValueError as exc:
        raise ValueError(f"Cannot derive module path from '{path}'") from exc
    return ".".join(parts[start:])


def load_parameter_type_folder(folder: str | Path, registry: PluginRegistry) -> str:
    plugin_dir = Path(folder).resolve()
    impl_file = plugin_dir / "implementation.py"
    if not impl_file.exists():
        raise FileNotFoundError(f"Missing implementation.py in {plugin_dir}")

    module_base = _folder_to_module_base(plugin_dir)

    impl = importlib.import_module(f"{module_base}.implementation")

    spec = impl.PLUGIN
    if not isinstance(spec, PluginSpec):
        raise TypeError(f"{impl_file} must expose PLUGIN = PluginSpec instance")

    ui_spec = None
    ui_file = plugin_dir / "ui.py"
    if ui_file.exists():
        ui_module = importlib.import_module(f"{module_base}.ui")
        ui_spec = _extract_ui_spec(ui_module)

    registry.register(spec, ui_spec=ui_spec, path=str(plugin_dir))
    return spec.parameter_type


def autodiscover_plugins(root: str | Path, registry: PluginRegistry) -> list[str]:
    root_path = Path(root).resolve()
    if not root_path.exists():
        return []
    loaded: list[str] = []
    for child in sorted(root_path.iterdir()):
        if child.is_dir() and (child / "implementation.py").exists():
            loaded.append(load_parameter_type_folder(child, registry))
    return loaded
