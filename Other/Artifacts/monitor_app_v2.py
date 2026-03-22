from __future__ import annotations

import argparse
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from realtimedb_service.client import SignalClient


class MonitorApp:
    def __init__(self, root: tk.Tk, client: SignalClient) -> None:
        self.root = root
        self.client = client
        self.events: queue.Queue = queue.Queue()
        self.rows: dict[str, dict] = {}
        self.graph: dict[str, dict | list | str] = {}
        self.stop_flag = threading.Event()
        self.filter_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Connecting...")
        self.selected_name: str | None = None
        self.sort_reverse = False

        root.title("RealtimeDB Verify Monitor")
        root.geometry("1650x850")

        self._build_ui()
        self._bind_events()
        self.load_initial()
        self.start_subscription_thread()
        self.root.after(100, self.process_events)
        self.root.after(2000, self.refresh_status)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Filter:").pack(side=tk.LEFT)
        filter_entry = ttk.Entry(top, textvariable=self.filter_var, width=40)
        filter_entry.pack(side=tk.LEFT, padx=(6, 10))
        filter_entry.focus_set()

        ttk.Button(top, text="Refresh", command=self.reload_all).pack(side=tk.LEFT)
        ttk.Button(top, text="Graph", command=self.show_graph_summary).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="Snapshot JSON", command=self.show_snapshot_json).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(top, textvariable=self.status_var).pack(side=tk.RIGHT)

        center = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        center.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(center)
        right = ttk.Frame(center, padding=8)
        center.add(left, weight=4)
        center.add(right, weight=2)

        cols = (
            "name",
            "plugin_type",
            "scan_mode",
            "value",
            "deps",
            "dependents",
            "config",
            "state",
            "metadata",
        )
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        widths = {
            "name": 220,
            "plugin_type": 100,
            "scan_mode": 90,
            "value": 150,
            "deps": 180,
            "dependents": 180,
            "config": 260,
            "state": 260,
            "metadata": 200,
        }
        for col in cols:
            self.tree.heading(col, text=col.title(), command=lambda c=col: self.sort_by(c))
            self.tree.column(col, width=widths[col], anchor="w")

        yscroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        xscroll = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        ttk.Label(right, text="Selected Parameter", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.detail_text = tk.Text(right, wrap="word", height=20)
        self.detail_text.pack(fill=tk.BOTH, expand=True)

        ttk.Label(right, text="Recent Events", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
        self.event_list = tk.Listbox(right, height=12)
        self.event_list.pack(fill=tk.BOTH, expand=False)

    def _bind_events(self) -> None:
        self.filter_var.trace_add("write", lambda *_: self.render_tree())
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

    def load_initial(self) -> None:
        self.rows = dict(self.client.describe())
        self.graph = self.client.graph_info()
        self.render_tree()
        self.status_var.set(
            f"Connected | parameters={len(self.rows)} | active={len(self.graph.get('active_parameters', []))}"
        )

    def reload_all(self) -> None:
        try:
            self.load_initial()
        except Exception as exc:
            messagebox.showerror("Reload failed", str(exc))

    def compact(self, value, max_len: int = 120) -> str:
        text = json.dumps(value, sort_keys=True, default=str) if isinstance(value, (dict, list, tuple)) else repr(value)
        text = text.replace("\n", " ")
        return text if len(text) <= max_len else text[: max_len - 3] + "..."

    def get_deps(self, name: str) -> list[str]:
        deps = self.graph.get("dependencies", {})
        return list(deps.get(name, [])) if isinstance(deps, dict) else []

    def get_dependents(self, name: str) -> list[str]:
        rev = self.graph.get("reverse_dependencies", {})
        return list(rev.get(name, [])) if isinstance(rev, dict) else []

    def get_scan_mode(self, name: str) -> str:
        scan_modes = self.graph.get("scan_modes", {})
        return str(scan_modes.get(name, "")) if isinstance(scan_modes, dict) else ""

    def row_values(self, name: str, desc: dict) -> tuple[str, ...]:
        return (
            name,
            str(desc.get("plugin_type", "")),
            self.get_scan_mode(name),
            self.compact(desc.get("value"), 80),
            ", ".join(self.get_deps(name)),
            ", ".join(self.get_dependents(name)),
            self.compact(desc.get("config", {}), 120),
            self.compact(desc.get("state", {}), 120),
            self.compact(desc.get("metadata", {}), 120),
        )

    def filtered_names(self) -> list[str]:
        text = self.filter_var.get().strip().lower()
        names = sorted(self.rows)
        if not text:
            return names
        out = []
        for name in names:
            desc = self.rows[name]
            hay = " ".join(
                [
                    name,
                    str(desc.get("plugin_type", "")),
                    json.dumps(desc.get("config", {}), sort_keys=True, default=str),
                    json.dumps(desc.get("state", {}), sort_keys=True, default=str),
                    json.dumps(desc.get("metadata", {}), sort_keys=True, default=str),
                ]
            ).lower()
            if text in hay:
                out.append(name)
        return out

    def render_tree(self) -> None:
        existing = set(self.tree.get_children())
        wanted = self.filtered_names()

        for iid in existing - set(wanted):
            self.tree.delete(iid)

        for name in wanted:
            values = self.row_values(name, self.rows[name])
            if self.tree.exists(name):
                self.tree.item(name, values=values)
            else:
                self.tree.insert("", "end", iid=name, values=values)

        if self.selected_name and self.tree.exists(self.selected_name):
            self.tree.selection_set(self.selected_name)

    def sort_by(self, column: str) -> None:
        self.sort_reverse = not self.sort_reverse
        items = [(self.tree.set(k, column), k) for k in self.tree.get_children("")]
        items.sort(reverse=self.sort_reverse)
        for index, (_, k) in enumerate(items):
            self.tree.move(k, "", index)

    def on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        name = selected[0]
        self.selected_name = name
        self.show_detail(name)

    def show_detail(self, name: str) -> None:
        desc = self.rows.get(name, {})
        detail = {
            "name": name,
            "plugin_type": desc.get("plugin_type"),
            "scan_mode": self.get_scan_mode(name),
            "value": desc.get("value"),
            "dependencies": self.get_deps(name),
            "dependents": self.get_dependents(name),
            "config": desc.get("config", {}),
            "state": desc.get("state", {}),
            "metadata": desc.get("metadata", {}),
        }
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", json.dumps(detail, indent=2, sort_keys=True, default=str))

    def push_event_text(self, event: dict) -> None:
        summary = f"{event.get('event')} | {event.get('name', '')}"
        if "value" in event:
            summary += f" | value={self.compact(event.get('value'), 50)}"
        self.event_list.insert(0, summary)
        while self.event_list.size() > 100:
            self.event_list.delete(tk.END)

    def start_subscription_thread(self) -> None:
        def worker() -> None:
            try:
                with self.client.subscribe(send_initial=False) as sub:
                    for event in sub:
                        if self.stop_flag.is_set():
                            break
                        self.events.put(event)
            except Exception as exc:
                self.events.put({"event": "monitor_error", "error": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def process_events(self) -> None:
        dirty_graph = False
        try:
            while True:
                event = self.events.get_nowait()
                et = event.get("event")
                self.push_event_text(event)

                if et in {"parameter_added", "parameter_snapshot"}:
                    name = event["name"]
                    self.rows[name] = {
                        "plugin_type": event.get("plugin_type"),
                        "value": event.get("value"),
                        "config": event.get("config", {}),
                        "state": event.get("state", {}),
                        "metadata": event.get("metadata", {}),
                    }
                    dirty_graph = True

                elif et == "parameter_removed":
                    name = event["name"]
                    self.rows.pop(name, None)
                    if self.tree.exists(name):
                        self.tree.delete(name)
                    dirty_graph = True

                elif et == "value_changed":
                    name = event["name"]
                    if name in self.rows:
                        self.rows[name]["value"] = event.get("value")

                elif et == "config_changed":
                    name = event["name"]
                    if name in self.rows:
                        self.rows[name]["config"] = event.get("config", {})
                        dirty_graph = True

                elif et == "metadata_changed":
                    name = event["name"]
                    if name in self.rows:
                        self.rows[name]["metadata"] = event.get("metadata", {})

                elif et == "state_changed":
                    name = event["name"]
                    if name in self.rows:
                        self.rows[name]["state"] = event.get("state", {})

                elif et == "monitor_error":
                    self.status_var.set(f"Disconnected: {event.get('error')}")

            
        except queue.Empty:
            pass

        if dirty_graph:
            try:
                self.graph = self.client.graph_info()
            except Exception:
                pass

        self.render_tree()
        if self.selected_name:
            self.show_detail(self.selected_name)

        active_count = len(self.graph.get("active_parameters", [])) if isinstance(self.graph, dict) else 0
        warnings_count = len(self.graph.get("warnings", [])) if isinstance(self.graph, dict) else 0
        self.status_var.set(
            f"Connected | parameters={len(self.rows)} | active={active_count} | warnings={warnings_count}"
        )
        self.root.after(100, self.process_events)

    def refresh_status(self) -> None:
        try:
            stats = self.client.stats()
            active_count = len(self.graph.get("active_parameters", [])) if isinstance(self.graph, dict) else 0
            warnings_count = len(self.graph.get("warnings", [])) if isinstance(self.graph, dict) else 0
            self.status_var.set(
                "Connected | "
                f"parameters={len(self.rows)} | active={active_count} | warnings={warnings_count} | "
                f"cycle={stats.get('cycle_count')} | scan={stats.get('last_scan_duration_s', 0):.5f}s"
            )
        except Exception as exc:
            self.status_var.set(f"Disconnected: {exc}")
        if not self.stop_flag.is_set():
            self.root.after(2000, self.refresh_status)

    def show_graph_summary(self) -> None:
        try:
            graph = self.client.graph_info()
        except Exception as exc:
            messagebox.showerror("Graph info failed", str(exc))
            return

        win = tk.Toplevel(self.root)
        win.title("Graph Info")
        win.geometry("900x700")
        txt = tk.Text(win, wrap="none")
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert("1.0", json.dumps(graph, indent=2, sort_keys=True, default=str))

    def show_snapshot_json(self) -> None:
        try:
            snapshot = self.client.snapshot()
        except Exception as exc:
            messagebox.showerror("Snapshot failed", str(exc))
            return

        win = tk.Toplevel(self.root)
        win.title("Snapshot")
        win.geometry("700x600")
        txt = tk.Text(win, wrap="none")
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert("1.0", json.dumps(snapshot, indent=2, sort_keys=True, default=str))

    def on_close(self) -> None:
        self.stop_flag.set()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="RealtimeDB verify monitor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    root = tk.Tk()
    client = SignalClient(args.host, args.port, timeout=5.0)
    MonitorApp(root, client)
    root.mainloop()


if __name__ == "__main__":
    main()
