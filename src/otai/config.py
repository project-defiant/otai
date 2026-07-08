"""otai runtime configuration: cache directory resolution.

The cache directory holds the shared DuckDB catalog file and the
"latest release" resolution cache. It defaults to ~/.cache/otai but is
overridable via the OTAI_CACHE_DIR environment variable so tests never
touch the real user home directory.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "OTAI_CACHE_DIR"


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "otai"


def get_cache_dir() -> Path:
    """Resolve the otai cache directory, honoring OTAI_CACHE_DIR if set."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override)
    return default_cache_dir()
