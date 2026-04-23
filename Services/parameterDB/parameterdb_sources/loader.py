from __future__ import annotations

import importlib
import inspect
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import DataSourceSpec


LOGGER = logging.getLogger(__name__)


def _load_py_module(path: str | Path) -> Any:
    module_path = Path(path)
    module_name = f"source_{module_path.stem}_{abs(hash(str(module_path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from '{module_path}'")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _call_ui_spec_provider(provider: Any, *, record: dict[str, Any] | None, mode: str | None) -> Any:
    try:
        signature = inspect.signature(provider)
    except (TypeError, ValueError):
        return provider(record=record, mode=mode)

    params = signature.parameters
    accepts_var_kwargs = any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
    )
    kwargs: dict[str, Any] = {}

    if accepts_var_kwargs or "record" in params:
        kwargs["record"] = record
    elif "_record" in params:
        kwargs["_record"] = record

    if accepts_var_kwargs or "mode" in params:
        kwargs["mode"] = mode
    elif "_mode" in params:
        kwargs["_mode"] = mode

    if kwargs or accepts_var_kwargs:
        return provider(**kwargs)
    return provider()


def _call_ui_action_provider(
    provider: Any,
    *,
    action_name: str,
    action_payload: dict[str, Any],
    record: dict[str, Any] | None,
) -> Any:
    try:
        signature = inspect.signature(provider)
    except (TypeError, ValueError):
        return provider(action=action_name, payload=action_payload, record=record)

    params = signature.parameters
    accepts_var_kwargs = any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
    )
    kwargs: dict[str, Any] = {}

    if accepts_var_kwargs or "action" in params:
        kwargs["action"] = action_name
    elif "action_name" in params:
        kwargs["action_name"] = action_name

    if accepts_var_kwargs or "payload" in params:
        kwargs["payload"] = action_payload
    elif "action_payload" in params:
        kwargs["action_payload"] = action_payload

    if accepts_var_kwargs or "record" in params:
        kwargs["record"] = record
    elif "_record" in params:
        kwargs["_record"] = record

    if kwargs or accepts_var_kwargs:
        return provider(**kwargs)

    positional = [
        param
        for param in params.values()
        if param.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if len(positional) >= 3:
        return provider(action_name, action_payload, record)
    if len(positional) >= 2:
        return provider(action_name, action_payload)
    if len(positional) >= 1:
        return provider(action_name)
    return provider()


@dataclass(slots=True)
class LoadedSourceType:
    source_type: str
    folder: str
    ui_spec: dict[str, Any] | None = None


class DataSourceRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, DataSourceSpec] = {}
        self._ui_specs: dict[str, Any] = {}
        self._ui_actions: dict[str, Any] = {}

    def register(
        self,
        spec: DataSourceSpec,
        ui_spec: Any | None = None,
        ui_actions: Any | None = None,
    ) -> None:
        self._specs[spec.source_type] = spec
        if ui_spec is not None:
            self._ui_specs[spec.source_type] = ui_spec
        if ui_actions is not None:
            self._ui_actions[spec.source_type] = ui_actions

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
            value = _call_ui_spec_provider(provider, record=record, mode=mode)
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

    def invoke_ui_action(
        self,
        source_type: str,
        action: str,
        *,
        payload: dict[str, Any] | None = None,
        record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            provider = self._ui_actions[source_type]
        except KeyError as exc:
            raise KeyError(
                f"Data source type '{source_type}' does not support UI module actions"
            ) from exc
        if not callable(provider):
            raise TypeError(
                f"UI action provider for '{source_type}' must be callable"
            )
        action_name = str(action or "").strip()
        if not action_name:
            raise ValueError("Action must be a non-empty string")
        action_payload = dict(payload or {})
        result = _call_ui_action_provider(
            provider,
            action_name=action_name,
            action_payload=action_payload,
            record=record,
        )
        if not isinstance(result, dict):
            raise TypeError(
                f"UI action provider for '{source_type}' must return a dict"
            )
        return dict(result)


def _folder_to_module_base(path: Path) -> str:
    parts = list(path.parts)
    try:
        start = parts.index("Services")
    except ValueError as exc:
        raise ValueError(f"Cannot derive module path from '{path}'") from exc
    return ".".join(parts[start:])


def _extract_ui_spec(ui_module: Any | None) -> Any | None:
    if ui_module is None:
        return None
    if hasattr(ui_module, "get_ui_spec"):
        return ui_module.get_ui_spec
    if hasattr(ui_module, "UI_SPEC"):
        return dict(ui_module.UI_SPEC)
    return None


def _extract_ui_actions(ui_module: Any | None) -> Any | None:
    if ui_module is None:
        return None
    if hasattr(ui_module, "invoke_ui_action"):
        return ui_module.invoke_ui_action
    if hasattr(ui_module, "run_ui_action"):
        return ui_module.run_ui_action
    return None


def _is_package_import_failure(exc: ModuleNotFoundError, module_name: str) -> bool:
    missing = str(getattr(exc, "name", "") or "").strip()
    if not missing:
        return False
    return module_name == missing or module_name.startswith(f"{missing}.")


def load_source_folder(
    folder: str | Path, registry: DataSourceRegistry
) -> LoadedSourceType:
    path = Path(folder)

    service_file = path / "service.py"
    ui_file = path / "ui.py"

    if not service_file.exists():
        raise FileNotFoundError(f"Missing service.py in '{path}'")

    try:
        module_base = _folder_to_module_base(path)
    except ValueError:
        # Fallback for datasource folders that are not importable Python packages.
        service_module = _load_py_module(service_file)
        ui_module = _load_py_module(ui_file) if ui_file.exists() else None
    else:
        service_module_name = f"{module_base}.service"
        ui_module_name = f"{module_base}.ui"
        try:
            service_module = importlib.import_module(service_module_name)
        except ModuleNotFoundError as exc:
            if not _is_package_import_failure(exc, service_module_name):
                raise
            service_module = _load_py_module(service_file)
            ui_module = _load_py_module(ui_file) if ui_file.exists() else None
        else:
            if ui_file.exists():
                try:
                    ui_module = importlib.import_module(ui_module_name)
                except ModuleNotFoundError as exc:
                    if not _is_package_import_failure(exc, ui_module_name):
                        raise
                    ui_module = _load_py_module(ui_file)
            else:
                ui_module = None

    spec = getattr(service_module, "SOURCE", None)
    if spec is None:
        raise ValueError(f"'{service_file}' must define SOURCE")

    ui_spec = _extract_ui_spec(ui_module)
    ui_actions = _extract_ui_actions(ui_module)
    registry.register(spec, ui_spec, ui_actions)
    return LoadedSourceType(
        source_type=spec.source_type, folder=str(path), ui_spec=ui_spec
    )


def autodiscover_sources(root: str | Path, registry: DataSourceRegistry) -> list[str]:
    path = Path(root)
    if not path.exists():
        return []
    loaded: list[str] = []
    for child in sorted(path.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        try:
            info = load_source_folder(child, registry)
            loaded.append(info.source_type)
        except Exception as exc:
            LOGGER.warning(
                "Skipping data source folder '%s' due to load error: %s",
                child,
                exc,
                exc_info=True,
            )
            continue
    return loaded
