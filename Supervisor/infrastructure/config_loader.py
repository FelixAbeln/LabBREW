from __future__ import annotations

from pathlib import Path

import yaml

from ..domain.models import (
    CapabilityArgRule,
    Endpoint,
    ExternalCapability,
    ProvidedCapability,
    ServiceSpec,
    Topology,
)


_LEGACY_SERVICE_KEYS = {"provides", "requires", "capability_args"}
_ALLOWED_SERVICE_KEYS = {
    "module",
    "docs",
    "listen",
    "backend",
    "backends",
    "static_args",
    "advertise_as",
    "env",
    "startup_timeout_s",
    "restart_backoff_s",
    "enabled",
}
_ALLOWED_LISTEN_KEYS = {"host", "port", "proto", "path"}


class YamlTopologyLoader:
    def load(self, path: str | Path) -> Topology:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

        external_capabilities = []
        external_endpoint_by_name: dict[str, Endpoint] = {}
        for name, raw in (data.get("external_capabilities") or {}).items():
            ep = raw["endpoint"]
            endpoint = Endpoint(
                host=ep["host"],
                port=int(ep["port"]),
                proto=ep.get("proto", "tcp"),
                path=ep.get("path", ""),
            )
            external_capabilities.append(
                ExternalCapability(
                    name=name,
                    endpoint=endpoint,
                )
            )
            external_endpoint_by_name[str(name)] = endpoint

        services = []
        for name, raw in (data.get("services") or {}).items():
            self._validate_service_shape(name, raw)

            listen = raw.get("listen") or {}
            advertise_as = tuple(raw.get("advertise_as") or ())
            provides = tuple(
                ProvidedCapability(
                    name=cap_name,
                    bind_host=str(listen.get("host", "0.0.0.0")),
                    port=int(listen["port"]),
                    proto=str(listen.get("proto", "http")),
                    path=str(listen.get("path", "")),
                    advertise=True,
                    healthcheck_type="tcp",
                )
                for cap_name in advertise_as
            )

            backends_raw = raw.get("backends")
            backend = raw.get("backend")
            backend_mappings: list[dict[str, str]] = []

            if isinstance(backends_raw, dict) and backends_raw:
                for capability_name, mapping in backends_raw.items():
                    if not isinstance(mapping, dict):
                        raise ValueError(
                            f"Service '{name}'.backends['{capability_name}'] must be a mapping"
                        )
                    url_flag = str(mapping.get("url_flag") or "").strip()
                    host_flag = str(mapping.get("host_flag") or "").strip()
                    port_flag = str(mapping.get("port_flag") or "").strip()
                    if url_flag and (host_flag or port_flag):
                        raise ValueError(
                            f"Service '{name}'.backends['{capability_name}'] must use either url_flag or host_flag+port_flag"
                        )
                    if url_flag:
                        backend_mappings.append(
                            {
                                "capability": str(capability_name),
                                "mode": "url",
                                "url_flag": url_flag,
                            }
                        )
                        continue
                    if not host_flag or not port_flag:
                        raise ValueError(
                            f"Service '{name}'.backends['{capability_name}'] requires url_flag or host_flag and port_flag"
                        )
                    backend_mappings.append(
                        {
                            "capability": str(capability_name),
                            "mode": "host_port",
                            "host_flag": host_flag,
                            "port_flag": port_flag,
                        }
                    )
            elif backend:
                backend_mappings.append(
                    {
                        "capability": str(backend),
                        "mode": "host_port",
                        "host_flag": "--backend-host",
                        "port_flag": "--backend-port",
                    }
                )

            requires = tuple(item["capability"] for item in backend_mappings)
            capability_arg_rules = tuple(
                CapabilityArgRule(
                    capability=item["capability"],
                    mode=item["mode"],
                    url_flag=item.get("url_flag"),
                    host_flag=item.get("host_flag"),
                    port_flag=item.get("port_flag"),
                )
                for item in backend_mappings
            )

            for item in backend_mappings:
                if item.get("mode") != "url":
                    continue
                capability = str(item["capability"])
                endpoint = external_endpoint_by_name.get(capability)
                if endpoint is None:
                    continue
                if str(endpoint.proto).lower() == "http" and int(endpoint.port) != 8780:
                    raise ValueError(
                        f"Service '{name}'.backends['{capability}'] uses url_flag with external HTTP capability "
                        "that does not target Supervisor Agent port 8780"
                    )

            # Bind args come from the new listen block. This is what prevents services
            # from silently falling back to their internal default port.
            static_args = list(raw.get("static_args") or [])
            if listen:
                static_args = [
                    "--host",
                    str(listen.get("host", "127.0.0.1")),
                    "--port",
                    str(int(listen["port"])),
                    *static_args,
                ]

            env = tuple((str(k), str(v)) for k, v in (raw.get("env") or {}).items())
            services.append(
                ServiceSpec(
                    name=name,
                    module=str(raw["module"]),
                    docs=str(raw["docs"]) if raw.get("docs") else None,
                    provides=provides,
                    requires=requires,
                    capability_arg_rules=capability_arg_rules,
                    static_args=tuple(str(arg) for arg in static_args),
                    env=env,
                    startup_timeout_s=float(raw.get("startup_timeout_s", 20.0)),
                    restart_backoff_s=float(raw.get("restart_backoff_s", 3.0)),
                    enabled=bool(raw.get("enabled", True)),
                )
            )

        return Topology(
            services=tuple(services),
            external_capabilities=tuple(external_capabilities),
            advertise_service_type=data.get("advertise_service_type", "_fcs._tcp.local."),
        )

    def _validate_service_shape(self, service_name: str, raw: object) -> None:
        if not isinstance(raw, dict):
            raise ValueError(f"Service '{service_name}' must be a mapping")

        legacy = sorted(_LEGACY_SERVICE_KEYS.intersection(raw.keys()))
        if legacy:
            joined = ", ".join(legacy)
            raise ValueError(
                f"Service '{service_name}' uses legacy config key(s): {joined}. "
                "Use only the new schema: module, docs, listen, backend, backends, static_args, advertise_as, env, "
                "startup_timeout_s, restart_backoff_s, enabled"
            )

        unknown = sorted(set(raw.keys()) - _ALLOWED_SERVICE_KEYS)
        if unknown:
            joined = ", ".join(unknown)
            raise ValueError(f"Service '{service_name}' has unsupported key(s): {joined}")

        if not raw.get("module"):
            raise ValueError(f"Service '{service_name}' is missing required key 'module'")

        listen = raw.get("listen")
        if listen is not None:
            if not isinstance(listen, dict):
                raise ValueError(f"Service '{service_name}'.listen must be a mapping")
            unknown_listen = sorted(set(listen.keys()) - _ALLOWED_LISTEN_KEYS)
            if unknown_listen:
                joined = ", ".join(unknown_listen)
                raise ValueError(f"Service '{service_name}'.listen has unsupported key(s): {joined}")
            if "port" not in listen:
                raise ValueError(f"Service '{service_name}'.listen is missing required key 'port'")

        advertise_as = raw.get("advertise_as") or []
        if not isinstance(advertise_as, list):
            raise ValueError(f"Service '{service_name}'.advertise_as must be a list")

        docs = raw.get("docs")
        if docs is not None and not isinstance(docs, str):
            raise ValueError(f"Service '{service_name}'.docs must be a string if provided")

        backend = raw.get("backend")
        if backend is not None and not isinstance(backend, str):
            raise ValueError(f"Service '{service_name}'.backend must be a string or null")

        backends = raw.get("backends")
        if backend is not None and backends is not None:
            raise ValueError(
                f"Service '{service_name}' specifies both 'backend' and 'backends'; use one or the other"
            )

        if backends is not None:
            if not isinstance(backends, dict):
                raise ValueError(f"Service '{service_name}'.backends must be a mapping")
            for capability_name, mapping in backends.items():
                if not isinstance(mapping, dict):
                    raise ValueError(
                        f"Service '{service_name}'.backends['{capability_name}'] must be a mapping"
                    )
                host_flag = mapping.get("host_flag")
                port_flag = mapping.get("port_flag")
                url_flag = mapping.get("url_flag")
                has_url_flag = isinstance(url_flag, str) and bool(url_flag.strip())
                has_host_port = isinstance(host_flag, str) and bool(host_flag.strip()) and isinstance(port_flag, str) and bool(port_flag.strip())

                if has_url_flag and has_host_port:
                    raise ValueError(
                        f"Service '{service_name}'.backends['{capability_name}'] cannot define url_flag together with host_flag/port_flag"
                    )

                if has_url_flag:
                    continue

                if not isinstance(host_flag, str) or not host_flag.strip():
                    raise ValueError(
                        f"Service '{service_name}'.backends['{capability_name}'] must define url_flag or a non-empty host_flag"
                    )
                if not isinstance(port_flag, str) or not port_flag.strip():
                    raise ValueError(
                        f"Service '{service_name}'.backends['{capability_name}'].port_flag must be a non-empty string"
                    )
