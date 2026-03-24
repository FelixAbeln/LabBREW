from __future__ import annotations

import argparse
import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from ..parameterdb_core.client import SignalClient
from ..parameterdb_core.plugin_ui import deep_copy_payload, get_by_path, set_by_path
import time


class PluginTypeDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, plugin_map: dict[str, dict[str, Any]], *, title: str, prompt: str, kind_key: str) -> None:
        super().__init__(master)
        self.title(title)
        self.geometry("560x420")
        self.transient(master)
        self.grab_set()
        self.result: str | None = None
        self.plugin_map = plugin_map
        self.kind_key = kind_key

        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root, text=prompt).pack(anchor="w")

        self.filter_var = tk.StringVar()
        ent = ttk.Entry(root, textvariable=self.filter_var)
        ent.pack(fill=tk.X, pady=(6, 8))
        ent.bind("<KeyRelease>", lambda e: self.refresh())

        body = ttk.Frame(root)
        body.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(body)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-1>", lambda e: self.accept())
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.update_details())
        sb = ttk.Scrollbar(body, orient="vertical", command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=sb.set)

        self.details = tk.Text(root, height=8, wrap="word")
        self.details.pack(fill=tk.BOTH, pady=(8, 8))
        self.details.configure(state="disabled")

        bar = ttk.Frame(root)
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Use", command=self.accept).pack(side=tk.RIGHT, padx=6)

        self._visible: list[str] = []
        self.refresh()
        ent.focus_set()

    def refresh(self) -> None:
        needle = self.filter_var.get().strip().lower()
        self.listbox.delete(0, tk.END)
        self._visible = []
        for kind in sorted(self.plugin_map):
            spec = self.plugin_map[kind]
            hay = f"{kind} {spec.get('display_name', '')} {spec.get('description', '')}".lower()
            if needle and needle not in hay:
                continue
            label = f"{kind} — {spec.get('display_name', kind)}"
            self.listbox.insert(tk.END, label)
            self._visible.append(kind)
        if self._visible:
            self.listbox.selection_set(0)
            self.update_details()

    def update_details(self) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        idxs = self.listbox.curselection()
        if idxs:
            kind = self._visible[idxs[0]]
            spec = self.plugin_map[kind]
            info = {
                self.kind_key: kind,
                "display_name": spec.get("display_name", kind),
                "description": spec.get("description", ""),
                "required": spec.get("create", {}).get("required", []),
            }
            self.details.insert("1.0", json.dumps(info, indent=2))
        self.details.configure(state="disabled")

    def accept(self) -> None:
        idxs = self.listbox.curselection()
        if not idxs:
            return
        self.result = self._visible[idxs[0]]
        self.destroy()


