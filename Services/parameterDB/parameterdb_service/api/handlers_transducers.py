from __future__ import annotations

from typing import Any


def register_transducer_handlers(server: Any) -> None:
    d = server.dispatcher
    d.register("list_transducers", server.api_list_transducers)
    d.register("create_transducer", server.api_create_transducer)
    d.register("update_transducer", server.api_update_transducer)
    d.register("delete_transducer", server.api_delete_transducer)
