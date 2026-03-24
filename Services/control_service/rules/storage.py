from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RULE_DIR = PROJECT_ROOT / "Data" / "Rules"
RULE_DIR = Path("./Data/Rules")


def get_rule_dir() -> Path:
    RULE_DIR.mkdir(parents=True, exist_ok=True)
    return RULE_DIR


def _cleanup_stale_rule_tmp_files(rule_dir: Path) -> None:
    for tmp_path in rule_dir.glob("*.json.*.tmp"):
        try:
            if tmp_path.is_file():
                tmp_path.unlink()
        except OSError:
            pass


def load_rules() -> list[dict]:
    rule_dir = get_rule_dir()
    _cleanup_stale_rule_tmp_files(rule_dir)
    rules: list[dict] = []

    for file in sorted(rule_dir.glob("*.json")):
        try:
            with open(file, "r", encoding="utf-8") as f:
                rules.append(json.load(f))
        except Exception as exc:
            print(f"Failed to load rule file {file}: {exc}")

    return rules


def save_rule(rule: dict) -> Path:
    rule_dir = get_rule_dir()

    rule_id = rule.get("id")
    if not rule_id:
        raise ValueError("Rule must contain an 'id'")

    path = rule_dir / f"{rule_id}.json"

    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rule, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_name, path)

        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise

    return path


def delete_rule(rule_id: str) -> bool:
    path = get_rule_dir() / f"{rule_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False