from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .base import DataSourceSpec


@dataclass(slots=True)
class LoadedSourceType:
    source_type: str
    folder: str
    ui_spec: dict[str, Any] | None = None


class DataSourceRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, DataSourceSpec] = {}
        self._ui_specs: dict[str, Any] = {}

    def register(self, spec: DataSourceSpec, ui_spec: Any | None = None) -> None:
        self._specs[spec.source_type] = spec
        if ui_spec is not None:
            self._ui_specs[spec.source_type] = ui_spec

    def get(self, source_type: str) -> DataSourceSpec:
        try:
            return self._specs[source_type]
        except KeyError as exc:
            raise KeyError(f"Unknown data source type '{source_type}'") from exc

    def list_types(self) -> list[str]:
        return sorted(self._specs)

    def _resolve_ui_spec(
        self,
        source_type: str,
        *,
        record: dict[str, Any] | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        try:
            provider = self._ui_specs[source_type]
        except KeyError as exc:
            raise KeyError(f"Unknown data source type '{source_type}'") from exc
        if callable(provider):
            try:
                value = provider(record=record, mode=mode)
            except TypeError:
                value = provider()
        else:
            value = provider
        if not isinstance(value, dict):
            raise TypeError(f"UI spec provider for '{source_type}' must return a dict")
        return dict(value)

    def list_ui(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for source_type in sorted(self._ui_specs):
            spec = self._resolve_ui_spec(source_type)
            result[source_type] = {
                "source_type": source_type,
                "display_name": spec.get("display_name", source_type),
                "description": spec.get("description", ""),
            }
        return result

    def get_ui_spec(
        self,
        source_type: str,
        *,
        record: dict[str, Any] | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        return self._resolve_ui_spec(source_type, record=record, mode=mode)


def _load_py_module(pyfile: Path) -> ModuleType:
    module_name = f"source_{pyfile.stem}_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, pyfile)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from '{pyfile}'")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(module_name, None)
        raise


def _extract_ui_spec(ui_module: Any | None) -> Any | None:
    if ui_module is None:
        return None
    if hasattr(ui_module, "get_ui_spec"):
        return ui_module.get_ui_spec
    if hasattr(ui_module, "UI_SPEC"):
        return dict(ui_module.UI_SPEC)
    return None


def load_source_folder(
    folder: str | Path, registry: DataSourceRegistry
) -> LoadedSourceType:
    path = Path(folder)
    print(path)

    service_file = path / "service.py"
    ui_file = path / "ui.py"

    if not service_file.exists():
        raise FileNotFoundError(f"Missing service.py in '{path}'")

    module_base = ".".join(path.parts[-4:])  # adjust if needed
    # For your example this should become:
    # Services.parameterDB.sourceDefs.brewtools_kvaser

    service_module = importlib.import_module(f"{module_base}.service")
    ui_module = (
        importlib.import_module(f"{module_base}.ui") if ui_file.exists() else None
    )

    spec = getattr(service_module, "SOURCE", None)
    if spec is None:
        raise ValueError(f"'{service_file}' must define SOURCE")

    ui_spec = _extract_ui_spec(ui_module)
    registry.register(spec, ui_spec)
    return LoadedSourceType(
        source_type=spec.source_type, folder=str(path), ui_spec=ui_spec
    )


def autodiscover_sources(root: str | Path, registry: DataSourceRegistry) -> list[str]:
    path = Path(root)
    print(path)
    if not path.exists():
        print("path n9t foudn")
        return []
    loaded: list[str] = []
    for child in sorted(path.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        try:
            info = load_source_folder(child, registry)
            loaded.append(info.source_type)
        except Exception as e:
            print(e)
    print(loaded)
    return loaded
