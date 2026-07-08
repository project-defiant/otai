"""Command implementations, decoupled from the CLI/typer layer.

Each function here takes an explicit cache_dir (and any network-touching
dependencies as injectable callables) and returns a plain JSON-envelope
dict, so it can be unit tested directly without going through the CLI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from otai import catalog, envelope, schema_builder
from otai import croissant as croissant_mod
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


def list_datasets(
    cache_dir: Path,
    release: str | None = None,
    fetch_xml=releases_mod.default_fetch_listing_xml,
    fetch_croissant=croissant_mod.default_fetch_croissant,
    base_uri: str = schema_builder.DEFAULT_BASE_URI,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Implements `otai list-datasets`: single-release dataset catalog listing.

    Resolves `release` to `latest` when omitted (via releases.get_releases),
    ensures that release's croissant.json is cached (fetched at most once -
    PRD §5) and its DuckDB schema/views exist (built lazily on first use -
    PRD §6), then returns each dataset's name and one-line description.
    """
    if release is None:
        try:
            _release_names, release, _from_cache = releases_mod.get_releases(
                cache_dir, fetch_xml=fetch_xml, now=now
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a structured envelope
            return envelope.failure(
                "s3_error", f"Failed to resolve latest release: {exc}"
            )

    try:
        croissant_data = croissant_mod.get_croissant(
            cache_dir, release, fetch=fetch_croissant
        )
        datasets = croissant_mod.parse_datasets(croissant_data)
    except Exception as exc:  # noqa: BLE001
        return envelope.failure(
            "croissant_error",
            f"Failed to load croissant.json for release {release!r}: {exc}",
        )

    conn = None
    try:
        conn = catalog.connect_catalog(cache_dir)
        if release not in catalog.list_cached_schemas(conn):
            schema_builder.build_release_schema(conn, release, datasets, base_uri)
    except Exception as exc:  # noqa: BLE001
        return envelope.failure(
            "catalog_error",
            f"Failed to build schema for release {release!r}: {exc}",
        )
    finally:
        if conn is not None:
            conn.close()

    rows = [{"dataset": d.name, "description": d.description} for d in datasets]
    return envelope.success({"release": release, "datasets": rows})
