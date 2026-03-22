from __future__ import annotations

import json
from dataclasses import dataclass
import re
from urllib import error, parse, request

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
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
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .discovery import MdnsDiscoveryBrowser
from .schedule_codec import ScheduleCodec
from .template_exporter import ScheduleTemplateExporter, TemplateExportOptions
from ..shared_service.styles import AppPalette, build_main_window_stylesheet, build_status_banner_stylesheet, button_role_stylesheet


@dataclass(slots=True)
class ApiClient:
    base_url: str

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _decode_response(self, resp) -> dict:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    def _request(self, req: request.Request | str, *, timeout: float) -> dict:
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return self._decode_response(resp)
        except error.HTTPError as exc:
            message = f"HTTP Error {exc.code}: {exc.reason}"
            details = None
            try:
                payload = self._decode_response(exc)
                if isinstance(payload, dict):
                    details = payload
                    message = str(payload.get("message") or payload.get("error") or message)
            except Exception:
                pass
            raise RuntimeError(message if details is None else f"{message}") from exc

    def get(self, path: str, *, timeout: float = 0.5) -> dict:
        return self._request(f"{self.base_url}{path}", timeout=timeout)

    def post(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload or {}).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._request(req, timeout=5.0)


class MainWindow(QMainWindow):
    def __init__(self, api: ApiClient) -> None:
        super().__init__()
        self.api = api
        self.template_exporter = ScheduleTemplateExporter()
        self.schedule_codec = ScheduleCodec()
        self.setWindowTitle("FCS Scheduler Client")
        self._blink_on = False
        self._last_status: dict = {}
        self._auto_tab_follow = True
        self._log_expanded = False
        self._setup_expanded = True
        self._connected = False
        self._refresh_in_flight = False
        self._normal_poll_ms = 1000
        self._offline_poll_ms = 4000
        self._discovery_browser = MdnsDiscoveryBrowser()
        self._discovery_timer = QTimer(self)
        self._discovery_refresh_ms = 3000
        self.palette = AppPalette()

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        parsed_base = parse.urlsplit(self.api.base_url)
        default_host = parsed_base.hostname or "127.0.0.1"
        default_port = parsed_base.port or (443 if parsed_base.scheme == "https" else 8769)

        self.setup_panel = QWidget()
        setup_layout = QVBoxLayout(self.setup_panel)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(8)

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
        setup_content_layout = QVBoxLayout(self.setup_content)
        setup_content_layout.setContentsMargins(0, 0, 0, 0)
        setup_content_layout.setSpacing(8)

        connection_group = QGroupBox("Service connection")
        connection = QGridLayout(connection_group)
        self.host_input = QComboBox()
        self.host_input.setEditable(True)
        self.host_input.setInsertPolicy(QComboBox.NoInsert)
        self.host_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.host_input.setMinimumContentsLength(22)
        self._set_host_combo_items([default_host], selected=default_host)
        self.port_input = QLineEdit(str(default_port))
        self.port_input.setMaximumWidth(100)
        self.btn_refresh_hosts = QPushButton("Refresh")
        self.btn_connect = QPushButton("Connect")
        self.connection_target_lbl = QLabel("")
        self.connection_target_lbl.setProperty("role", "value")
        self.connection_target_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        connection.addWidget(QLabel("Host / IP"), 0, 0)
        connection.addWidget(self.host_input, 0, 1)
        connection.addWidget(QLabel("Port"), 0, 2)
        connection.addWidget(self.port_input, 0, 3)
        connection.addWidget(self.btn_refresh_hosts, 0, 4)
        connection.addWidget(self.btn_connect, 0, 5)
        connection.addWidget(QLabel("Current target"), 1, 0)
        connection.addWidget(self.connection_target_lbl, 1, 1, 1, 5)
        connection.setColumnStretch(1, 1)
        setup_content_layout.addWidget(connection_group)

        top_group = QGroupBox("Workbook")
        top = QGridLayout(top_group)
        self.workbook_path = QLineEdit()
        self.btn_browse = QPushButton("Browse…")
        self.btn_load = QPushButton("Load workbook")
        self.template_mode = QComboBox()
        self.template_mode.addItems(["Blank template", "Test routine template"])
        self.btn_export_template = QPushButton("Export template")
        self.btn_export_current = QPushButton("Export current")
        top.addWidget(QLabel("Workbook"), 0, 0)
        top.addWidget(self.workbook_path, 0, 1)
        top.addWidget(self.btn_browse, 0, 2)
        top.addWidget(self.btn_load, 0, 3)
        top.addWidget(QLabel("Template mode"), 1, 0)
        top.addWidget(self.template_mode, 1, 1)
        top.addWidget(self.btn_export_template, 1, 2)
        top.addWidget(self.btn_export_current, 1, 3)
        top.setColumnStretch(1, 1)
        setup_content_layout.addWidget(top_group)
        self.setup_panel.setLayout(setup_layout)
        setup_layout.addWidget(self.setup_content)
        layout.addWidget(self.setup_panel)

        self.confirm_banner = QLabel("")
        self.confirm_banner.setVisible(False)
        self.confirm_banner.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.confirm_banner)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.btn_primary = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_prev = QPushButton("Previous")
        self.btn_next = QPushButton("Next")
        for btn in [self.btn_primary, self.btn_stop, self.btn_prev, self.btn_next]:
            btn.setMinimumHeight(44)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            ctrl.addWidget(btn)
        layout.addLayout(ctrl)

        status_group = QGroupBox("Runtime status")
        status_form = QFormLayout(status_group)
        status_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.state_lbl = QLabel("—")
        self.phase_lbl = QLabel("—")
        self.step_lbl = QLabel("—")
        self.elapsed_lbl = QLabel("—")
        self.hold_lbl = QLabel("—")
        self.wait_lbl = QLabel("—")
        self.transition_lbl = QLabel("—")
        for label in [
            self.state_lbl,
            self.phase_lbl,
            self.step_lbl,
            self.elapsed_lbl,
            self.hold_lbl,
            self.wait_lbl,
            self.transition_lbl,
        ]:
            label.setProperty("role", "value")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_form.addRow("State", self.state_lbl)
        status_form.addRow("Phase", self.phase_lbl)
        status_form.addRow("Current step", self.step_lbl)
        status_form.addRow("Step elapsed", self.elapsed_lbl)
        status_form.addRow("Hold elapsed", self.hold_lbl)
        status_form.addRow("Waiting", self.wait_lbl)
        status_form.addRow("Last transition", self.transition_lbl)
        layout.addWidget(status_group)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.startup_table = self._make_table()
        self.plan_table = self._make_table()
        self.tabs.addTab(self.startup_table, "StartupRoutine")
        self.tabs.addTab(self.plan_table, "Plan")
        layout.addWidget(self.tabs, 1)

        self.log_panel = QWidget()
        log_layout = QVBoxLayout(self.log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)
        log_head = QHBoxLayout()
        log_head.setContentsMargins(0, 0, 0, 0)
        self.log_title = QLabel("Log")
        self.log_title.setObjectName("LogTitle")
        self.btn_toggle_log = QPushButton("Show log")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.setChecked(False)
        self.btn_toggle_log.setMaximumWidth(110)
        log_head.addWidget(self.log_title)
        log_head.addStretch(1)
        log_head.addWidget(self.btn_toggle_log)
        self.events = QTextEdit()
        self.events.setReadOnly(True)
        self.events.setVisible(False)
        self.events.setMinimumHeight(140)
        self.events.setMaximumHeight(220)
        log_layout.addLayout(log_head)
        log_layout.addWidget(self.events, 1)
        layout.addWidget(self.log_panel, 0)

        self.setCentralWidget(root)
        self._wire()
        self._apply_styles()
        self._sync_connection_target_label()
        self._start_discovery()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(self._normal_poll_ms)
        self._discovery_timer.timeout.connect(self.refresh_discovered_hosts)
        self._discovery_timer.start(self._discovery_refresh_ms)
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._toggle_confirm_blink)
        self._sync_setup_visibility()
        self._sync_log_visibility()
        self.refresh_status()

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels(["#", "Enabled", "Name", "Actions", "Wait", "Source", "Criteria", "Confirm"])
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setFocusPolicy(Qt.NoFocus)
        table.setShowGrid(True)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _apply_styles(self) -> None:
        self.setStyleSheet(build_main_window_stylesheet(self.palette))
        self.confirm_banner.setStyleSheet(build_status_banner_stylesheet(self.palette))

    def _set_button_role_style(self, button: QPushButton, role: str, blink_on: bool = False) -> None:
        button.setStyleSheet(button_role_stylesheet(role=role, blink_on=blink_on, palette=self.palette))

    def _wire(self) -> None:
        self.btn_browse.clicked.connect(self.browse_workbook)
        self.btn_load.clicked.connect(self.load_schedule)
        self.btn_export_template.clicked.connect(self.export_template)
        self.btn_export_current.clicked.connect(self.export_current)
        self.btn_connect.clicked.connect(self.apply_connection_settings)
        self.btn_refresh_hosts.clicked.connect(self.refresh_discovered_hosts)
        self.host_input.lineEdit().returnPressed.connect(self.apply_connection_settings)
        self.port_input.returnPressed.connect(self.apply_connection_settings)
        self.btn_primary.clicked.connect(self.on_primary_button)
        self.btn_stop.clicked.connect(lambda: self._post("/run/stop"))
        self.btn_prev.clicked.connect(lambda: self._post("/run/previous"))
        self.btn_next.clicked.connect(lambda: self._post("/run/next"))
        self.btn_toggle_log.toggled.connect(self._on_toggle_log)
        self.btn_toggle_setup.toggled.connect(self._on_toggle_setup)

    def _on_toggle_setup(self, checked: bool) -> None:
        self._setup_expanded = checked
        self._sync_setup_visibility()

    def _sync_setup_visibility(self) -> None:
        self.setup_content.setVisible(self._setup_expanded)
        self.btn_toggle_setup.setText("Hide setup" if self._setup_expanded else "Show setup")

    def _on_toggle_log(self, checked: bool) -> None:
        self._log_expanded = checked
        self._sync_log_visibility()

    def _sync_log_visibility(self) -> None:
        self.events.setVisible(self._log_expanded)
        self.btn_toggle_log.setText("Hide log" if self._log_expanded else "Show log")
        if self._log_expanded:
            self._scroll_log_to_bottom()

    def _selected_host_text(self) -> str:
        text = self.host_input.currentText().strip()
        if not text:
            return ""
        match = re.search(r"\(([^()]+)\)\s*$", text)
        if match:
            return match.group(1).strip()
        if " — " in text:
            return text.split(" — ", 1)[1].strip()
        return text

    def _host_display_text(self, entry: dict) -> str:
        name = str(entry.get("display_name") or entry.get("name") or "").strip()
        host = str(entry.get("host") or "").strip()
        address = str(entry.get("address") or "").strip()
        target = host or address
        if name and target:
            if address and target != address:
                return f"{name} @ {target} ({address})"
            return f"{name} ({target})"
        if host and address and host != address:
            return f"{host} ({address})"
        return host or address

    def _set_host_combo_items(self, items: list[str], *, selected: str | None = None) -> None:
        current = selected if selected is not None else self.host_input.currentText().strip()
        unique: list[str] = []
        seen: set[str] = set()
        for item in items:
            cleaned = item.strip()
            if cleaned and cleaned not in seen:
                unique.append(cleaned)
                seen.add(cleaned)
        if current and current not in seen:
            unique.insert(0, current)
        self.host_input.blockSignals(True)
        self.host_input.clear()
        self.host_input.addItems(unique)
        self.host_input.setEditText(current or (unique[0] if unique else ""))
        self.host_input.blockSignals(False)

    def _start_discovery(self) -> None:
        try:
            self._discovery_browser.start()
        except Exception:
            return
        self.refresh_discovered_hosts()

    def refresh_discovered_hosts(self) -> None:
        current = self.host_input.currentText().strip()
        discovered: list[str] = []
        try:
            for entry in self._discovery_browser.snapshot():
                display = self._host_display_text(entry)
                if display:
                    discovered.append(display)
        except Exception:
            pass
        self._set_host_combo_items(discovered or ([current] if current else []), selected=current)

    def shutdown(self) -> None:
        try:
            self._discovery_timer.stop()
        except Exception:
            pass
        try:
            self._discovery_browser.close()
        except Exception:
            pass

    def browse_workbook(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select schedule workbook",
            self.workbook_path.text().strip(),
            "Excel Workbook (*.xlsx *.xlsm)",
        )
        if path:
            self.workbook_path.setText(path)

    def _sync_connection_target_label(self) -> None:
        self.connection_target_lbl.setText(self.api.base_url)

    def apply_connection_settings(self) -> None:
        host = self._selected_host_text()
        port_text = self.port_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Service connection", "Enter a host or IP address.")
            return
        try:
            port = int(port_text)
        except ValueError:
            QMessageBox.warning(self, "Service connection", "Port must be a whole number.")
            return
        if not (1 <= port <= 65535):
            QMessageBox.warning(self, "Service connection", "Port must be between 1 and 65535.")
            return

        self.api.set_base_url(f"http://{host}:{port}")
        self._sync_connection_target_label()

        try:
            status = self.api.get("/status")
            service_state = str(status.get("state", "unknown"))
            QMessageBox.information(
                self,
                "Service connection",
                f"Connected to {self.api.base_url}.\n\nService state: {service_state}",
            )
            self.refresh_status()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Service connection",
                f"Updated target to {self.api.base_url}, but the service could not be reached.\n\n{exc}",
            )
            self.refresh_status()

    def export_template(self) -> None:
        suggested_name = "fcs_test_routine_template.xlsx" if self.template_mode.currentIndex() == 1 else "fcs_schedule_template.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Export schedule template", suggested_name, "Excel Workbook (*.xlsx)")
        if not path:
            return
        try:
            options = TemplateExportOptions(include_examples=True, include_test_routine=self.template_mode.currentIndex() == 1)
            exported = self.template_exporter.export(path, options)
            self.workbook_path.setText(str(exported))
            QMessageBox.information(self, "Template exported", f"Template written to:\n{exported}")
        except Exception as exc:
            QMessageBox.critical(self, "Template export failed", str(exc))

    def load_schedule(self) -> None:
        workbook_path = self.workbook_path.text().strip()
        if not workbook_path:
            QMessageBox.warning(self, "Load workbook", "Choose a workbook first.")
            return
        try:
            result, payload = self.schedule_codec.load_excel_as_payload(workbook_path)
            if not result.ok:
                QMessageBox.warning(self, "Load workbook", result.message)
                return
        except Exception as exc:
            QMessageBox.critical(self, "Load workbook", f"Could not read workbook.\n\n{exc}")
            return

        try:
            validation = self.api.post("/schedule/validate", payload)
        except Exception as exc:
            QMessageBox.critical(self, "Load workbook", f"Validation request failed.\n\n{exc}")
            return

        if not validation.get("ok", False):
            issues = validation.get("issues") or []
            if issues:
                detail = "\n".join(f"- {item}" for item in issues[:12])
                if len(issues) > 12:
                    detail += f"\n- ... and {len(issues) - 12} more"
            else:
                detail = str(validation.get("message", "Schedule validation failed."))
            QMessageBox.warning(self, "Load workbook", f"Schedule validation failed.\n\n{detail}")
            return

        try:
            response = self.api.post("/schedule/upload", payload)
        except Exception as exc:
            QMessageBox.critical(self, "Load workbook", f"Upload failed.\n\n{exc}")
            return

        self.refresh_status()
        if not response.get("ok", True):
            QMessageBox.warning(self, "FCS service", str(response.get("message", "Unknown error")))
            return

        loaded_name = str((payload.get("metadata") or {}).get("workbook_name") or workbook_path)
        QMessageBox.information(self, "Load workbook", f"Schedule uploaded successfully.\n\n{loaded_name}")

    def export_current(self) -> None:
        try:
            response = self.api.get("/schedule/current")
            payload = response.get("schedule") or {}
            has_schedule = bool(response.get("has_schedule"))
            if not has_schedule:
                QMessageBox.warning(self, "Export current", "No schedule is loaded on the service.")
                return
            suggested = str((payload.get("metadata") or {}).get("workbook_name") or "fcs_current_schedule")
            if not suggested.lower().endswith(".xlsx"):
                suggested = f"{suggested}.xlsx"
            path, _ = QFileDialog.getSaveFileName(self, "Export current schedule", suggested, "Excel Workbook (*.xlsx)")
            if not path:
                return
            exported = self.schedule_codec.export_current_workbook(path, payload)
            QMessageBox.information(self, "Current schedule exported", f"Workbook written to:\n{exported}")
        except Exception as exc:
            QMessageBox.critical(self, "Export current", str(exc))

    def on_primary_button(self) -> None:
        state = str(self._last_status.get("state", "idle"))
        waiting_confirmation = bool(self._last_status.get("awaiting_confirmation", False)) or state == "waiting_confirmation"
        if waiting_confirmation:
            self._post("/run/confirm")
            return
        if state == "paused":
            self._post("/run/resume")
            return
        if state in {"running", "startup"}:
            self._post("/run/pause")
            return
        self._post("/run/start")

    def _update_button_states(self, status: dict) -> None:
        state = str(status.get("state", "idle"))
        waiting_confirmation = bool(status.get("awaiting_confirmation", False)) or state == "waiting_confirmation"
        active = state in {"running", "startup", "waiting_confirmation", "paused"}

        if waiting_confirmation:
            self.btn_primary.setText("Confirm")
            self._set_button_role_style(self.btn_primary, "blink", self._blink_on)
            if not self.blink_timer.isActive():
                self.blink_timer.start(500)
        else:
            if self.blink_timer.isActive():
                self.blink_timer.stop()
            if state in {"running", "startup"}:
                self.btn_primary.setText("Pause")
                self._set_button_role_style(self.btn_primary, "green")
            elif state == "paused":
                self.btn_primary.setText("Resume")
                self._set_button_role_style(self.btn_primary, "yellow")
            else:
                self.btn_primary.setText("Start")
                self._set_button_role_style(self.btn_primary, "grey")

        for button in [self.btn_stop, self.btn_prev, self.btn_next]:
            self._set_button_role_style(button, "grey")
            button.setEnabled(active)
        self.btn_primary.setEnabled(True)

        message = str(status.get("confirmation_message", "") or "")
        self.confirm_banner.setVisible(waiting_confirmation and bool(message))
        self.confirm_banner.setText(message)

    def _toggle_confirm_blink(self) -> None:
        self._blink_on = not self._blink_on
        self._update_button_states(self._last_status)

    def refresh_status(self) -> None:
        if self._refresh_in_flight:
            return

        self._refresh_in_flight = True
        try:
            try:
                status = self.api.get("/status", timeout=0.5)
            except Exception as exc:
                self._connected = False
                if self.timer.interval() != self._offline_poll_ms:
                    self.timer.start(self._offline_poll_ms)
                self._last_status = {"state": "disconnected"}
                self.state_lbl.setText(f"Disconnected ({exc})")
                self.phase_lbl.setText("—")
                self.step_lbl.setText("—")
                self.elapsed_lbl.setText("—")
                self.hold_lbl.setText("—")
                self.wait_lbl.setText("Service unavailable")
                self.transition_lbl.setText("—")
                self._fill_table(self.startup_table, [], active=(False, -1))
                self._fill_table(self.plan_table, [], active=(False, -1))
                self._update_button_states(self._last_status)
                return

            self._connected = True
            if self.timer.interval() != self._normal_poll_ms:
                self.timer.start(self._normal_poll_ms)

            self._last_status = status
            self.state_lbl.setText(str(status.get("state", "—")))
            self.phase_lbl.setText(str(status.get("phase", "—")))
            raw_idx = status.get("current_step_index", -1)
            idx = -1 if raw_idx is None or raw_idx == "" else int(raw_idx)
            name = str(status.get("current_step_name", "") or "")
            self.step_lbl.setText(f"{idx + 1 if idx >= 0 else '—'} | {name if name else '—'}")
            self.elapsed_lbl.setText(f"{float(status.get('step_elapsed_s', 0.0)):.1f} s")
            self.hold_lbl.setText(f"{float(status.get('hold_elapsed_s', 0.0)):.1f} s")
            self.wait_lbl.setText(str(status.get("wait_reason", "—")))
            self.transition_lbl.setText(str(status.get("last_transition", "—")))

            active_phase = str(status.get("phase", ""))
            active_index = idx
            self._fill_table(self.startup_table, status.get("startup_steps", []), active=(active_phase == "startup", active_index))
            self._fill_table(self.plan_table, status.get("plan_steps", []), active=(active_phase == "plan", active_index))
            if self._auto_tab_follow:
                self.tabs.setCurrentIndex(0 if active_phase == "startup" else 1)

            self.events.setPlainText("\n".join(status.get("event_log", [])))
            self._scroll_log_to_bottom()
            self._update_button_states(status)
        finally:
            self._refresh_in_flight = False

    def _scroll_log_to_bottom(self) -> None:
        self.events.moveCursor(QTextCursor.End)
        sb = self.events.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.isVisible():
            self._auto_tab_follow = False

    def enable_auto_tab_follow(self) -> None:
        self._auto_tab_follow = True

    def _fill_table(self, table: QTableWidget, steps: list[dict], active: tuple[bool, int]) -> None:
        is_active_phase, active_index = active
        table.clearContents()
        table.setRowCount(len(steps))
        active_row = -1
        for row, step in enumerate(steps):
            actions = "; ".join(action.get("display_text", "") for action in step.get("controller_actions", []))
            criteria = self._criteria_text(step)
            display_index = int(step.get("index", row))
            values = [
                display_index + 1,
                step.get("enabled", True),
                step.get("name", ""),
                actions,
                step.get("wait_type", ""),
                step.get("wait_source", ""),
                criteria,
                step.get("confirmation_message", "") or step.get("require_confirmation", False),
            ]
            highlight = is_active_phase and row == active_index
            if highlight:
                active_row = row
            bg = QColor("#fde68a") if highlight else QColor("#ffffff")
            fg = QColor("#111827")
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setBackground(bg)
                item.setForeground(fg)
                table.setItem(row, col, item)

        header = table.horizontalHeader()
        for col in range(table.columnCount()):
            mode = QHeaderView.ResizeMode.ResizeToContents if col in (0, 1, 2, 4) else QHeaderView.ResizeMode.Stretch
            header.setSectionResizeMode(col, mode)
        header.setStretchLastSection(True)
        table.resizeRowsToContents()

        if is_active_phase and 0 <= active_row < table.rowCount():
            table.scrollToItem(table.item(active_row, 0), QTableWidget.PositionAtCenter)

    def _criteria_text(self, step: dict) -> str:
        wait_type = step.get("wait_type", "")
        if wait_type == "signal":
            operator = step.get("operator", "")
            if operator in {"in_range", "out_of_range"}:
                return f"{operator} [{step.get('threshold_low', '')}, {step.get('threshold_high', '')}] hold={step.get('hold_for_s', 0)}s"
            return f"{operator} {step.get('threshold', '')} hold={step.get('hold_for_s', 0)}s"
        if wait_type == "all_valid":
            return f"{', '.join(step.get('valid_sources', []))} hold={step.get('hold_for_s', 0)}s"
        return f"{step.get('duration_s', 0)}s"

    def _post(self, path: str, payload: dict | None = None, *, refresh: bool = True) -> None:
        try:
            result = self.api.post(path, payload)
            if refresh:
                self.refresh_status()
            if not result.get("ok", True):
                QMessageBox.warning(self, "FCS service", str(result.get("message", "Unknown error")))
        except Exception as exc:
            QMessageBox.critical(self, "FCS service", str(exc))


def run_ui(base_url: str = "http://127.0.0.1:8769") -> int:
    app = QApplication([])
    window = MainWindow(ApiClient(base_url=base_url.rstrip("/")))
    window.resize(1280, 860)
    window.show()
    exit_code = app.exec()
    window.shutdown()
    return exit_code
