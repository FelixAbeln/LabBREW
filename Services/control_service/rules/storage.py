from __future__ import annotations

from pathlib import Path
from typing import Any

from .repository import DEFAULT_RULE_DIR, FileRuleRepository, RuleRepository

RULE_DIR = DEFAULT_RULE_DIR
_rule_repository_override: RuleRepository | None = None


def set_rule_repository(repository: RuleRepository | None) -> None:
    global _rule_repository_override
    _rule_repository_override = repository


def _get_rule_repository() -> RuleRepository:
    if _rule_repository_override is not None:
        return _rule_repository_override
    return FileRuleRepository(RULE_DIR)


def get_rule_dir() -> Path:
    repository = _get_rule_repository()
    rule_dir = getattr(repository, "rule_dir", RULE_DIR)
    rule_dir.mkdir(parents=True, exist_ok=True)
    return rule_dir


def _cleanup_stale_rule_tmp_files(rule_dir: Path) -> None:
    for tmp_path in rule_dir.glob("*.json.*.tmp"):
        try:
            if tmp_path.is_file():
                tmp_path.unlink()
        except OSError:
            pass


def load_rules() -> list[dict]:
    return _get_rule_repository().load_rules()


def save_rule(rule: dict) -> Path:
    storage_ref = _get_rule_repository().save_rule(rule)
    return Path(storage_ref) if not str(storage_ref).startswith("postgres:") else Path(RULE_DIR) / f"{rule['id']}.json"


def delete_rule(rule_id: str) -> bool:
    return _get_rule_repository().delete_rule(rule_id)


def rule_repository_stats() -> dict[str, Any]:
    return dict(_get_rule_repository().stats())
