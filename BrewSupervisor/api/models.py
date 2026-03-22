from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FermenterView(BaseModel):
    id: str
    name: str
    address: str
    host: str
    online: bool = True
    agent_base_url: str
    services_hint: list[str] = Field(default_factory=list)
    services: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None
