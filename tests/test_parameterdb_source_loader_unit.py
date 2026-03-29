from __future__ import annotations

from pathlib import Path

import pytest

from Services.parameterDB.parameterdb_sources import loader
from tests.test_parameterdb_source_runner_and_loader import FakeSpec


def test_registry_rejects_unknown_types_and_supports_literal_ui_specs() -> None:
    registry = loader.DataSourceRegistry()
    spec = FakeSpec()
    registry.register(spec, {"display_name": "Literal", "description": "Literal UI"})

    assert registry.list_ui()["fake"] == {
        "source_type": "fake",
        "display_name": "Literal",
        "description": "Literal UI",
    }
    assert registry.get_ui_spec("fake") == {"display_name": "Literal", "description": "Literal UI"}

    with pytest.raises(KeyError, match="Unknown data source type 'missing'"):
        registry.get("missing")
    with pytest.raises(KeyError, match="Unknown data source type 'missing'"):
        registry.get_ui_spec("missing")


def test_load_py_module_success_import_error_and_cleanup(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text("VALUE = 7\n", encoding="utf-8")

    module = loader._load_py_module(good)
    assert module.VALUE == 7
    assert module.__name__ in loader.sys.modules

    bad = tmp_path / "bad.py"
    bad.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="boom"):
        loader._load_py_module(bad)

    assert not any(name.startswith("source_bad_") for name in loader.sys.modules)


def test_load_py_module_rejects_missing_loader(monkeypatch, tmp_path: Path) -> None:
    pyfile = tmp_path / "missing_loader.py"
    pyfile.write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(loader.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)

    with pytest.raises(ImportError, match="Could not load module"):
        loader._load_py_module(pyfile)


def test_extract_ui_spec_none_and_load_source_folder_missing_source(monkeypatch, tmp_path: Path) -> None:
    assert loader._extract_ui_spec(None) is None

    folder = tmp_path / "Services" / "parameterDB" / "sourceDefs" / "missing_source"
    folder.mkdir(parents=True)
    (folder / "service.py").write_text("# marker", encoding="utf-8")

    class ServiceModuleWithoutSource:
        pass

    monkeypatch.setattr(loader.importlib, "import_module", lambda name: ServiceModuleWithoutSource)

    with pytest.raises(ValueError, match="must define SOURCE"):
        loader.load_source_folder(folder, loader.DataSourceRegistry())