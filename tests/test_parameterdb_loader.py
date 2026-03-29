from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import Services.parameterDB.parameterdb_service.loader as loader_module
from Services.parameterDB.parameterdb_service.loader import PluginRegistry
from Services.parameterDB.parameterdb_service.plugin_api import ParameterBase, PluginSpec


class FakeParam(ParameterBase):
    parameter_type = "fake"

    def scan(self, ctx) -> None:
        return None


class FakeSpec(PluginSpec):
    parameter_type = "fake"
    display_name = "Fake"
    description = "Fake plugin"

    def create(self, name: str, *, config=None, value=None, metadata=None):
        return FakeParam(name, config=config, value=value, metadata=metadata)


class OtherSpec(FakeSpec):
    parameter_type = "other"
    display_name = "Other"



def test_plugin_registry_register_get_and_list() -> None:
    registry = PluginRegistry()
    spec = FakeSpec()

    registry.register(spec, ui_spec={"create": {"required": ["name"]}}, path="/plugins/fake")

    got = registry.get("fake")
    listed = registry.list_types()
    listed_ui = registry.list_ui()
    one_ui = registry.get_ui_spec("fake")

    assert got is spec
    assert listed["fake"]["display_name"] == "Fake"
    assert listed["fake"]["has_ui"] is True
    assert listed["fake"]["plugin_path"] == "/plugins/fake"
    assert listed_ui["fake"]["parameter_type"] == "fake"
    assert one_ui["display_name"] == "Fake"



def test_plugin_registry_missing_keys_raise_value_error() -> None:
    registry = PluginRegistry()

    with pytest.raises(ValueError):
        registry.get("missing")

    with pytest.raises(ValueError):
        registry.get_ui_spec("missing")



def test_extract_ui_spec_paths() -> None:
    class WithGetter:
        @staticmethod
        def get_ui_spec():
            return {"display_name": "From getter"}

    class WithUiSpec:
        UI_SPEC = {"display_name": "From constant"}

    class WithBadGetter:
        @staticmethod
        def get_ui_spec():
            return ["bad"]

    class WithBadUiSpec:
        UI_SPEC = ["bad"]

    assert loader_module._extract_ui_spec(None) is None
    assert loader_module._extract_ui_spec(WithGetter())["display_name"] == "From getter"
    assert loader_module._extract_ui_spec(WithUiSpec())["display_name"] == "From constant"

    with pytest.raises(TypeError):
        loader_module._extract_ui_spec(WithBadGetter())

    with pytest.raises(TypeError):
        loader_module._extract_ui_spec(WithBadUiSpec())



def test_folder_to_module_base_requires_services_segment() -> None:
    assert loader_module._folder_to_module_base(Path("X/Services/parameterDB/plugins/pid")) == "Services.parameterDB.plugins.pid"

    with pytest.raises(ValueError):
        loader_module._folder_to_module_base(Path("X/no_services/pid"))



def test_load_parameter_type_folder_missing_implementation(tmp_path: Path) -> None:
    registry = PluginRegistry()

    with pytest.raises(FileNotFoundError):
        loader_module.load_parameter_type_folder(tmp_path / "missing_impl", registry)



def test_load_parameter_type_folder_registers_spec_and_optional_ui(monkeypatch, tmp_path: Path) -> None:
    plugin_dir = tmp_path / "Services" / "parameterDB" / "plugins" / "fake"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "implementation.py").write_text("# stub", encoding="utf-8")
    (plugin_dir / "ui.py").write_text("# stub", encoding="utf-8")

    registry = PluginRegistry()

    impl_module = SimpleNamespace(PLUGIN=FakeSpec())
    ui_module = SimpleNamespace(UI_SPEC={"display_name": "UI Fake"})

    def _fake_import_module(name: str):
        if name.endswith(".implementation"):
            return impl_module
        if name.endswith(".ui"):
            return ui_module
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr(loader_module.importlib, "import_module", _fake_import_module)

    loaded = loader_module.load_parameter_type_folder(plugin_dir, registry)

    assert loaded == "fake"
    assert registry.list_types()["fake"]["plugin_path"].endswith("plugins\\fake") or registry.list_types()["fake"]["plugin_path"].endswith("plugins/fake")
    assert registry.get_ui_spec("fake")["display_name"] == "UI Fake"



def test_load_parameter_type_folder_rejects_non_pluginspec(monkeypatch, tmp_path: Path) -> None:
    plugin_dir = tmp_path / "Services" / "parameterDB" / "plugins" / "bad"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "implementation.py").write_text("# stub", encoding="utf-8")

    registry = PluginRegistry()

    monkeypatch.setattr(loader_module.importlib, "import_module", lambda _name: SimpleNamespace(PLUGIN=object()))

    with pytest.raises(TypeError):
        loader_module.load_parameter_type_folder(plugin_dir, registry)



def test_autodiscover_plugins_handles_missing_root_and_filters_dirs(monkeypatch, tmp_path: Path) -> None:
    registry = PluginRegistry()

    missing = loader_module.autodiscover_plugins(tmp_path / "missing", registry)
    assert missing == []

    root = tmp_path / "root"
    valid = root / "valid"
    invalid = root / "invalid"
    valid.mkdir(parents=True)
    invalid.mkdir(parents=True)
    (valid / "implementation.py").write_text("# stub", encoding="utf-8")

    called: list[str] = []

    def _fake_load(folder, _registry):
        called.append(Path(folder).name)
        return "loaded.valid"

    monkeypatch.setattr(loader_module, "load_parameter_type_folder", _fake_load)

    loaded = loader_module.autodiscover_plugins(root, registry)

    assert loaded == ["loaded.valid"]
    assert called == ["valid"]


def test_load_py_module_success_and_missing_loader(monkeypatch, tmp_path: Path) -> None:
    good = tmp_path / "good_impl.py"
    good.write_text("VALUE = 42\n", encoding="utf-8")

    module = loader_module._load_py_module(good)
    assert module.VALUE == 42

    monkeypatch.setattr(loader_module.importlib.util, "spec_from_file_location", lambda *_a, **_k: None)

    with pytest.raises(ImportError, match="Could not load module"):
        loader_module._load_py_module(tmp_path / f"missing_{uuid4().hex}.py")
