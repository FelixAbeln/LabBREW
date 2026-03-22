from __future__ import annotations

import threading
import time
from copy import deepcopy


class OwnershipManager:
    def __init__(self):
        self._owners: dict[str, str] = {}
        self._meta: dict[str, dict] = {}
        self._lock = threading.RLock()

    def _build_meta(
        self,
        target: str,
        owner: str,
        *,
        reason: str = "",
        owner_source: str | None = None,
        rule_id: str | None = None,
    ) -> dict:
        meta = {
            "target": target,
            "owner": owner,
            "reason": reason,
            "time": time.time(),
        }
        if owner_source:
            meta["owner_source"] = owner_source
        if rule_id:
            meta["rule_id"] = rule_id
        return meta

    def get_owner(self, target: str) -> str | None:
        with self._lock:
            return self._owners.get(target)

    def request(
        self,
        target: str,
        owner: str,
        *,
        reason: str = "",
        owner_source: str | None = None,
        rule_id: str | None = None,
    ) -> bool:
        with self._lock:
            current = self._owners.get(target)
            if current is None or current == owner:
                self._owners[target] = owner
                self._meta[target] = self._build_meta(
                    target,
                    owner,
                    reason=reason,
                    owner_source=owner_source,
                    rule_id=rule_id,
                )
                return True
            return False

    def release(self, target: str, owner: str) -> bool:
        with self._lock:
            if self._owners.get(target) == owner:
                del self._owners[target]
                self._meta.pop(target, None)
                return True
            return False

    def force_takeover(
        self,
        target: str,
        owner: str,
        reason: str = "",
        *,
        owner_source: str | None = None,
        rule_id: str | None = None,
    ) -> None:
        with self._lock:
            self._owners[target] = owner
            self._meta[target] = self._build_meta(
                target,
                owner,
                reason=reason,
                owner_source=owner_source,
                rule_id=rule_id,
            )

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return deepcopy(self._meta)
