import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from otai import releases

SAMPLE_LISTING_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Name>open-targets-public-data-releases</Name>
    <Prefix>platform/</Prefix>
    <Delimiter>/</Delimiter>
    <CommonPrefixes>
        <Prefix>platform/25.12/</Prefix>
    </CommonPrefixes>
    <CommonPrefixes>
        <Prefix>platform/26.03/</Prefix>
    </CommonPrefixes>
    <CommonPrefixes>
        <Prefix>platform/26.06/</Prefix>
    </CommonPrefixes>
</ListBucketResult>
"""


class TestParseReleaseFolders:
    def test_parses_immediate_child_release_folders(self):
        result = releases.parse_release_folders(SAMPLE_LISTING_XML)
        assert result == ["25.12", "26.03", "26.06"]

    def test_empty_listing_yields_no_releases(self):
        xml = b"""<?xml version="1.0"?>
        <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
        </ListBucketResult>"""
        assert releases.parse_release_folders(xml) == []


class TestResolveLatest:
    def test_lexically_max_release_is_latest(self):
        assert releases.resolve_latest(["25.12", "26.06", "26.03"]) == "26.06"

    def test_single_release_is_latest(self):
        assert releases.resolve_latest(["25.12"]) == "25.12"

    def test_empty_release_list_raises(self):
        with pytest.raises(releases.ReleaseListingError):
            releases.resolve_latest([])


class TestGetReleases:
    def test_fetches_and_caches_on_first_call(self, tmp_path):
        fetch = Mock(return_value=SAMPLE_LISTING_XML)
        now = datetime(2026, 7, 8, tzinfo=timezone.utc)

        result_releases, latest, from_cache = releases.get_releases(
            tmp_path, fetch_xml=fetch, now=now
        )

        assert result_releases == ["25.12", "26.03", "26.06"]
        assert latest == "26.06"
        assert from_cache is False
        fetch.assert_called_once()

    def test_second_call_within_ttl_uses_cache_not_network(self, tmp_path):
        fetch = Mock(return_value=SAMPLE_LISTING_XML)
        now = datetime(2026, 7, 8, tzinfo=timezone.utc)
        releases.get_releases(tmp_path, fetch_xml=fetch, now=now)

        later = now + timedelta(hours=1)
        result_releases, latest, from_cache = releases.get_releases(
            tmp_path, fetch_xml=fetch, now=later
        )

        assert result_releases == ["25.12", "26.03", "26.06"]
        assert latest == "26.06"
        assert from_cache is True
        fetch.assert_called_once()  # not called again

    def test_call_after_ttl_expiry_refetches(self, tmp_path):
        fetch = Mock(return_value=SAMPLE_LISTING_XML)
        now = datetime(2026, 7, 8, tzinfo=timezone.utc)
        releases.get_releases(tmp_path, fetch_xml=fetch, now=now)

        much_later = now + timedelta(hours=25)
        _result_releases, _latest, from_cache = releases.get_releases(
            tmp_path, fetch_xml=fetch, now=much_later
        )

        assert from_cache is False
        assert fetch.call_count == 2

    def test_naive_now_does_not_break_freshness_check_against_aware_cache(
        self, tmp_path
    ):
        # First call with an aware `now` (production default) writes an
        # aware resolved_at into the cache.
        fetch = Mock(return_value=SAMPLE_LISTING_XML)
        aware_now = datetime(2026, 7, 8, tzinfo=timezone.utc)
        releases.get_releases(tmp_path, fetch_xml=fetch, now=aware_now)

        # A second call passing a naive `now` (allowed by the signature)
        # must not raise TypeError when comparing against the aware cache.
        naive_later = datetime(2026, 7, 8, 1, 0, 0)
        result_releases, latest, from_cache = releases.get_releases(
            tmp_path, fetch_xml=fetch, now=naive_later
        )

        assert result_releases == ["25.12", "26.03", "26.06"]
        assert latest == "26.06"
        assert from_cache is True
        fetch.assert_called_once()

    def test_aware_now_does_not_break_freshness_check_against_naive_cache(
        self, tmp_path
    ):
        # First call with a naive `now` writes a naive resolved_at.
        fetch = Mock(return_value=SAMPLE_LISTING_XML)
        naive_now = datetime(2026, 7, 8)
        releases.get_releases(tmp_path, fetch_xml=fetch, now=naive_now)

        # A second call passing an aware `now` must not raise TypeError
        # when comparing against the naive cache.
        aware_later = datetime(2026, 7, 8, 1, 0, 0, tzinfo=timezone.utc)
        result_releases, latest, from_cache = releases.get_releases(
            tmp_path, fetch_xml=fetch, now=aware_later
        )

        assert result_releases == ["25.12", "26.03", "26.06"]
        assert latest == "26.06"
        assert from_cache is True
        fetch.assert_called_once()

    def test_cache_file_persists_across_process_boundaries(self, tmp_path):
        fetch = Mock(return_value=SAMPLE_LISTING_XML)
        now = datetime(2026, 7, 8, tzinfo=timezone.utc)
        releases.get_releases(tmp_path, fetch_xml=fetch, now=now)

        cache_file = tmp_path / releases.CACHE_FILENAME
        assert cache_file.exists()
        payload = json.loads(cache_file.read_text())
        assert payload["latest"] == "26.06"
        assert payload["releases"] == ["25.12", "26.03", "26.06"]
        assert "resolved_at" in payload

    def test_corrupt_cache_file_is_ignored_and_refetched(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / releases.CACHE_FILENAME).write_text("not json")
        fetch = Mock(return_value=SAMPLE_LISTING_XML)

        _result_releases, latest, from_cache = releases.get_releases(
            tmp_path, fetch_xml=fetch, now=datetime(2026, 7, 8, tzinfo=timezone.utc)
        )

        assert from_cache is False
        assert latest == "26.06"

    def test_no_real_network_call_is_ever_made(self, tmp_path):
        # Sanity check that the default fetch function is never invoked when
        # a fetch_xml override is supplied - guards against accidental live
        # network calls creeping into this test module.
        fetch = Mock(return_value=SAMPLE_LISTING_XML)
        releases.get_releases(tmp_path, fetch_xml=fetch, now=datetime.now(timezone.utc))
        assert fetch.called
