from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def cleanup_stale_tmp_files(directory: str | Path, glob_pattern: str) -> None:
    base = Path(directory)
    for tmp_path in base.glob(glob_pattern):
        try:
            if tmp_path.is_file():
                tmp_path.unlink()
        except OSError:
            pass


def atomic_write_text(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        Path(tmp_name).replace(target)

        # Best-effort durability of directory entry update.
        try:
            dir_fd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            tmp_path = Path(tmp_name)
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(
    path: str | Path,
    payload: dict[str, Any],
    *,
    indent: int = 2,
    sort_keys: bool = True,
    ensure_ascii: bool = False,
) -> None:
    text = json.dumps(
        payload,
        indent=indent,
        sort_keys=sort_keys,
        ensure_ascii=ensure_ascii,
    )
    atomic_write_text(path, text)
