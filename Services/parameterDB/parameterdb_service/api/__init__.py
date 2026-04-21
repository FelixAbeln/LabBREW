from .dispatcher import CommandDispatcher
from .handlers_general import register_general_handlers
from .handlers_graph import register_graph_handlers
from .handlers_parameters import register_parameter_handlers
from .handlers_plugins import register_plugin_handlers
from .handlers_streaming import register_streaming_handlers
from .handlers_transducers import register_transducer_handlers


def register_all_handlers(server) -> None:
    register_general_handlers(server)
    register_graph_handlers(server)
    register_parameter_handlers(server)
    register_transducer_handlers(server)
    register_plugin_handlers(server)
    register_streaming_handlers(server)


__all__ = [
    "CommandDispatcher",
    "register_all_handlers",
]