class SchemaEditor(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        client: SignalClient,
        schema_ui: dict[str, Any],
        mode: str,
        *,
        entity_kind: str,
        type_key: str,
        record: dict[str, Any] | None = None,
        save_callback: Callable[[dict[str, Any], str], None],
        list_parameter_refs: bool = True,
    ) -> None:
        super().__init__(master)
        self.client = client
        self.schema_ui = schema_ui
        self.mode = mode
        self.entity_kind = entity_kind
        self.type_key = type_key
        self.record = deep_copy_payload(record or {})
        self.field_vars: dict[str, tuple[tk.Variable | tk.Text, dict[str, Any]]] = {}
        self.result = False
        self.save_callback = save_callback
        self.list_parameter_refs = list_parameter_refs
        try:
            self.parameter_names = self.client.list_parameters() if list_parameter_refs else []
        except Exception:
            self.parameter_names = []

        title = f"{mode.title()} {schema_ui.get('display_name', schema_ui.get(type_key, entity_kind.title()))}"
        self.title(title)
        self.geometry("860x760")
        self.minsize(700, 520)
        self.transient(master)
        self.grab_set()

        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(header, text=schema_ui.get("display_name", schema_ui.get(type_key, entity_kind.title())), font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        desc = schema_ui.get("description", "")
        if desc:
            ttk.Label(header, text=desc, wraplength=780, justify="left").pack(anchor="w", pady=(4, 0))

        body = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        body.grid(row=1, column=0, sticky="nsew")

        form_host = ttk.Frame(body)
        body.add(form_host, weight=4)
        preview_host = ttk.LabelFrame(body, text="Payload Preview", padding=8)
        body.add(preview_host, weight=2)

        self.notebook = ttk.Notebook(form_host)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.preview = tk.Text(preview_host, wrap="word", height=20)
        self.preview.pack(fill=tk.BOTH, expand=True)
        self.preview.configure(state="disabled")

        bar = ttk.Frame(root)
        bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.error_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.error_var, foreground="#b00020").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Save", command=self.on_save).pack(side=tk.RIGHT, padx=6)

        self._build_form()
        self.refresh_preview()

    def _base_data(self) -> dict[str, Any]:
        if self.mode == "create":
            defaults = deep_copy_payload(self.schema_ui.get("create", {}).get("defaults", {}))
            return {
                "name": defaults.get("name", ""),
                self.type_key: self.schema_ui[self.type_key],
                "config": defaults.get("config", {}),
                "metadata": defaults.get("metadata", {}),
                "value": defaults.get("value"),
                "state": defaults.get("state", {}),
            }
        data = deep_copy_payload(self.record)
        edit_defaults = deep_copy_payload(self.schema_ui.get("edit", {}).get("defaults", {}))
        for key, value in edit_defaults.items():
            if key == "config" and isinstance(value, dict):
                merged = deep_copy_payload(value)
                merged.update(data.get("config") or {})
                data["config"] = merged
            elif key not in data:
                data[key] = value
        data.setdefault("name", "")
        data.setdefault(self.type_key, self.record.get(self.type_key, self.schema_ui[self.type_key]))
        data.setdefault("config", {})
        data.setdefault("metadata", {})
        data.setdefault("value", None)
        data.setdefault("state", {})
        return data

    def _iter_sections(self) -> list[dict[str, Any]]:
        if self.mode == "create":
            sections = deep_copy_payload(self.schema_ui.get("create", {}).get("sections", []))
            if not sections:
                sections = deep_copy_payload(self.schema_ui.get("edit", {}).get("sections", []))
                for section in sections:
                    section["fields"] = [f for f in section.get("fields", []) if not str(f.get("key", "")).startswith("state.")]
                sections = [s for s in sections if s.get("fields")]
        else:
            sections = deep_copy_payload(self.schema_ui.get("edit", {}).get("sections", []))
        if not sections:
            sections = [
                {"title": "General", "fields": [{"key": "name", "label": "Name", "type": "string", "required": True}]},
                {"title": "Config", "fields": [{"key": "config", "label": "Config", "type": "json"}]},
            ]
        return sections

    def _build_form(self) -> None:
        data = self._base_data()
        sections = self._iter_sections()
        if self.mode == "create" and not any(field.get("key") == "name" for section in sections for field in section.get("fields", [])):
            sections = [{"title": "Identity", "fields": [{"key": "name", "label": "Name", "type": "string", "required": True}]}] + sections

        for section in sections:
            frame = ttk.Frame(self.notebook, padding=10)
            frame.columnconfigure(1, weight=1)
            self.notebook.add(frame, text=section.get("title", "Section"))
            row = 0
            for field in section.get("fields", []):
                key = field["key"]
                label = field.get("label", key)
                if field.get("required"):
                    label += " *"
                ttk.Label(frame, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=4)
                holder_frame = ttk.Frame(frame)
                holder_frame.grid(row=row, column=1, sticky="nsew", pady=4)
                holder_frame.columnconfigure(0, weight=1)
                value = get_by_path(data, key)
                widget, holder = self._make_input(holder_frame, field, value)
                widget.grid(row=0, column=0, sticky="ew")
                self.field_vars[key] = (holder, field)
                help_text = field.get("help")
                if help_text:
                    ttk.Label(frame, text=help_text, foreground="#555", wraplength=520, justify="left").grid(row=row + 1, column=1, sticky="w", pady=(0, 4))
                    row += 1
                row += 1

    def _bind_change(self, widget: tk.Widget, holder: tk.Variable | tk.Text) -> None:
        if isinstance(holder, tk.Variable):
            holder.trace_add("write", lambda *_: self.refresh_preview())
        elif isinstance(widget, tk.Text):
            widget.bind("<<Modified>>", lambda e: self._handle_modified(widget))

    def _handle_modified(self, widget: tk.Widget) -> None:
        if isinstance(widget, tk.Text) and widget.edit_modified():
            widget.edit_modified(False)
            self.refresh_preview()

    def _make_input(self, parent: tk.Misc, field: dict[str, Any], value: Any):
        field_type = field.get("type", "string")
        readonly = bool(field.get("readonly")) or field_type == "readonly"

        if field_type in {"text", "code", "json"}:
            wrap = "none" if field_type == "code" else "word"
            text = tk.Text(parent, height=8 if field_type in {"text", "code"} else 6, wrap=wrap)
            initial = ""
            if value is not None:
                if field_type == "json" and not isinstance(value, str):
                    initial = json.dumps(value, indent=2, sort_keys=True)
                else:
                    initial = str(value)
            text.insert("1.0", initial)
            if readonly:
                text.configure(state="disabled")
            self._bind_change(text, text)
            return text, text

        if field_type == "bool":
            var = tk.BooleanVar(value=bool(value))
            widget = ttk.Checkbutton(parent, variable=var)
            if readonly:
                widget.state(["disabled"])
            self._bind_change(widget, var)
            return widget, var

        if field_type == "enum":
            choices = field.get("choices") or field.get("options") or []
            var = tk.StringVar(value="" if value is None else str(value))
            combo = ttk.Combobox(parent, textvariable=var, values=list(choices), state="readonly" if not readonly else "disabled")
            self._bind_change(combo, var)
            return combo, var

        if field_type == "parameter_ref":
            options = field.get("options") or self.parameter_names
            if value not in (None, "") and value not in options:
                options = list(options) + [value]
            outer = ttk.Frame(parent)
            outer.columnconfigure(0, weight=1)
            var = tk.StringVar(value="" if value is None else str(value))
            combo = ttk.Combobox(outer, textvariable=var, values=list(options), state="readonly" if not readonly else "disabled")
            combo.grid(row=0, column=0, sticky="ew")
            if not readonly:
                ttk.Button(outer, text="…", width=3, command=lambda v=var: self._choose_parameter(v)).grid(row=0, column=1, padx=(6, 0))
            self._bind_change(combo, var)
            return outer, var

        if field_type == "parameter_ref_list":
            outer = ttk.Frame(parent)
            outer.columnconfigure(0, weight=1)
            var = tk.StringVar(value=", ".join(value or []))
            entry = ttk.Entry(outer, textvariable=var)
            entry.grid(row=0, column=0, sticky="ew")
            if readonly:
                entry.state(["disabled"])
            else:
                ttk.Button(outer, text="Pick…", command=lambda v=var: self._choose_parameter_list(v)).grid(row=0, column=1, padx=(6, 0))
            self._bind_change(entry, var)
            return outer, var

        shown = "" if value is None else (json.dumps(value) if isinstance(value, (dict, list)) else str(value))
        var = tk.StringVar(value=shown)
        widget = ttk.Entry(parent, textvariable=var)
        if readonly:
            widget.state(["readonly"])
        self._bind_change(widget, var)
        return widget, var

    def _choose_parameter(self, var: tk.StringVar) -> None:
        dlg = PluginTypeDialog(self, {name: {"display_name": name, "description": ""} for name in self.parameter_names}, title="Choose Parameter", prompt="Choose a parameter:", kind_key="name")
        self.wait_window(dlg)
        if dlg.result:
            var.set(dlg.result)

    def _choose_parameter_list(self, var: tk.StringVar) -> None:
        current = {x.strip() for x in var.get().split(",") if x.strip()}
        win = tk.Toplevel(self)
        win.title("Choose Parameters")
        win.geometry("320x420")
        win.transient(self)
        win.grab_set()
        vals: dict[str, tk.BooleanVar] = {}
        body = ttk.Frame(win, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        for name in self.parameter_names:
            bv = tk.BooleanVar(value=name in current)
            vals[name] = bv
            ttk.Checkbutton(body, text=name, variable=bv).pack(anchor="w")
        def apply() -> None:
            picked = [name for name, bv in vals.items() if bv.get()]
            var.set(", ".join(picked))
            win.destroy()
        bar = ttk.Frame(body)
        bar.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(bar, text="Cancel", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Apply", command=apply).pack(side=tk.RIGHT, padx=6)
        self.wait_window(win)

    def _read_field_value(self, spec: dict[str, Any], holder: tk.Variable | tk.Text) -> Any:
        field_type = spec.get("type", "string")
        raw = holder.get("1.0", "end").strip() if isinstance(holder, tk.Text) else holder.get()
        if field_type == "readonly":
            return raw
        if field_type in {"text", "code", "string", "parameter_ref", "enum"}:
            return raw
        if field_type == "json":
            return None if raw == "" else json.loads(raw)
        if field_type == "bool":
            return bool(raw)
        if field_type == "int":
            return None if raw == "" else int(raw)
        if field_type == "float":
            return None if raw == "" else float(raw)
        if field_type == "parameter_ref_list":
            return [item.strip() for item in raw.split(",") if item.strip()]
        return raw

    def _collect_data(self) -> dict[str, Any]:
        data = self._base_data()
        for key, (holder, spec) in self.field_vars.items():
            set_by_path(data, key, self._read_field_value(spec, holder))
        return data

    def _validate(self, data: dict[str, Any]) -> None:
        required = set(self.schema_ui.get("create", {}).get("required", []))
        for _, spec in self.field_vars.values():
            if spec.get("required"):
                required.add(spec["key"])
        missing = []
        for path in sorted(required):
            value = get_by_path(data, path)
            if value in (None, "", []):
                missing.append(path)
        if missing:
            raise ValueError("Missing required fields: " + ", ".join(missing))

    def refresh_preview(self) -> None:
        try:
            data = self._collect_data()
            text = json.dumps(data, indent=2, sort_keys=True)
            self.error_var.set("")
        except Exception as exc:
            text = f"Invalid form data:\n{exc}"
            self.error_var.set(str(exc))
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def on_save(self) -> None:
        try:
            data = self._collect_data()
            self._validate(data)
            self.save_callback(data, self.mode)
            self.result = True
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)


class SourceManager(tk.Toplevel):
    def __init__(self, master: tk.Misc, source_client: SignalClient, parameter_client: SignalClient) -> None:
        super().__init__(master)
        self.source_client = source_client
        self.parameter_client = parameter_client
        self.title("Data Sources")
        self.geometry("1100x640")
        self.transient(master)
        self.grab_set()
        self.rows: dict[str, dict[str, Any]] = {}
        self.ui_cache: dict[str, dict[str, Any]] = {}
        self.ui_summaries: dict[str, dict[str, Any]] = {}

        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Create", command=self.create_source).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Edit", command=self.edit_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Delete", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Refresh", command=self.reload).pack(side=tk.LEFT, padx=10)

        cols = ("name", "source_type", "running", "config")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=14)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        widths = {"name": 180, "source_type": 140, "running": 80, "config": 620}
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=widths[col], anchor="w")

        detail = ttk.LabelFrame(self, text="Selected Source", padding=8)
        detail.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.detail_text = tk.Text(detail, height=12, wrap="word")
        self.detail_text.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_details())

        self.reload()

    def reload(self) -> None:
        self.ui_summaries = self.source_client.list_source_types_ui()
        self.rows = self.source_client.list_sources()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for name, row in sorted(self.rows.items()):
            self.tree.insert("", "end", iid=name, values=(name, row.get("source_type", ""), str(bool(row.get("running"))), json.dumps(row.get("config", {}), sort_keys=True)))
        self.update_details()

    def selected_name(self) -> str | None:
        selected = self.tree.selection()
        return selected[0] if selected else None

    def selected_record(self) -> dict[str, Any] | None:
        name = self.selected_name()
        return self.rows.get(name) if name else None

    def get_source_type_ui(self, source_type: str, *, name: str | None = None, mode: str | None = None) -> dict[str, Any]:
        cache_key = f"{source_type}::{name or ''}::{mode or ''}"
        if cache_key not in self.ui_cache:
            self.ui_cache[cache_key] = self.source_client.get_source_type_ui(source_type, name=name, mode=mode)
        return self.ui_cache[cache_key]

    def _save_source(self, data: dict[str, Any], mode: str) -> None:
        if mode == "create":
            self.source_client.create_source(data["name"], data["source_type"], config=data.get("config", {}))
        else:
            self.source_client.update_source(data["name"], config=data.get("config", {}))
        self.reload()

    def create_source(self) -> None:
        dlg = PluginTypeDialog(self, self.ui_summaries, title="Choose Data Source Type", prompt="Choose a data source type to create:", kind_key="source_type")
        self.wait_window(dlg)
        if not dlg.result:
            return
        ui = self.get_source_type_ui(dlg.result, mode="create")
        editor = SchemaEditor(self, self.parameter_client, ui, "create", entity_kind="source", type_key="source_type", save_callback=self._save_source, list_parameter_refs=True)
        self.wait_window(editor)

    def edit_selected(self) -> None:
        record = self.selected_record()
        if not record:
            return
        ui = self.get_source_type_ui(record["source_type"], name=record.get("name"), mode="edit")
        editor = SchemaEditor(self, self.parameter_client, ui, "edit", entity_kind="source", type_key="source_type", record=record, save_callback=self._save_source, list_parameter_refs=True)
        self.wait_window(editor)

    def delete_selected(self) -> None:
        name = self.selected_name()
        if not name:
            return
        if messagebox.askyesno("Delete source", f"Delete source '{name}'?", parent=self):
            self.source_client.delete_source(name)
            self.reload()

    def update_details(self) -> None:
        self.detail_text.delete("1.0", "end")
        record = self.selected_record()
        if record:
            self.detail_text.insert("1.0", json.dumps(record, indent=2, sort_keys=True))


