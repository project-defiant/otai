"""Croissant dataset descriptor: fetch, permanent local cache, and parsing.

Each Open Targets release publishes a Croissant 1.0
(http://mlcommons.org/croissant/1.0) JSON-LD descriptor at
s3://open-targets-public-data-releases/platform/<release>/croissant.json,
describing every dataset (`recordSet`) available for that release along
with the parquet file glob backing it (`fileSet`, via `distribution`).

Unlike the "latest release" cache (24h TTL, see releases.py), a release's
croissant.json is immutable once published: it is cached locally forever
and never re-fetched once a *valid* cache exists (PRD §5). A corrupt or
unreadable cache (e.g. from an interrupted write) is treated as a cache
miss and silently refetched, same as releases.py already does for its own
cache - the write itself is atomic (temp file + rename) so an interruption
mid-write can't leave a corrupt file in the first place, but this also
covers a cache corrupted by any other means (disk error, manual edit).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
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


def _load_cached_croissant(cache_dir: Path, release: str) -> dict[str, Any] | None:
    """Return the cached croissant.json for a release, or `None` if absent/corrupt."""
    path = _cache_path(cache_dir, release)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _save_croissant_cache(cache_dir: Path, release: str, data: dict[str, Any]) -> None:
    """Write the cache atomically: write to a temp file, then rename over the
    target. The rename is atomic on POSIX, so a crash/interruption mid-write
    can never leave a partially-written (corrupt) cache file in its place.
    """
    path = _cache_path(cache_dir, release)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{CROISSANT_FILENAME}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as tmp_file:
            tmp_file.write(json.dumps(data))
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def get_croissant(
    cache_dir: Path,
    release: str,
    fetch: Callable[[str], bytes] = default_fetch_croissant,
) -> dict[str, Any]:
    """Return the parsed croissant.json for a release, fetching+caching if absent.

    A release's croissant.json is never re-fetched once a *valid* cache
    exists (immutable release data, PRD §5) - unlike releases.get_releases's
    TTL cache. A corrupt cache is treated as a miss and refetched (see
    module docstring), rather than permanently failing that release.
    """
    cached = _load_cached_croissant(cache_dir, release)
    if cached is not None:
        return cached

    raw = fetch(release)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CroissantError(
            f"Invalid croissant.json fetched for release {release!r}: {exc}"
        ) from exc

    _save_croissant_cache(cache_dir, release, data)
    return data


@dataclass(frozen=True)
class FieldReference:
    """A cross-dataset relationship: a field pointing at another dataset's field.

    Croissant 1.0 expresses this on a field as `references.field.@id`, an
    identifier of the form "<recordSetName>/<fieldName>" (e.g.
    "target/id"), which we split into the referenced dataset and field name.
    """

    dataset: str
    field: str


@dataclass(frozen=True)
class FieldInfo:
    """A single `field` (or `subField`) entry of a croissant `recordSet`."""

    name: str
    description: str
    data_type: str
    references: FieldReference | None = None
    sub_fields: tuple[FieldInfo, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable representation used by `describe-dataset` output."""
        return {
            "name": self.name,
            "dataType": self.data_type,
            "description": self.description,
            "references": (
                {"dataset": self.references.dataset, "field": self.references.field}
                if self.references is not None
                else None
            ),
            "subFields": [sub.as_dict() for sub in self.sub_fields],
        }


@dataclass(frozen=True)
class DatasetInfo:
    """A single dataset (croissant `recordSet`) relevant to `list-datasets`."""

    name: str
    description: str
    file_glob: str
    fields: tuple[FieldInfo, ...] = ()


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


def _parse_reference(field: dict[str, Any]) -> FieldReference | None:
    """Parse a field's `references` property into a FieldReference, if present.

    Croissant 1.0 shape: `references.field.@id` = "<recordSetName>/<fieldName>"
    (e.g. an evidence dataset's `targetId` field referencing `target/id`).
    """
    references = field.get("references")
    if not isinstance(references, dict):
        return None
    ref_field = references.get("field")
    if not isinstance(ref_field, dict):
        return None
    ref_id = ref_field.get("@id")
    if not ref_id or "/" not in ref_id:
        return None
    dataset_name, _, field_name = ref_id.rpartition("/")
    if not dataset_name or not field_name:
        return None
    return FieldReference(dataset=dataset_name, field=field_name)


def _parse_data_type(field: dict[str, Any]) -> str:
    data_type = field.get("dataType", "")
    if isinstance(data_type, list):
        return data_type[0] if data_type else ""
    return data_type or ""


def _parse_field(field: dict[str, Any]) -> FieldInfo:
    """Parse a single `field` (or `subField`) entry, recursing into subFields."""
    sub_fields = tuple(
        _parse_field(sub)
        for sub in field.get("subField") or []
        if isinstance(sub, dict)
    )
    return FieldInfo(
        name=field.get("name") or field.get("@id") or "",
        description=field.get("description", ""),
        data_type=_parse_data_type(field),
        references=_parse_reference(field),
        sub_fields=sub_fields,
    )


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
        fields = tuple(
            _parse_field(field)
            for field in record_set.get("field") or []
            if isinstance(field, dict)
        )
        datasets.append(
            DatasetInfo(
                name=name, description=description, file_glob=file_glob, fields=fields
            )
        )
    return datasets
