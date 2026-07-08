from datetime import datetime, timezone
from unittest.mock import Mock

from otai import catalog, commands

SAMPLE_LISTING_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <CommonPrefixes><Prefix>platform/25.12/</Prefix></CommonPrefixes>
    <CommonPrefixes><Prefix>platform/26.03/</Prefix></CommonPrefixes>
    <CommonPrefixes><Prefix>platform/26.06/</Prefix></CommonPrefixes>
</ListBucketResult>
"""


def test_list_releases_reports_latest_and_no_cached_schemas(tmp_path):
    fetch = Mock(return_value=SAMPLE_LISTING_XML)

    result = commands.list_releases(
        tmp_path, fetch_xml=fetch, now=datetime(2026, 7, 8, tzinfo=timezone.utc)
    )

    assert result["ok"] is True
    releases_out = {r["release"]: r for r in result["data"]["releases"]}
    assert set(releases_out) == {"25.12", "26.03", "26.06"}
    assert releases_out["26.06"]["latest"] is True
    assert releases_out["25.12"]["latest"] is False
    assert releases_out["26.03"]["latest"] is False
    assert all(r["cached"] is False for r in releases_out.values())
    assert result["data"]["latest"] == "26.06"


def test_list_releases_flags_schemas_already_in_catalog_as_cached(tmp_path):
    conn = catalog.connect_catalog(tmp_path)
    conn.execute('CREATE SCHEMA "25.12"')
    conn.close()

    fetch = Mock(return_value=SAMPLE_LISTING_XML)
    result = commands.list_releases(
        tmp_path, fetch_xml=fetch, now=datetime(2026, 7, 8, tzinfo=timezone.utc)
    )

    releases_out = {r["release"]: r for r in result["data"]["releases"]}
    assert releases_out["25.12"]["cached"] is True
    assert releases_out["26.03"]["cached"] is False
    assert releases_out["26.06"]["cached"] is False


def test_list_releases_returns_failure_envelope_on_s3_error(tmp_path):
    fetch = Mock(side_effect=OSError("network unreachable"))

    result = commands.list_releases(
        tmp_path, fetch_xml=fetch, now=datetime(2026, 7, 8, tzinfo=timezone.utc)
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "s3_error"
    assert "network unreachable" in result["error"]["message"]
