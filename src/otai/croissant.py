"""Croissant dataset descriptor: fetch, permanent local cache, and parsing.

Each Open Targets release publishes a Croissant 1.0
(http://mlcommons.org/croissant/1.0) JSON-LD descriptor at
s3://open-targets-public-data-releases/platform/<release>/croissant.json,
describing every dataset (`recordSet`) available for that release along
with the parquet file glob backing it (`fileSet`, via `distribution`).

Unlike the "latest release" cache (24h TTL, see releases.py), a release's
croissant.json is immutable once published: it is cached locally forever
and never re-fetched once present (PRD §5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen

BUCKET = "open-targets-public-data-releases"
PREFIX = "platform"
CROISSANT_FILENAME = "croissant.json"


class CroissantError(RuntimeError):
    """Raised when a croissant.json payload is missing or unparsable."""


def croissant_url(release: str) -> str:
    """Return the S3 HTTPS URL of a release's croissant.json."""
    return f"https://{BUCKET}.s3.amazonaws.com/{PREFIX}/{release}/{CROISSANT_FILENAME}"


def default_fetch_croissant(release: str, timeout: float = 10.0) -> bytes:
    """Fetch the raw croissant.json bytes for a release.

    Real network call - only used in production; tests always inject a
    fake fetch callable instead.
    """
    with urlopen(croissant_url(release), timeout=timeout) as response:  # noqa: S310
        return response.read()


def _cache_path(cache_dir: Path, release: str) -> Path:
    return Path(cache_dir) / release / CROISSANT_FILENAME


def get_croissant(
    cache_dir: Path,
    release: str,
    fetch: Callable[[str], bytes] = default_fetch_croissant,
) -> dict[str, Any]:
    """Return the parsed croissant.json for a release, fetching+caching if absent.

    A release's croissant.json is never re-fetched once cached (immutable
    release data, PRD §5) - unlike releases.get_releases's TTL cache.
    """
    path = _cache_path(cache_dir, release)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise CroissantError(
                f"Cached croissant.json for release {release!r} is corrupt: {exc}"
            ) from exc

    raw = fetch(release)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CroissantError(
            f"Invalid croissant.json fetched for release {release!r}: {exc}"
        ) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


@dataclass(frozen=True)
class DatasetInfo:
    """A single dataset (croissant `recordSet`) relevant to `list-datasets`."""

    name: str
    description: str
    file_glob: str


def _distribution_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the top-level `distribution` (FileSet/FileObject) entries by id/name."""
    index: dict[str, dict[str, Any]] = {}
    for entry in data.get("distribution") or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("@id") or entry.get("name")
        if key:
            index[key] = entry
    return index


def _resolve_file_glob(
    record_set: dict[str, Any], distribution: dict[str, dict[str, Any]]
) -> str:
    """Resolve a recordSet's backing file glob, tolerant of shape variations.

    Standard Croissant 1.0 shape: a recordSet's fields reference their
    backing FileSet indirectly via `field[].source.fileSet.@id`, and the
    glob itself (`includes`) lives on the referenced `distribution` entry.
    Also tolerates a recordSet carrying its glob directly under `fileSet`
    (as a plain string, or a dict with `includes`/`@id`).
    """
    direct = record_set.get("fileSet")
    if isinstance(direct, str):
        return direct
    if isinstance(direct, dict):
        if "includes" in direct:
            return direct["includes"]
        ref_id = direct.get("@id")
        if ref_id and ref_id in distribution:
            return distribution[ref_id].get("includes", "")

    for field in record_set.get("field") or []:
        if not isinstance(field, dict):
            continue
        source = field.get("source") or {}
        file_set_ref = source.get("fileSet")
        if isinstance(file_set_ref, dict):
            ref_id = file_set_ref.get("@id")
            if ref_id and ref_id in distribution:
                return distribution[ref_id].get("includes", "")

    return ""


def parse_datasets(data: dict[str, Any]) -> list[DatasetInfo]:
    """Parse the `recordSet` entries of a croissant descriptor into DatasetInfo rows."""
    distribution = _distribution_index(data)
    datasets: list[DatasetInfo] = []
    for record_set in data.get("recordSet") or []:
        if not isinstance(record_set, dict):
            continue
        name = record_set.get("name") or record_set.get("@id") or ""
        if not name:
            continue
        description = record_set.get("description", "")
        file_glob = _resolve_file_glob(record_set, distribution)
        datasets.append(DatasetInfo(name=name, description=description, file_glob=file_glob))
    return datasets
