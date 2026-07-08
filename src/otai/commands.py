"""Command implementations, decoupled from the CLI/typer layer.

Each function here takes an explicit cache_dir (and any network-touching
dependencies as injectable callables) and returns a plain JSON-envelope
dict, so it can be unit tested directly without going through the CLI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from otai import catalog, envelope
from otai import releases as releases_mod


def list_releases(
    cache_dir: Path,
    fetch_xml=releases_mod.default_fetch_listing_xml,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Implements `otai list-releases`: list S3 releases, flag latest + cached."""
    try:
        release_names, latest, _from_cache = releases_mod.get_releases(
            cache_dir, fetch_xml=fetch_xml, now=now
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a structured envelope
        return envelope.failure("s3_error", f"Failed to list releases from S3: {exc}")

    conn = None
    try:
        conn = catalog.connect_catalog(cache_dir)
        cached_schemas = set(catalog.list_cached_schemas(conn))
    except Exception as exc:  # noqa: BLE001
        return envelope.failure(
            "catalog_error", f"Failed to open local DuckDB catalog: {exc}"
        )
    finally:
        if conn is not None:
            conn.close()

    rows = [
        {
            "release": release,
            "latest": release == latest,
            "cached": release in cached_schemas,
        }
        for release in sorted(release_names)
    ]
    return envelope.success({"releases": rows, "latest": latest})
