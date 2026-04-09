from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar, TypeVar

from .frame import CanFrame

T = TypeVar("T")


# A handler converts a CanFrame into a domain object (or returns None if it can't)
DomainHandler = Callable[[CanFrame], object | None]


class DomainFactory:
    """
    Registry mapping msg_type -> handler.

    Keeps protocol parsing (BodyFactory) separate from semantic interpretation.
    """
    _handlers: ClassVar[dict[int, DomainHandler]] = {}

    @classmethod
    def clear(cls) -> None:
        cls._handlers.clear()

    @classmethod
    def register(cls, msg_type: int, handler: DomainHandler) -> None:
        cls._handlers[int(msg_type)] = handler

    @classmethod
    def build(cls, frame: CanFrame) -> object | None:
        handler = cls._handlers.get(int(frame.can_id.msg_type))
        if handler is None:
            return None
        return handler(frame)


# Convenience decorator (optional)
def domain_handler(msg_type: int):
    def deco(fn: DomainHandler) -> DomainHandler:
        DomainFactory.register(int(msg_type), fn)
        return fn
    return deco
