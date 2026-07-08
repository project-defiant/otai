"""S3 release listing, "latest" resolution, and its 24h TTL local cache.

Releases live as immediate child "folders" (common prefixes) under
s3://open-targets-public-data-releases/platform/, e.g. 25.12, 26.03, 26.06.
"Latest" is defined as the lexically max release name (PRD §4).

Listing the bucket is a real network call in production; every entry point
here that touches the network takes an injectable fetch function so tests
can run fully offline (PRD §10).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

BUCKET = "open-targets-public-data-releases"
PREFIX = "platform/"
LIST_URL = f"https://{BUCKET}.s3.amazonaws.com/?list-type=2&prefix={PREFIX}&delimiter=/"
S3_LISTING_XML_NS = "http://s3.amazonaws.com/doc/2006-03-01/"

CACHE_FILENAME = "latest_release_cache.json"
CACHE_TTL_SECONDS = 24 * 60 * 60


class ReleaseListingError(RuntimeError):
    """Raised when the S3 bucket listing is missing, empty, or unparsable."""


def default_fetch_listing_xml(timeout: float = 10.0) -> bytes:
    """Fetch the raw S3 ListBucketResult XML for the platform/ prefix.

    Real network call - only used in production; tests always inject a
    fake fetch_xml callable instead.
    """
    with urlopen(LIST_URL, timeout=timeout) as response:  # noqa: S310
        return response.read()


def parse_release_folders(xml_bytes: bytes) -> list[str]:
    """Extract immediate child release folder names from a listing XML payload."""
    root = ET.fromstring(xml_bytes)  # noqa: S314 - trusted public AWS S3 listing response
    ns = {"s3": S3_LISTING_XML_NS}
    releases: list[str] = []
    for prefix_el in root.findall(".//s3:CommonPrefixes/s3:Prefix", ns):
        text = (prefix_el.text or "").strip("/")
        parts = text.split("/")
        if len(parts) == 2 and f"{parts[0]}/" == PREFIX:
            releases.append(parts[1])
    return sorted(releases)


def resolve_latest(release_names: list[str]) -> str:
    """Return the lexically max release name; "latest" per PRD §4."""
    if not release_names:
        raise ReleaseListingError("Cannot resolve latest release from an empty list.")
    return max(release_names)


def _cache_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / CACHE_FILENAME


def _load_cache(cache_dir: Path) -> dict | None:
    path = _cache_path(cache_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _save_cache(
    cache_dir: Path, release_names: list[str], latest: str, resolved_at: datetime
) -> None:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "releases": release_names,
        "latest": latest,
        "resolved_at": resolved_at.isoformat(),
    }
    _cache_path(cache_dir).write_text(json.dumps(payload))


def _is_fresh(cache: dict, now: datetime) -> bool:
    try:
        resolved_at = datetime.fromisoformat(cache["resolved_at"])
        release_names = cache["releases"]
        latest = cache["latest"]
    except (KeyError, ValueError, TypeError):
        return False
    if not isinstance(release_names, list) or not isinstance(latest, str):
        return False
    age_seconds = (now - resolved_at).total_seconds()
    return 0 <= age_seconds < CACHE_TTL_SECONDS


def get_releases(
    cache_dir: Path,
    fetch_xml=default_fetch_listing_xml,
    now: datetime | None = None,
) -> tuple[list[str], str, bool]:
    """Resolve the release list and latest release, using the 24h TTL cache.

    Returns (release_names, latest, from_cache).
    """
    now = now or datetime.now(timezone.utc)
    cache = _load_cache(cache_dir)
    if cache is not None and _is_fresh(cache, now):
        return cache["releases"], cache["latest"], True

    xml_bytes = fetch_xml()
    release_names = parse_release_folders(xml_bytes)
    latest = resolve_latest(release_names)
    _save_cache(cache_dir, release_names, latest, now)
    return release_names, latest, False
