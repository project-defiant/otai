"""Shared JSON cache file I/O: tolerant reads, atomic writes.

Used by both `releases.py` (24h TTL "latest release" cache) and
`croissant.py` (permanent per-release cache) - each needs the same two
properties: a corrupt or unreadable cache file is treated as a miss rather
than raised (the caller refetches/rebuilds instead of permanently failing
that cache entry), and a write can never be interrupted mid-way into a
partially-written (corrupt) file.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger


def read_json_or_none(path: Path) -> Any | None:
    """Return the parsed JSON at `path`, or `None` if absent or corrupt."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.warning(f"Cache file {path} is corrupt ({exc}); treating as a miss")
        return None


def write_json_atomic(path: Path, data: Any) -> None:
    """Write `data` as JSON to `path` atomically (temp file + rename).

    The rename is atomic on POSIX, so a crash/interruption mid-write can
    never leave a partially-written file in `path`'s place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as tmp_file:
            tmp_file.write(json.dumps(data))
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
