"""Command implementations, decoupled from the CLI/typer layer.

Each function here takes an explicit cache_dir (and any network-touching
dependencies as injectable callables) and returns a plain JSON-envelope
dict, so it can be unit tested directly without going through the CLI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

from otai import catalog, envelope, schema_builder, sql_guard
from otai import croissant as croissant_mod
from otai import releases as releases_mod


def _resolve_release(
    cache_dir: Path,
    release: str | None,
    fetch_xml,
    now: datetime | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve `release` to `latest` when omitted.

    Returns `(release, None)` on success, or `(None, failure_envelope)` if
    latest-resolution fails. Shared by list_datasets/describe_dataset/
    run_sql, all of which default to `latest` the same way (PRD §6/§7).
    """
    if release is not None:
        return release, None
    try:
        _release_names, release, _from_cache = releases_mod.get_releases(
            cache_dir, fetch_xml=fetch_xml, now=now
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a structured envelope
        return None, envelope.failure(
            "s3_error", f"Failed to resolve latest release: {exc}"
        )
    else:
        return release, None


def _load_datasets(
    cache_dir: Path, release: str, fetch_croissant
) -> tuple[list[croissant_mod.DatasetInfo] | None, dict[str, Any] | None]:
    """Load (fetch-if-needed-cache) a release's parsed croissant datasets.

    Returns `(datasets, None)` on success, or `(None, failure_envelope)`.
    """
    try:
        croissant_data = croissant_mod.get_croissant(
            cache_dir, release, fetch=fetch_croissant
        )
        return croissant_mod.parse_datasets(croissant_data), None
    except Exception as exc:  # noqa: BLE001
        return None, envelope.failure(
            "croissant_error",
            f"Failed to load croissant.json for release {release!r}: {exc}",
        )


def _ensure_release_schema(
    conn, release: str, datasets: list[croissant_mod.DatasetInfo], base_uri: str
) -> None:
    """Build a release's DuckDB schema/views if not already present (PRD §6)."""
    if release not in catalog.list_cached_schemas(conn):
        schema_builder.build_release_schema(conn, release, datasets, base_uri)


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
    release, error = _resolve_release(cache_dir, release, fetch_xml, now)
    if error is not None:
        return error
    release = cast(str, release)

    datasets, error = _load_datasets(cache_dir, release, fetch_croissant)
    if error is not None:
        return error
    datasets = cast(list[croissant_mod.DatasetInfo], datasets)

    conn = None
    try:
        conn = catalog.connect_catalog(cache_dir)
        _ensure_release_schema(conn, release, datasets, base_uri)
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


def describe_dataset(
    cache_dir: Path,
    name: str,
    release: str | None = None,
    fetch_xml=releases_mod.default_fetch_listing_xml,
    fetch_croissant=croissant_mod.default_fetch_croissant,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Implements `otai describe-dataset <name> [--release X]`.

    Resolves `release` to `latest` when omitted (same pattern as
    list_datasets), then reads the cached croissant.json directly for the
    named dataset's full field list - names, types, descriptions,
    cross-dataset `references`, and nested `subFields` (PRD §5/§7). Does
    not touch the DuckDB catalog: this command has no need for the views.
    """
    release, error = _resolve_release(cache_dir, release, fetch_xml, now)
    if error is not None:
        return error
    release = cast(str, release)

    datasets, error = _load_datasets(cache_dir, release, fetch_croissant)
    if error is not None:
        return error
    datasets = cast(list[croissant_mod.DatasetInfo], datasets)

    dataset = next((d for d in datasets if d.name == name), None)
    if dataset is None:
        return envelope.failure(
            "dataset_not_found",
            f"Dataset {name!r} not found in release {release!r}.",
        )

    return envelope.success(
        {
            "release": release,
            "dataset": dataset.name,
            "description": dataset.description,
            "fields": [field.as_dict() for field in dataset.fields],
        }
    )


def run_sql(
    cache_dir: Path,
    query: str,
    fetch_xml=releases_mod.default_fetch_listing_xml,
    fetch_croissant=croissant_mod.default_fetch_croissant,
    base_uri: str = schema_builder.DEFAULT_BASE_URI,
    now: datetime | None = None,
    row_cap: int = sql_guard.DEFAULT_ROW_CAP,
    timeout_seconds: float = sql_guard.DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Implements `otai run-sql "<query>"`: guarded read-only SQL, latest by
    default with explicit cross-release support (PRD §6/§7, issue #5).

    Unlike list_datasets/describe_dataset, there is no `--release` flag
    (PRD §7): this always resolves `latest`, ensures its croissant is
    cached and its DuckDB schema/views exist (same lazy-init pattern), then
    points the connection's search_path at that release's schema so
    unqualified table names resolve there without callers needing to write
    `"<release>".table`. Actual read-only enforcement, timeout, and row-cap
    guardrails live in sql_guard.run_guarded_query, which this delegates to
    so that guardrail logic stays unit-testable independent of release
    resolution (PRD §10).

    Schema-qualified references to *other* releases (e.g. "26.03".target)
    are resolved explicitly (issue #5): the query is parsed with
    `sql_guard.extract_schema_qualifiers` to find every schema qualifier
    used, each is checked against the full set of known releases (PRD §6
    step 2 / §7 guardrail #2) - an unrecognized qualifier fails fast with
    `release_not_found` before anything is built or executed - and each
    valid qualifier's release schema is lazy-init'd (croissant fetch +
    `CREATE SCHEMA`/views) alongside `latest`, using the same
    `_load_datasets`/`_ensure_release_schema` helpers `list_datasets` uses,
    just called directly since the release string is already known here.
    This is what makes cross-release joins like `"26.06".target JOIN
    "26.03".target` work in a single call with no extra flag.
    """
    # run-sql always targets latest (no --release flag, PRD §7), and always
    # needs the full release list to validate schema qualifiers below - one
    # get_releases call covers both, rather than resolving latest via
    # _resolve_release and then re-fetching the full list separately.
    try:
        release_names, release, _from_cache = releases_mod.get_releases(
            cache_dir, fetch_xml=fetch_xml, now=now
        )
    except Exception as exc:  # noqa: BLE001
        return envelope.failure("s3_error", f"Failed to resolve releases: {exc}")

    qualifiers = sql_guard.extract_schema_qualifiers(query)
    unknown_qualifiers = sorted(set(qualifiers) - set(release_names))
    if unknown_qualifiers:
        return envelope.failure(
            "release_not_found",
            "Query references unknown release(s): " + ", ".join(unknown_qualifiers),
        )

    datasets, error = _load_datasets(cache_dir, release, fetch_croissant)
    if error is not None:
        return error
    datasets = cast(list[croissant_mod.DatasetInfo], datasets)

    extra_releases = sorted(set(qualifiers) - {release})

    conn = None
    try:
        conn = catalog.connect_catalog(cache_dir)
        _ensure_release_schema(conn, release, datasets, base_uri)

        for extra_release in extra_releases:
            extra_datasets, extra_error = _load_datasets(
                cache_dir, extra_release, fetch_croissant
            )
            if extra_error is not None:
                conn.close()
                return extra_error
            extra_datasets = cast(list[croissant_mod.DatasetInfo], extra_datasets)
            _ensure_release_schema(conn, extra_release, extra_datasets, base_uri)

        conn.execute("SET search_path = ?", [f'"{release}"'])
    except Exception as exc:  # noqa: BLE001
        if conn is not None:
            conn.close()
        return envelope.failure(
            "catalog_error",
            f"Failed to prepare release {release!r} for querying: {exc}",
        )

    try:
        result = sql_guard.run_guarded_query(
            conn, query, row_cap=row_cap, timeout_seconds=timeout_seconds
        )
    finally:
        conn.close()

    if result["ok"]:
        result["data"]["release"] = release
    return result
