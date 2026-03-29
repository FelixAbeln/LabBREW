from __future__ import annotations

import ast
from pathlib import Path

import pytest

from Services.parameterDB.parameterdb_core.client import SignalClient
from Services.parameterDB.parameterdb_sources.loader import DataSourceRegistry
from Services.parameterDB.sourceDefs.system_time.service import SystemTimeSourceSpec
from Services.parameterDB.serviceDS import SourceRunner, _builtin_source_root
from tests.integration_helpers import skip_if_parameterdb_unreachable, wait_until


def _source_def_folders() -> list[Path]:
    root = Path(_builtin_source_root())
    return sorted(
        child
        for child in root.iterdir()
        if child.is_dir() and not child.name.startswith("_")
    )


@pytest.mark.parametrize("folder", _source_def_folders(), ids=lambda path: path.name)
def test_builtin_source_def_folder_shape(folder: Path) -> None:
    service_file = folder / "service.py"
    ui_file = folder / "ui.py"

    assert service_file.exists()

    service_tree = ast.parse(service_file.read_text(encoding="utf-8"))
    has_source_symbol = any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SOURCE" for target in node.targets)
        for node in service_tree.body
    )
    assert has_source_symbol

    if ui_file.exists():
        ui_tree = ast.parse(ui_file.read_text(encoding="utf-8"))
        has_ui_entry = any(
            (isinstance(node, ast.FunctionDef) and node.name == "get_ui_spec")
            or (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "UI_SPEC" for target in node.targets)
            )
            for node in ui_tree.body
        )
        assert has_ui_entry


def test_system_time_source_writes_to_live_parameterdb_when_available(tmp_path: Path) -> None:
    skip_if_parameterdb_unreachable()

    registry = DataSourceRegistry()
    registry.register(SystemTimeSourceSpec())

    client = SignalClient("127.0.0.1", 8765, timeout=2.0)
    runner = SourceRunner(client, registry, config_dir=str(tmp_path / "sources"))

    source_name = "it_system_time"
    param_name = f"it.{source_name}.value"

    runner.create_source(
        source_name,
        "system_time",
        config={
            "parameter_name": param_name,
            "parameter_prefix": f"it.{source_name}",
            "update_interval_s": 0.05,
        },
    )

    try:
        def _read_written_value() -> str | None:
            with client.session() as session:
                value = session.get_value(param_name)
            text = str(value).strip() if value is not None else ""
            return text or None

        observed = wait_until(_read_written_value, timeout_s=5.0, label="system_time source update")
        assert isinstance(observed, str)
        assert observed != ""
    finally:
        runner.delete_source(source_name)
        runner.stop_all()
