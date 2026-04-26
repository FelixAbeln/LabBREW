from __future__ import annotations

import socketserver
from pathlib import Path
from typing import Any

from ..parameterdb_core.protocol import (
    encode_message,
    make_error_response,
    make_response,
    read_message,
    validate_request_envelope,
)
from .api import CommandDispatcher, register_all_handlers
from .api.validation import (
    validate_create_transducer,
    validate_create_parameter,
    validate_delete_transducer,
    validate_delete_parameter,
    validate_empty_ok,
    validate_export_snapshot,
    validate_get_parameter_type_ui,
    validate_get_value,
    validate_import_snapshot,
    validate_load_parameter_type_folder,
    validate_set_value,
    validate_snapshot_names,
    validate_subscribe,
    validate_update_transducer,
    validate_update_changes,
)
from .engine import ScanEngine
from .event_broker import EventBroker
from .loader import PluginRegistry, load_parameter_type_folder
from .persistence import (
    AuditLogger,
    build_snapshot_payload,
    load_snapshot_payload_into_store,
)


class RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        client = self.client_address[0] if self.client_address else "unknown"
        self.server.audit_log.log(category="connection", action="opened", client=client)  # type: ignore[attr-defined]
        while True:
            req_id: str | None = None
            cmd: str | None = None
            try:
                req = read_message(self.rfile)
                if req is None:
                    break

                cmd, req_id, payload = validate_request_envelope(req)

                streaming_handler = self.server.dispatcher.get_streaming_handler(cmd)  # type: ignore[attr-defined]
                if streaming_handler is not None:
                    streaming_handler(self, req_id=req_id, payload=payload)
                    break

                result = self.server.dispatch(cmd, payload)  # type: ignore[attr-defined]
                resp = make_response(req_id=req_id, result=result)
            except Exception as exc:
                self.server.audit_log.log(  # type: ignore[attr-defined]
                    category="error",
                    action="command_failed",
                    client=client,
                    req_id=req_id,
                    cmd=cmd,
                    error_type=exc.__class__.__name__,
                    message=str(exc),
                )
                resp = make_error_response(
                    req_id=req_id,
                    error_type=exc.__class__.__name__,
                    message=str(exc),
                )

            self.wfile.write(encode_message(resp))
            self.wfile.flush()
        self.server.audit_log.log(category="connection", action="closed", client=client)  # type: ignore[attr-defined]


class SignalTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        host: str,
        port: int,
        engine: ScanEngine,
        registry: PluginRegistry,
        event_broker: EventBroker,
        *,
        audit_logger: AuditLogger | None = None,
    ):
        super().__init__((host, port), RequestHandler)
        self.engine = engine
        self.registry = registry
        self.event_broker = event_broker
        self.audit_log = audit_logger or AuditLogger(
            "./data/parameterdb_audit.jsonl", enabled=False
        )
        self.snapshot_manager = None
        self.dispatcher = CommandDispatcher()
        register_all_handlers(self)

    def dispatch(self, cmd: str, payload: dict[str, Any]) -> Any:
        return self.dispatcher.dispatch(cmd, payload)

    # general
    def api_stats(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_empty_ok(payload)
        stats = self.engine.stats()
        stats["subscriber_count"] = self.event_broker.subscriber_count()
        stats["snapshot_persistence"] = (
            self.snapshot_manager.stats() if self.snapshot_manager is not None else None
        )
        return stats

    def api_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_empty_ok(payload)
        return self.engine.store.snapshot()

    def api_snapshot_names(self, payload: dict[str, Any]) -> dict[str, Any]:
        clean = validate_snapshot_names(payload)
        return self.engine.store.snapshot_names(clean["names"])

    def api_export_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_export_snapshot(payload)
        snapshot_payload = build_snapshot_payload(self.engine.store)
        snapshot_stats = (
            self.snapshot_manager.stats() if self.snapshot_manager is not None else None
        )
        return {
            "snapshot": snapshot_payload,
            "snapshot_stats": snapshot_stats,
        }

    def api_import_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        clean = validate_import_snapshot(payload)
        store = self.engine.store
        was_running = bool(self.engine.stats().get("running"))
        if was_running:
            self.engine.stop()

        removed_count = 0
        restored_count = 0
        try:
            if clean["replace_existing"]:
                for name in store.list_names():
                    param = store._remove_runtime_param(name)
                    if param is not None:
                        param.on_removed(store)
                        removed_count += 1
            else:
                # When not replacing existing parameters, ensure that the snapshot
                # does not contain any parameter names that are already present
                # in the store. This avoids partial application and the ValueError
                # raised by the underlying store when adding duplicates.
                existing_names = set(store.list_names())
                snapshot = clean["snapshot"]
                snapshot_param_names: set[str] = set()
                if isinstance(snapshot, dict):
                    params = snapshot.get("parameters")  # expected snapshot schema
                    if isinstance(params, dict):
                        snapshot_param_names = set(params.keys())
                overlapping = existing_names & snapshot_param_names
                if overlapping:
                    # Fail early with a clear error message
                    # and without touching the store.
                    raise ValueError(
                        "Snapshot import aborted: parameters "
                        "already exist in store and "
                        f"replace_existing is False: {', '.join(sorted(overlapping))}"
                    )

            restored_count = load_snapshot_payload_into_store(
                store, self.registry, clean["snapshot"]
            )

            if clean["save_to_disk"] and self.snapshot_manager is not None:
                self.snapshot_manager.save_now(force=True)
        finally:
            if was_running:
                self.engine.start()

        self.audit_log.log(
            category="change",
            action="snapshot_imported",
            removed_count=removed_count,
            restored_count=restored_count,
            replace_existing=clean["replace_existing"],
            save_to_disk=clean["save_to_disk"],
        )
        return {
            "ok": True,
            "removed_count": removed_count,
            "restored_count": restored_count,
            "snapshot_stats": self.snapshot_manager.stats()
            if self.snapshot_manager is not None
            else None,
        }

    def api_describe(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_empty_ok(payload)
        return self.engine.store.records()

    def api_list_parameters(self, payload: dict[str, Any]) -> list[str]:
        validate_empty_ok(payload)
        return self.engine.store.list_names()

    # graph
    def api_graph_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_empty_ok(payload)
        return self.engine.graph_info()

    # transducers
    def api_list_transducers(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        validate_empty_ok(payload)
        return self.engine.transducers.list()

    def api_create_transducer(self, payload: dict[str, Any]) -> dict[str, Any]:
        clean = validate_create_transducer(payload)
        item = self.engine.transducers.create(clean["transducer"])
        self.audit_log.log(
            category="change",
            action="transducer_created",
            name=item.get("name"),
        )
        return item

    def api_update_transducer(self, payload: dict[str, Any]) -> dict[str, Any]:
        clean = validate_update_transducer(payload)
        item = self.engine.transducers.update(clean["name"], clean["transducer"])
        self.audit_log.log(
            category="change",
            action="transducer_updated",
            name=clean["name"],
        )
        return item

    def api_delete_transducer(self, payload: dict[str, Any]) -> bool:
        clean = validate_delete_transducer(payload)
        removed = self.engine.transducers.delete(clean["name"])
        if removed:
            self.audit_log.log(
                category="change",
                action="transducer_deleted",
                name=clean["name"],
            )
        return removed

    # plugins
    def api_list_parameter_types(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_empty_ok(payload)
        return self.registry.list_types()

    def api_list_parameter_type_ui(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_empty_ok(payload)
        return self.registry.list_ui()

    def api_get_parameter_type_ui(self, payload: dict[str, Any]) -> dict[str, Any]:
        clean = validate_get_parameter_type_ui(payload)
        return self.registry.get_ui_spec(clean["parameter_type"])

    def api_load_parameter_type_folder(self, payload: dict[str, Any]) -> str:
        clean = validate_load_parameter_type_folder(payload)
        result = load_parameter_type_folder(Path(clean["folder"]), self.registry)
        self.audit_log.log(
            category="change",
            action="parameter_type_folder_loaded",
            folder=clean["folder"],
            parameter_type=result,
        )
        return result

    # parameters
    def api_create_parameter(self, payload: dict[str, Any]) -> bool:
        clean = validate_create_parameter(payload)
        store = self.engine.store
        spec = self.registry.get(clean["parameter_type"])
        param = spec.create(
            clean["name"],
            config=clean["config"],
            value=clean["value"],
            metadata=clean["metadata"],
        )
        store.add(param)
        param.on_added(store)
        self.audit_log.log(
            category="change",
            action="parameter_created",
            name=clean["name"],
            parameter_type=clean["parameter_type"],
            metadata=clean["metadata"],
        )
        return True

    def api_delete_parameter(self, payload: dict[str, Any]) -> bool:
        clean = validate_delete_parameter(payload)
        store = self.engine.store
        param = store._remove_runtime_param(clean["name"])
        if param is not None:
            param.on_removed(store)
            self.audit_log.log(
                category="change", action="parameter_deleted", name=clean["name"]
            )
        return True

    def api_get_value(self, payload: dict[str, Any]) -> Any:
        clean = validate_get_value(payload)
        return self.engine.store.get_value(clean["name"], clean.get("default"))

    def api_set_value(self, payload: dict[str, Any]) -> bool:
        clean = validate_set_value(payload)
        self.engine.store.set_value(clean["name"], clean["value"])

        # External writes set raw signal and leave pipeline output pending until
        # the next scan. Clear prior-cycle pipeline runtime state now so describe/
        # state subscribers do not see stale calibration/transducer metadata.
        param = self.engine.store._get_runtime_param(clean["name"])
        self.engine._clear_database_pipeline_state(param)
        param.state["signal_value"] = param.get_signal_value()
        self.engine.store.publish_scan_state(clean["name"], dict(param.state))

        if self.audit_log.audit_external_writes:
            self.audit_log.log(
                category="change",
                action="value_written",
                name=clean["name"],
                value=clean["value"],
            )
        return True

    def api_update_config(self, payload: dict[str, Any]) -> bool:
        clean = validate_update_changes(payload)
        self.engine.store.update_config(clean["name"], **clean["changes"])
        self.audit_log.log(
            category="change",
            action="config_updated",
            name=clean["name"],
            changed_keys=sorted(clean["changes"].keys()),
        )
        return True

    def api_update_metadata(self, payload: dict[str, Any]) -> bool:
        clean = validate_update_changes(payload)
        self.engine.store.update_metadata(clean["name"], **clean["changes"])
        self.audit_log.log(
            category="change",
            action="metadata_updated",
            name=clean["name"],
            changed_keys=sorted(clean["changes"].keys()),
        )
        return True

    # streaming
    def api_subscribe(
        self,
        request_handler: RequestHandler,
        *,
        req_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        clean = validate_subscribe(payload)
        store = self.engine.store
        names = set(clean["names"])
        send_initial = clean["send_initial"]
        token, q, queue_size = self.event_broker.subscribe(
            clean["names"], max_queue=clean["max_queue"]
        )
        self.audit_log.log(
            category="connection",
            action="subscribed",
            subscription_id=token,
            names=clean["names"],
            max_queue=queue_size,
        )

        try:
            request_handler.wfile.write(
                encode_message(
                    make_response(
                        req_id=req_id,
                        result={
                            "status": "subscribed",
                            "subscription_id": token,
                            "max_queue": queue_size,
                        },
                    )
                )
            )
            request_handler.wfile.flush()

            if send_initial:
                current = store.records()
                for name, desc in current.items():
                    if names and name not in names:
                        continue
                    request_handler.wfile.write(
                        encode_message(
                            {
                                "event": "parameter_snapshot",
                                "name": name,
                                **desc,
                            }
                        )
                    )
                request_handler.wfile.flush()

            while True:
                event = q.get()
                event_name = event.get("name")
                if (
                    names
                    and event_name
                    and event_name not in names
                    and event.get("event") != "subscription_overflow"
                ):
                    continue
                request_handler.wfile.write(encode_message(event))
                request_handler.wfile.flush()

        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.event_broker.unsubscribe(token)
            self.audit_log.log(
                category="connection", action="unsubscribed", subscription_id=token
            )
