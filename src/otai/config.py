"""otai runtime configuration: cache directory and data-source base URI.

The cache directory holds the shared DuckDB catalog file, the "latest
release" resolution cache, and cached per-release croissant.json files. It
defaults to ~/.cache/otai but is overridable via the OTAI_CACHE_DIR
environment variable so tests never touch the real user home directory.

The base URI is the root under which every release's `output/` parquet
files and `croissant.json` live. It defaults to the public Open Targets S3
bucket but is overridable via OTAI_BASE_URI so tests (and the CLI layer,
which has no other injection point) can point it at a local directory of
fixture parquet files instead (PRD §10).
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "OTAI_CACHE_DIR"
BASE_URI_ENV_VAR = "OTAI_BASE_URI"
DEFAULT_BASE_URI = "s3://open-targets-public-data-releases/platform"


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "otai"


def get_cache_dir() -> Path:
    """Resolve the otai cache directory, honoring OTAI_CACHE_DIR if set."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override)
    return default_cache_dir()


def get_base_uri() -> str:
    """Resolve the data-source base URI, honoring OTAI_BASE_URI if set."""
    return os.environ.get(BASE_URI_ENV_VAR, DEFAULT_BASE_URI)
