from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import parse

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..shared_service.http_client import ApiClient
from ..shared_service.styles import (
    AppPalette,
    build_main_window_stylesheet,
    build_status_banner_stylesheet,
    button_role_stylesheet,
)


@dataclass(slots=True)
class RuleRow:
    enabled: bool
    rule_id: str
    target: str
    operator: str
    params: str
    severity: str
    hold_for_s: str
    message: str


class RulesEditorWindow(QMainWindow):
    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self.palette = AppPalette()
        self.operator_defs: list[dict] = []
        self._syncing = False
        self._setup_expanded = True

        self.setWindowTitle("Safety Rules Editor")
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        parsed = parse.urlsplit(self.api.base_url)
        default_host = parsed.hostname or "127.0.0.1"
        default_port = parsed.port or 8770

        setup_head = QHBoxLayout()
        setup_head.setContentsMargins(0, 0, 0, 0)
        self.setup_title = QLabel("Setup")
        self.setup_title.setObjectName("SectionTitle")
        self.btn_toggle_setup = QPushButton("Hide setup")
        self.btn_toggle_setup.setCheckable(True)
        self.btn_toggle_setup.setChecked(True)
        self.btn_toggle_setup.setMaximumWidth(110)
        setup_head.addWidget(self.setup_title)
        setup_head.addStretch(1)
        setup_head.addWidget(self.btn_toggle_setup)
        layout.addLayout(setup_head)

        self.setup_content = QWidget()
        setup_layout = QVBoxLayout(self.setup_content)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(8)

        conn_group = QGroupBox("Service connection")
        conn = QGridLayout(conn_group)
        self.host_input = QLineEdit(default_host)
        self.port_input = QLineEdit(str(default_port))
        self.btn_connect = QPushButton("Connect")
        self.btn_reload = QPushButton("Reload rules")
        self.connection_target_lbl = QLabel(self.api.base_url)
        self.connection_target_lbl.setProperty("role", "value")
        self.connection_target_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        conn.addWidget(QLabel("Host / IP"), 0, 0)
        conn.addWidget(self.host_input, 0, 1)
        conn.addWidget(QLabel("Port"), 0, 2)
        conn.addWidget(self.port_input, 0, 3)
        conn.addWidget(self.btn_connect, 0, 4)
        conn.addWidget(self.btn_reload, 0, 5)
        conn.addWidget(QLabel("Current target"), 1, 0)
        conn.addWidget(self.connection_target_lbl, 1, 1, 1, 5)
        conn.setColumnStretch(1, 1)
        setup_layout.addWidget(conn_group)

        status_group = QGroupBox("Service status")
        status_form = QFormLayout(status_group)
        self.service_lbl = QLabel("—")
        self.rule_count_lbl = QLabel("—")
        self.operator_count_lbl = QLabel("—")
        self.operator_hint_lbl = QLabel("—")
        for label in [self.service_lbl, self.rule_count_lbl, self.operator_count_lbl, self.operator_hint_lbl]:
            label.setProperty("role", "value")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_form.addRow("Service", self.service_lbl)
        status_form.addRow("Rules", self.rule_count_lbl)
        status_form.addRow("Operators", self.operator_count_lbl)
        status_form.addRow("Selected operator", self.operator_hint_lbl)
        setup_layout.addWidget(status_group)

        layout.addWidget(self.setup_content)

        action_bar = QHBoxLayout()
        self.btn_add_rule = QPushButton("Add rule")
        self.btn_delete_rule = QPushButton("Delete selected")
        self.btn_duplicate_rule = QPushButton("Duplicate selected")
        self.btn_save = QPushButton("Save rules")
        self.btn_pretty_json = QPushButton("Format JSON")
        for btn in [self.btn_add_rule, self.btn_delete_rule, self.btn_duplicate_rule, self.btn_save, self.btn_pretty_json]:
            btn.setMinimumHeight(40)
            action_bar.addWidget(btn)
        layout.addLayout(action_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        table_panel = QWidget()
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(6)
        self.rules_table = QTableWidget(0, 8)
        self.rules_table.setHorizontalHeaderLabels([
            "Enabled", "Rule ID", "Target", "Operator", "Params JSON", "Severity", "Hold (s)", "Message"
        ])
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.setAlternatingRowColors(False)
        self.rules_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.rules_table.setSelectionMode(QTableWidget.SingleSelection)
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        table_layout.addWidget(self.rules_table)
        splitter.addWidget(table_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        spec_group = QGroupBox("Selected rule spec")
        spec_layout = QVBoxLayout(spec_group)
        self.rule_spec_view = QTextEdit()
        self.rule_spec_view.setReadOnly(True)
        self.rule_spec_view.setMinimumHeight(180)
        spec_layout.addWidget(self.rule_spec_view)
        right_layout.addWidget(spec_group)

        self.json_editor = QTextEdit()
        self.json_editor.setPlaceholderText('{\n  "schema_version": 1,\n  "rules": []\n}')
        right_layout.addWidget(QLabel("Rules JSON"))
        right_layout.addWidget(self.json_editor, 1)

        eval_group = QGroupBox("Evaluate value against rules")
        eval_form = QGridLayout(eval_group)
        self.eval_target = QLineEdit()
        self.eval_value = QLineEdit()
        self.btn_eval = QPushButton("Evaluate")
        self.eval_result = QTextEdit()
        self.eval_result.setReadOnly(True)
        self.eval_result.setMinimumHeight(170)
        eval_form.addWidget(QLabel("Signal"), 0, 0)
        eval_form.addWidget(self.eval_target, 0, 1)
        eval_form.addWidget(QLabel("Value"), 0, 2)
        eval_form.addWidget(self.eval_value, 0, 3)
        eval_form.addWidget(self.btn_eval, 0, 4)
        eval_form.addWidget(self.eval_result, 1, 0, 1, 5)
        eval_form.setColumnStretch(1, 1)
        eval_form.setColumnStretch(3, 1)
        right_layout.addWidget(eval_group)

        splitter.addWidget(right_panel)
        splitter.setSizes([900, 560])
        layout.addWidget(splitter, 1)

        self.banner = QLabel("")
        self.banner.setVisible(False)
        self.banner.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.banner)

        self.setCentralWidget(root)
        self._apply_styles()
        self._wire()
        self._resize_headers()
        self._sync_setup_visibility()
        self.refresh_from_service(show_message=False)

    def _apply_styles(self) -> None:
        self.setStyleSheet(build_main_window_stylesheet(self.palette))
        self.banner.setStyleSheet(build_status_banner_stylesheet(self.palette))
        self.btn_connect.setStyleSheet(button_role_stylesheet("green", palette=self.palette))
        self.btn_reload.setStyleSheet(button_role_stylesheet("grey", palette=self.palette))
        self.btn_save.setStyleSheet(button_role_stylesheet("green", palette=self.palette))
        self.btn_eval.setStyleSheet(button_role_stylesheet("yellow", palette=self.palette))

    def _wire(self) -> None:
        self.btn_toggle_setup.toggled.connect(self._on_toggle_setup)
        self.btn_connect.clicked.connect(self.apply_connection_settings)
        self.btn_reload.clicked.connect(self.refresh_from_service)
        self.btn_add_rule.clicked.connect(self.add_rule)
        self.btn_delete_rule.clicked.connect(self.delete_selected_rule)
        self.btn_duplicate_rule.clicked.connect(self.duplicate_selected_rule)
        self.btn_save.clicked.connect(self.save_rules)
        self.btn_pretty_json.clicked.connect(self.pretty_print_json)
        self.btn_eval.clicked.connect(self.evaluate_value)
        self.rules_table.itemSelectionChanged.connect(self._on_rule_selection_changed)
        self.rules_table.itemChanged.connect(self._on_table_changed)
        self.json_editor.textChanged.connect(self._on_json_changed)

    def _on_toggle_setup(self, checked: bool) -> None:
        self._setup_expanded = checked
        self._sync_setup_visibility()

    def _sync_setup_visibility(self) -> None:
        self.setup_content.setVisible(self._setup_expanded)
        self.btn_toggle_setup.setText("Hide setup" if self._setup_expanded else "Show setup")

    def _set_banner(self, message: str, *, visible: bool = True) -> None:
        self.banner.setText(message)
        self.banner.setVisible(visible and bool(message))

    def _resize_headers(self) -> None:
        header = self.rules_table.horizontalHeader()
        for col in range(self.rules_table.columnCount()):
            mode = QHeaderView.ResizeMode.ResizeToContents if col in (0, 1, 3, 5, 6) else QHeaderView.ResizeMode.Stretch
            header.setSectionResizeMode(col, mode)
        header.setStretchLastSection(True)

    def _selected_row(self) -> int:
        rows = self.rules_table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _table_row_to_rule(self, row: int) -> dict:
        enabled_holder = self.rules_table.cellWidget(row, 0)
        enabled_box = enabled_holder.findChild(QCheckBox) if enabled_holder is not None else None
        enabled = bool(enabled_box.isChecked()) if enabled_box is not None else True

        def text(col: int) -> str:
            item = self.rules_table.item(row, col)
            return item.text().strip() if item is not None else ""

        params_text = text(4) or "{}"
        try:
            params = json.loads(params_text)
            if not isinstance(params, dict):
                raise ValueError("Params JSON must be an object")
        except Exception as exc:
            raise ValueError(f"Row {row + 1}: invalid params JSON: {exc}") from exc

        hold_text = text(6)
        hold_value = 0.0 if hold_text == "" else float(hold_text)
        return {
            "id": text(1),
            "enabled": enabled,
            "target": text(2),
            "operator": text(3),
            "params": params,
            "severity": text(5) or "block",
            "hold_for_s": hold_value,
            "message": text(7),
        }

    def _collect_rules_from_table(self) -> dict:
        rules = [self._table_row_to_rule(row) for row in range(self.rules_table.rowCount())]
        return {"schema_version": 1, "rules": rules}

    def _populate_table(self, payload: dict) -> None:
        rules = list(payload.get("rules", []))
        self._syncing = True
        self.rules_table.setRowCount(0)
        for row, rule in enumerate(rules):
            self.rules_table.insertRow(row)
            enabled_box = QCheckBox()
            enabled_box.setChecked(bool(rule.get("enabled", True)))
            enabled_box.stateChanged.connect(self._on_table_widget_changed)
            enabled_holder = QWidget()
            holder_layout = QHBoxLayout(enabled_holder)
            holder_layout.setContentsMargins(8, 0, 8, 0)
            holder_layout.addWidget(enabled_box)
            holder_layout.addStretch(1)
            self.rules_table.setCellWidget(row, 0, enabled_holder)
            values = [
                str(rule.get("id", "")),
                str(rule.get("target", "")),
                str(rule.get("operator", "")),
                json.dumps(rule.get("params", {}), separators=(",", ": ")),
                str(rule.get("severity", "block")),
                str(rule.get("hold_for_s", 0)),
                str(rule.get("message", "")),
            ]
            for offset, value in enumerate(values, start=1):
                self.rules_table.setItem(row, offset, QTableWidgetItem(value))
        self._syncing = False
        self._resize_headers()
        self.rule_count_lbl.setText(str(len(rules)))
        if self.rules_table.rowCount() > 0 and self._selected_row() < 0:
            self.rules_table.selectRow(0)
        else:
            self._update_selected_rule_spec()

    def _populate_json_editor(self, payload: dict) -> None:
        self._syncing = True
        self.json_editor.setPlainText(json.dumps(payload, indent=2, sort_keys=True))
        self._syncing = False

    def _set_payload(self, payload: dict) -> None:
        payload = {
            "schema_version": int(payload.get("schema_version", 1)),
            "rules": list(payload.get("rules", [])),
        }
        self._populate_table(payload)
        self._populate_json_editor(payload)

    def apply_connection_settings(self) -> None:
        host = self.host_input.text().strip()
        port_text = self.port_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Service connection", "Enter a host or IP address.")
            return
        try:
            port = int(port_text)
        except ValueError:
            QMessageBox.warning(self, "Service connection", "Port must be a whole number.")
            return
        self.api.set_base_url(f"http://{host}:{port}")
        self.connection_target_lbl.setText(self.api.base_url)
        self.refresh_from_service()

    def refresh_from_service(self, *, show_message: bool = True) -> None:
        try:
            health = self.api.get("/status")
            ops = self.api.get("/operators")
            payload = self.api.get("/rules")
        except Exception as exc:
            if show_message:
                QMessageBox.warning(self, "Safety rules service", str(exc))
            self._set_banner(f"Could not reach {self.api.base_url}")
            return

        self.service_lbl.setText(str(health.get("service", "safety")))
        self.rule_count_lbl.setText(str(health.get("rule_count", len(payload.get("rules", [])))))
        self.operator_defs = list(ops.get("operator_defs", []))
        self.operator_count_lbl.setText(str(len(self.operator_defs)))
        self._set_payload(payload)
        self._set_banner(f"Connected to {self.api.base_url}")

    def _on_table_widget_changed(self) -> None:
        if self._syncing:
            return
        try:
            self._populate_json_editor(self._collect_rules_from_table())
            self._update_selected_rule_spec()
        except Exception as exc:
            self._set_banner(str(exc))

    def _on_table_changed(self, _item: QTableWidgetItem) -> None:
        if self._syncing:
            return
        self._on_table_widget_changed()
        self._update_operator_hint_from_selection()

    def _on_json_changed(self) -> None:
        if self._syncing:
            return
        text = self.json_editor.toPlainText().strip()
        if not text:
            return
        try:
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("JSON must describe an object")
            rules = payload.get("rules")
            if not isinstance(rules, list):
                raise ValueError("JSON must include a rules list")
            self._populate_table(payload)
            self._set_banner("JSON parsed successfully")
        except Exception as exc:
            self._set_banner(f"JSON not applied yet: {exc}")

    def pretty_print_json(self) -> None:
        text = self.json_editor.toPlainText().strip() or "{}"
        try:
            payload = json.loads(text)
        except Exception as exc:
            QMessageBox.warning(self, "Format JSON", str(exc))
            return
        self._populate_json_editor(payload)

    def add_rule(self) -> None:
        payload = self._payload_from_editor_or_table()
        next_index = len(payload.get("rules", [])) + 1
        payload.setdefault("rules", []).append(
            {
                "id": f"rule_{next_index}",
                "enabled": True,
                "target": "",
                "operator": self.operator_defs[0]["name"] if self.operator_defs else ">=",
                "params": {"threshold": 0},
                "severity": "block",
                "hold_for_s": 0,
                "message": "",
            }
        )
        self._set_payload(payload)
        self.rules_table.selectRow(self.rules_table.rowCount() - 1)

    def delete_selected_rule(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        payload = self._payload_from_editor_or_table()
        rules = list(payload.get("rules", []))
        if row < len(rules):
            rules.pop(row)
        payload["rules"] = rules
        self._set_payload(payload)

    def duplicate_selected_rule(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        payload = self._payload_from_editor_or_table()
        rules = list(payload.get("rules", []))
        if row >= len(rules):
            return
        clone = dict(rules[row])
        clone["id"] = f"{clone.get('id', 'rule')}_copy"
        rules.insert(row + 1, clone)
        payload["rules"] = rules
        self._set_payload(payload)
        self.rules_table.selectRow(row + 1)

    def _payload_from_editor_or_table(self) -> dict:
        text = self.json_editor.toPlainText().strip()
        if text:
            try:
                payload = json.loads(text)
                if isinstance(payload, dict) and isinstance(payload.get("rules", []), list):
                    return {"schema_version": int(payload.get("schema_version", 1)), "rules": list(payload.get("rules", []))}
            except Exception:
                pass
        return self._collect_rules_from_table()

    def save_rules(self) -> None:
        try:
            payload = self._collect_rules_from_table()
            response = self.api.post("/rules", payload)
        except Exception as exc:
            QMessageBox.critical(self, "Save rules", str(exc))
            return
        self._set_payload(response.get("rules", payload))
        self._set_banner(str(response.get("message", "Rules saved")))

    def _parse_eval_value(self, raw: str):
        text = raw.strip()
        if not text:
            return ""
        for parser in (json.loads,):
            try:
                return parser(text)
            except Exception:
                pass
        lowered = text.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        try:
            if "." in text:
                return float(text)
            return int(text)
        except Exception:
            return text

    def _format_rule_spec(self, rule: dict | None, condition_spec: dict | None = None, observed_values: dict | None = None) -> str:
        if not rule and not condition_spec:
            return "No rule selected."
        rule = dict(rule or {})
        spec = dict(condition_spec or {})
        source = spec.get("source") or rule.get("target", "")
        operator = spec.get("operator") or rule.get("operator", "")
        params = spec.get("params") if isinstance(spec.get("params"), dict) else rule.get("params", {})
        hold = spec.get("hold_for_s") if spec.get("hold_for_s") is not None else rule.get("hold_for_s", 0)
        payload = {
            "rule_id": rule.get("id", ""),
            "enabled": bool(rule.get("enabled", True)),
            "severity": rule.get("severity", "block"),
            "message": rule.get("message", ""),
            "kind": spec.get("kind", "signal"),
            "target": source,
            "operator": operator,
            "params": params or {},
            "hold_for_s": hold,
        }
        if observed_values:
            payload["observed_values"] = observed_values
        return json.dumps(payload, indent=2, sort_keys=True)

    def evaluate_value(self) -> None:
        target = self.eval_target.text().strip()
        if not target:
            QMessageBox.warning(self, "Evaluate", "Enter a signal name.")
            return
        try:
            value = self._parse_eval_value(self.eval_value.text())
            response = self.api.post("/rules", self._collect_rules_from_table())
            payload = response.get("rules", self._collect_rules_from_table())
            self._set_payload(payload)
            result = self.api.post("/evaluate", {"signal_name": target, "value": value})
        except Exception as exc:
            QMessageBox.critical(self, "Evaluate", str(exc))
            return
        matches = list(result.get("matches", []))
        if not matches:
            self.eval_result.setPlainText("No rules matched.")
            return
        blocks: list[str] = []
        for item in matches:
            blocks.append(
                self._format_rule_spec(
                    item.get("rule"),
                    item.get("condition_spec"),
                    item.get("observed_values"),
                )
            )
        self.eval_result.setPlainText("\n\n---\n\n".join(blocks))

    def _on_rule_selection_changed(self) -> None:
        row = self._selected_row()
        if row < 0:
            self.operator_hint_lbl.setText("—")
            self.rule_spec_view.setPlainText("No rule selected.")
            return
        target_item = self.rules_table.item(row, 2)
        if target_item is not None:
            self.eval_target.setText(target_item.text().strip())
        self._update_operator_hint_from_selection()
        self._update_selected_rule_spec()

    def _update_selected_rule_spec(self) -> None:
        row = self._selected_row()
        if row < 0:
            self.rule_spec_view.setPlainText("No rule selected.")
            return
        try:
            rule = self._table_row_to_rule(row)
        except Exception as exc:
            self.rule_spec_view.setPlainText(f"Rule spec unavailable: {exc}")
            return
        self.rule_spec_view.setPlainText(self._format_rule_spec(rule))

    def _update_operator_hint_from_selection(self) -> None:
        row = self._selected_row()
        if row < 0:
            self.operator_hint_lbl.setText("—")
            return
        operator_item = self.rules_table.item(row, 3)
        operator_name = operator_item.text().strip() if operator_item is not None else ""
        for item in self.operator_defs:
            if item.get("name") == operator_name:
                schema = item.get("arg_schema") or {}
                schema_hint = ", ".join(f"{k}: {v}" for k, v in schema.items()) or "no params"
                description = str(item.get("description", "")).strip()
                hint = f"{operator_name} — {description} ({schema_hint})" if description else f"{operator_name} ({schema_hint})"
                self.operator_hint_lbl.setText(hint)
                return
        self.operator_hint_lbl.setText(operator_name or "—")


def run_ui(base_url: str = "http://127.0.0.1:8770") -> int:
    app = QApplication([])
    window = RulesEditorWindow(ApiClient(base_url=base_url.rstrip("/")))
    window.resize(1420, 860)
    window.show()
    return app.exec()