class RelationsDialog(tk.Toplevel):
    """Focused view of parameter dependencies, dependents, write targets, and warnings."""
    def __init__(self, master: tk.Misc, name: str, graph: dict[str, Any], app_ref: MonitorApp | None = None) -> None:
        super().__init__(master)
        self.title(f"Relations: {name}")
        self.geometry("640x500")
        self.transient(master)
        self.grab_set()
        self.name = name
        self.graph = graph
        self.app_ref = app_ref

        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root, text=f"Parameter: {name}", font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 8))

        # Dependencies section
        deps_frame = ttk.LabelFrame(root, text="Dependencies (↑ requires)", padding=8)
        deps_frame.pack(fill=tk.BOTH, expand=False, pady=4)
        self.deps_listbox = tk.Listbox(deps_frame, height=4, selectmode=tk.SINGLE)
        self.deps_listbox.pack(fill=tk.BOTH, expand=True)
        self.deps_listbox.bind("<Double-1>", self._navigate_deps)
        for dep in (self.graph.get("dependencies") or {}).get(name, []):
            self.deps_listbox.insert(tk.END, dep)

        # Dependents section
        deps = self.graph.get("dependencies") or {}
        dependents = sorted([param for param, values in deps.items() if name in values])
        dependents_frame = ttk.LabelFrame(root, text="Dependents (↓ depends on this)", padding=8)
        dependents_frame.pack(fill=tk.BOTH, expand=False, pady=4)
        self.dependents_listbox = tk.Listbox(dependents_frame, height=4, selectmode=tk.SINGLE)
        self.dependents_listbox.pack(fill=tk.BOTH, expand=True)
        self.dependents_listbox.bind("<Double-1>", self._navigate_dependents)
        for dep in dependents:
            self.dependents_listbox.insert(tk.END, dep)

        # Write targets section
        write_targets = (self.graph.get("write_targets") or {}).get(name, [])
        writes_frame = ttk.LabelFrame(root, text="Write Targets (→ writes to)", padding=8)
        writes_frame.pack(fill=tk.BOTH, expand=False, pady=4)
        self.writes_listbox = tk.Listbox(writes_frame, height=4, selectmode=tk.SINGLE)
        self.writes_listbox.pack(fill=tk.BOTH, expand=True)
        self.writes_listbox.bind("<Double-1>", self._navigate_writes)
        for target in write_targets:
            self.writes_listbox.insert(tk.END, target)

        # Warnings section
        warnings = self.graph.get("warnings") or []
        param_warnings = [item for item in warnings if name in str(item)]
        warnings_frame = ttk.LabelFrame(root, text="Graph Warnings", padding=8)
        warnings_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        self.warnings_text = tk.Text(warnings_frame, height=6, wrap="word", state="disabled")
        self.warnings_text.pack(fill=tk.BOTH, expand=True)
        if param_warnings:
            self.warnings_text.configure(state="normal")
            for warn in param_warnings:
                self.warnings_text.insert(tk.END, f"• {warn}\n")
            self.warnings_text.configure(state="disabled")
        else:
            self.warnings_text.configure(state="normal")
            self.warnings_text.insert(tk.END, "(no warnings)")
            self.warnings_text.configure(state="disabled")

        # Button bar
        bar = ttk.Frame(root)
        bar.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(bar, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _navigate_deps(self, event: Any = None) -> None:
        sel = self.deps_listbox.curselection()
        if sel and self.app_ref:
            param_name = self.deps_listbox.get(sel[0])
            self.app_ref.select_parameter(param_name)

    def _navigate_dependents(self, event: Any = None) -> None:
        sel = self.dependents_listbox.curselection()
        if sel and self.app_ref:
            param_name = self.dependents_listbox.get(sel[0])
            self.app_ref.select_parameter(param_name)

    def _navigate_writes(self, event: Any = None) -> None:
        sel = self.writes_listbox.curselection()
        if sel and self.app_ref:
            param_name = self.writes_listbox.get(sel[0])
            self.app_ref.select_parameter(param_name)


class MonitorApp:
    def __init__(self, root: tk.Tk, client: SignalClient, source_client: SignalClient | None = None) -> None:
        self.root = root
        self.client = client
        self.source_client = source_client
        self.events: queue.Queue = queue.Queue()
        self.rows: dict[str, dict[str, Any]] = {}
        self.stop_flag = threading.Event()
        self.plugin_ui_cache: dict[str, dict[str, Any]] = {}
        self.graph: dict[str, Any] = {}

        root.title("ParameterDB Monitor")
        root.geometry("1650x850")

        toolbar = ttk.Frame(root, padding=8)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Create", command=self.create_parameter).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Edit", command=self.edit_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Delete", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Relations", command=self.show_relations).pack(side=tk.LEFT, padx=(12, 2))
        if self.source_client is not None:
            ttk.Button(toolbar, text="Sources", command=self.manage_sources).pack(side=tk.LEFT, padx=(12, 2))
        ttk.Button(toolbar, text="Refresh Graph", command=self.refresh_graph).pack(side=tk.LEFT, padx=10)
        ttk.Button(toolbar, text="Snapshot", command=self.show_snapshot).pack(side=tk.LEFT, padx=2)
        ttk.Label(toolbar, text="Filter").pack(side=tk.LEFT, padx=(20, 4))
        self.filter_var = tk.StringVar()
        filter_entry = ttk.Entry(toolbar, textvariable=self.filter_var, width=30)
        filter_entry.pack(side=tk.LEFT)
        filter_entry.bind("<KeyRelease>", lambda e: self.refresh_tree())

        self.status_var = tk.StringVar(value="Connecting...")
        ttk.Label(toolbar, textvariable=self.status_var).pack(side=tk.RIGHT)

        cols = ("name", "parameter_type", "scan", "value", "deps", "dependents", "writes", "config", "state", "metadata")
        self.tree = ttk.Treeview(root, columns=cols, show="headings", height=20)
        widths = {"name": 180, "parameter_type": 100, "scan": 55, "value": 140, "deps": 170, "dependents": 170, "writes": 170, "config": 260, "state": 260, "metadata": 180}
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_details())
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        detail = ttk.LabelFrame(root, text="Selected", padding=8)
        detail.pack(fill=tk.BOTH, padx=8, pady=(0, 8))
        self.detail_text = tk.Text(detail, height=14, wrap="word")
        self.detail_text.pack(fill=tk.BOTH, expand=True)

        self.plugin_ui_summaries: dict[str, dict[str, Any]] = {}
        self.load_initial()
        self.start_subscription_thread()
        self.root.after(150, self.process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_initial(self) -> None:
        self.plugin_ui_summaries = self.client.list_parameter_type_ui()
        self.plugin_ui_cache = {}
        self.rows = {}
        for name, desc in self.client.describe().items():
            record = dict(desc)
            record["name"] = name
            self.rows[name] = record
        self.refresh_graph()
        self.refresh_tree()

    def refresh_graph(self) -> None:
        try:
            self.graph = self.client.graph_info()
        except Exception as exc:
            messagebox.showerror("Graph error", str(exc), parent=self.root)
            self.graph = {"dependencies": {}, "warnings": [], "scan_order": []}
        self.refresh_tree()
        self.update_status()
        self.update_details()

    def deps_for(self, name: str) -> list[str]:
        return list((self.graph.get("dependencies") or {}).get(name, []))

    def dependents_for(self, name: str) -> list[str]:
        deps = self.graph.get("dependencies") or {}
        return sorted([param for param, values in deps.items() if name in values])

    def write_targets_for(self, name: str) -> list[str]:
        return list((self.graph.get("write_targets") or {}).get(name, []))

    def scan_index_for(self, name: str) -> int | None:
        scan_order = self.graph.get("scan_order") or []
        try:
            return int(scan_order.index(name))
        except ValueError:
            return None

    def graph_warnings_for(self, name: str) -> list[str]:
        warnings = self.graph.get("warnings") or []
        needle = f"{name}"
        return [item for item in warnings if needle in str(item)]

    def row_values(self, name: str, desc: dict[str, Any]) -> tuple[Any, ...]:
        scan_index = self.scan_index_for(name)
        return (
            name,
            desc.get("parameter_type", ""),
            "" if scan_index is None else scan_index,
            repr(desc.get("value")),
            ", ".join(self.deps_for(name)),
            ", ".join(self.dependents_for(name)),
            ", ".join(self.write_targets_for(name)),
            json.dumps(desc.get("config", {}), sort_keys=True),
            json.dumps(desc.get("state", {}), sort_keys=True),
            json.dumps(desc.get("metadata", {}), sort_keys=True),
        )

    def refresh_tree(self) -> None:
        needle = self.filter_var.get().strip().lower()
        existing = set(self.tree.get_children())
        wanted = set()
        for name, desc in sorted(self.rows.items()):
            hay = " ".join([
                name,
                str(desc.get("parameter_type", "")),
                json.dumps(desc.get("config", {}), sort_keys=True),
                json.dumps(desc.get("metadata", {}), sort_keys=True),
                json.dumps(desc.get("state", {}), sort_keys=True),
                " ".join(self.deps_for(name)),
                " ".join(self.dependents_for(name)),
                " ".join(self.write_targets_for(name)),
                " ".join(self.graph_warnings_for(name)),
            ]).lower()
            if needle and needle not in hay:
                continue
            wanted.add(name)
            values = self.row_values(name, desc)
            if self.tree.exists(name):
                self.tree.item(name, values=values)
            else:
                self.tree.insert("", "end", iid=name, values=values)
        for iid in existing - wanted:
            self.tree.delete(iid)
        self.update_status()

    def selected_name(self) -> str | None:
        selected = self.tree.selection()
        return selected[0] if selected else None

    def selected_record(self) -> dict[str, Any] | None:
        name = self.selected_name()
        return self.rows.get(name) if name else None

    def get_parameter_type_ui(self, parameter_type: str) -> dict[str, Any]:
        if parameter_type not in self.plugin_ui_cache:
            self.plugin_ui_cache[parameter_type] = self.client.get_parameter_type_ui(parameter_type)
        return self.plugin_ui_cache[parameter_type]

    def _save_parameter(self, data: dict[str, Any], mode: str) -> None:
        if mode == "create":
            self.client.create_parameter(data["name"], data["parameter_type"], value=data.get("value"), config=data.get("config", {}), metadata=data.get("metadata", {}))
        else:
            name = data["name"]
            self.client.set_value(name, data.get("value"))
            self.client.update_config(name, **data.get("config", {}))
            self.client.update_metadata(name, **data.get("metadata", {}))

    def create_parameter(self) -> None:
        try:
            self.plugin_ui_summaries = self.client.list_parameter_type_ui()
        except Exception:
            pass
        plugin_map = self.plugin_ui_summaries
        if not plugin_map:
            messagebox.showwarning("No plugins", "No plugin UIs are available.", parent=self.root)
            return
        dlg = PluginTypeDialog(self.root, plugin_map, title="Choose Parameter Type", prompt="Choose a parameter type to create:", kind_key="parameter_type")
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        editor = SchemaEditor(self.root, self.client, self.get_parameter_type_ui(dlg.result), "create", entity_kind="parameter", type_key="parameter_type", save_callback=self._save_parameter)
        self.root.wait_window(editor)

    def edit_selected(self) -> None:
        record = self.selected_record()
        if not record:
            return
        ui = self.get_parameter_type_ui(record["parameter_type"])
        dlg = SchemaEditor(self.root, self.client, ui, "edit", entity_kind="parameter", type_key="parameter_type", record=record, save_callback=self._save_parameter)
        self.root.wait_window(dlg)

    def manage_sources(self) -> None:
        if self.source_client is None:
            return
        win = SourceManager(self.root, self.source_client, self.client)
        self.root.wait_window(win)

    def delete_selected(self) -> None:
        name = self.selected_name()
        if not name:
            return
        if messagebox.askyesno("Delete parameter", f"Delete '{name}'?", parent=self.root):
            try:
                self.client.delete_parameter(name)
            except Exception as exc:
                messagebox.showerror("Delete failed", str(exc), parent=self.root)

    def show_snapshot(self) -> None:
        try:
            data = self.client.snapshot()
        except Exception as exc:
            messagebox.showerror("Snapshot failed", str(exc), parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.title("Snapshot")
        txt = tk.Text(win, wrap="word")
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert("1.0", json.dumps(data, indent=2, sort_keys=True))

    def show_relations(self) -> None:
        """Show relations (dependencies, dependents, writes, warnings) for selected parameter."""
        name = self.selected_name()
        if not name:
            messagebox.showwarning("No selection", "Please select a parameter first.", parent=self.root)
            return
        dlg = RelationsDialog(self.root, name, self.graph, app_ref=self)
        self.root.wait_window(dlg)

    def select_parameter(self, name: str) -> None:
        """Select and scroll to parameter in the tree view."""
        if name and self.tree.exists(name):
            self.tree.selection_set(name)
            self.tree.see(name)
            self.update_details()

    def update_details(self) -> None:
        self.detail_text.delete("1.0", "end")
        record = self.selected_record()
        if not record:
            return
        name = record["name"]
        payload = {
            "name": name,
            "parameter_type": record.get("parameter_type"),
            "scan_index": self.scan_index_for(name),
            "value": record.get("value"),
            "config": record.get("config", {}),
            "state": record.get("state", {}),
            "metadata": record.get("metadata", {}),
            "dependencies": self.deps_for(name),
            "dependents": self.dependents_for(name),
            "write_targets": self.write_targets_for(name),
            "graph_warnings": self.graph_warnings_for(name),
        }
        self.detail_text.insert("1.0", json.dumps(payload, indent=2, sort_keys=True))

    def update_status(self) -> None:
        try:
            stats = self.client.stats()
            last_scan = float(stats.get('last_scan_duration_s') or 0.0)
            avg_scan = float(stats.get('avg_scan_duration_s') or last_scan)
            estimated_hz = stats.get('estimated_cycle_rate_hz')
            utilization = stats.get('estimated_utilization')
            overrun_count = int(stats.get('overrun_count') or 0)
            mode = str(stats.get('mode') or 'fixed')
            hz_text = f"{float(estimated_hz):.1f}Hz" if estimated_hz else "-"
            util_text = f"{float(utilization) * 100:.0f}%" if utilization is not None else "-"
            self.status_var.set(
                f"Connected | params={len(self.rows)} | mode={mode} | rate={hz_text} | last={last_scan:.4f}s | avg={avg_scan:.4f}s | util={util_text} | overruns={overrun_count} | warnings={len(self.graph.get('warnings', []))}"
            )
        except Exception as exc:
            self.status_var.set(f"Disconnected: {exc}")

    def start_subscription_thread(self) -> None:
        def worker() -> None:
            while not self.stop_flag.is_set():
                try:
                    with self.client.subscribe(send_initial=True) as sub:
                        self.events.put({"event": "monitor_status", "status": "subscribed"})
                        for event in sub:
                            if self.stop_flag.is_set():
                                break
                            self.events.put(event)
                    if not self.stop_flag.is_set():
                        self.events.put({"event": "monitor_error", "error": "Subscription ended; reconnecting..."})
                except Exception as exc:
                    if self.stop_flag.is_set():
                        break
                    self.events.put({"event": "monitor_error", "error": f"{exc} | reconnecting..."})
                time.sleep(1.0)
        threading.Thread(target=worker, daemon=True).start()

    def process_events(self) -> None:
        graph_dirty = False
        try:
            while True:
                event = self.events.get_nowait()
                et = event.get("event")
                name = event.get("name")
                if et in {"parameter_added", "parameter_snapshot"} and name:
                    record = {"name": name, "parameter_type": event.get("parameter_type"), "value": event.get("value"), "config": event.get("config", {}), "state": event.get("state", {}), "metadata": event.get("metadata", {})}
                    self.rows[name] = record
                    graph_dirty = True
                elif et == "parameter_removed" and name:
                    self.rows.pop(name, None)
                    graph_dirty = True
                elif et == "value_changed" and name in self.rows:
                    self.rows[name]["value"] = event.get("value")
                elif et == "config_changed" and name in self.rows:
                    self.rows[name]["config"] = event.get("config", {})
                    graph_dirty = True
                elif et == "metadata_changed" and name in self.rows:
                    self.rows[name]["metadata"] = event.get("metadata", {})
                elif et == "state_changed" and name in self.rows:
                    self.rows[name]["state"] = event.get("state", {})
                elif et == "monitor_error":
                    self.status_var.set(f"Disconnected: {event.get('error')}")
                elif et == "monitor_status":
                    self.status_var.set("Connected | resynced subscription")
        except queue.Empty:
            pass

        if graph_dirty:
            try:
                self.graph = self.client.graph_info()
            except Exception:
                pass
        self.refresh_tree()
        self.update_details()
        self.root.after(150, self.process_events)

    def on_close(self) -> None:
        self.stop_flag.set()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="ParameterDB monitor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--source-host", default="127.0.0.1")
    parser.add_argument("--source-port", type=int, default=8766)
    parser.add_argument("--no-source-admin", action="store_true")
    args = parser.parse_args()

    root = tk.Tk()
    client = SignalClient(args.host, args.port, timeout=5.0).session()
    client.connect()
    source_client = None
    if not args.no_source_admin:
        try:
            source_client = SignalClient(args.source_host, args.source_port, timeout=5.0).session()
            source_client.connect()
            source_client.ping()
        except Exception:
            source_client = None
    try:
        MonitorApp(root, client, source_client=source_client)
        root.mainloop()
    finally:
        client.close()
        if source_client is not None:
            source_client.close()


if __name__ == "__main__":
    main()
