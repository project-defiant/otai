import json
from unittest.mock import Mock

import pytest

from otai import croissant

# A small, realistic Croissant 1.0 (http://mlcommons.org/croissant/1.0) fixture:
# a `distribution` of FileSets (each carrying the glob pattern relative to
# the release's output/ prefix) plus a `recordSet` of datasets whose fields
# reference their backing FileSet via `source.fileSet.@id`.
CROISSANT_FIXTURE = {
    "@context": {"@vocab": "https://schema.org/"},
    "@type": "sc:Dataset",
    "name": "Open Targets Platform 26.06",
    "distribution": [
        {
            "@type": "cr:FileSet",
            "@id": "target_files",
            "name": "target_files",
            "encodingFormat": "application/x-parquet",
            "includes": "target/*.parquet",
        },
        {
            "@type": "cr:FileSet",
            "@id": "disease_files",
            "name": "disease_files",
            "encodingFormat": "application/x-parquet",
            "includes": "disease/*.parquet",
        },
        {
            "@type": "cr:FileSet",
            "@id": "association_by_datasource_direct_files",
            "name": "association_by_datasource_direct_files",
            "encodingFormat": "application/x-parquet",
            "includes": "association_by_datasource_direct/*.parquet",
        },
    ],
    "recordSet": [
        {
            "@type": "cr:RecordSet",
            "@id": "target",
            "name": "target",
            "description": "Target (gene/protein) annotation.",
            "field": [
                {
                    "@type": "cr:Field",
                    "@id": "target/id",
                    "name": "id",
                    "dataType": "sc:Text",
                    "source": {
                        "fileSet": {"@id": "target_files"},
                        "extract": {"column": "id"},
                    },
                }
            ],
        },
        {
            "@type": "cr:RecordSet",
            "@id": "disease",
            "name": "disease",
            "description": "Disease/phenotype annotation.",
            "field": [
                {
                    "@type": "cr:Field",
                    "@id": "disease/id",
                    "name": "id",
                    "dataType": "sc:Text",
                    "source": {
                        "fileSet": {"@id": "disease_files"},
                        "extract": {"column": "id"},
                    },
                }
            ],
        },
        {
            "@type": "cr:RecordSet",
            "@id": "association_by_datasource_direct",
            "name": "association_by_datasource_direct",
            "description": "Direct target-disease associations by data source.",
            "field": [
                {
                    "@type": "cr:Field",
                    "@id": "association_by_datasource_direct/targetId",
                    "name": "targetId",
                    "dataType": "sc:Text",
                    "source": {
                        "fileSet": {"@id": "association_by_datasource_direct_files"},
                        "extract": {"column": "targetId"},
                    },
                }
            ],
        },
    ],
}


class TestParseDatasets:
    def test_extracts_name_description_and_file_glob(self):
        datasets = croissant.parse_datasets(CROISSANT_FIXTURE)

        by_name = {d.name: d for d in datasets}
        assert set(by_name) == {"target", "disease", "association_by_datasource_direct"}
        assert by_name["target"].description == "Target (gene/protein) annotation."
        assert by_name["target"].file_glob == "target/*.parquet"
        assert (
            by_name["association_by_datasource_direct"].file_glob
            == "association_by_datasource_direct/*.parquet"
        )

    def test_tolerates_direct_fileset_glob_shape(self):
        # Not every producer necessarily nests the glob under distribution;
        # tolerate a recordSet carrying its glob directly too.
        data = {
            "recordSet": [
                {
                    "name": "simple_dataset",
                    "description": "A dataset with an inline fileSet glob.",
                    "fileSet": "simple_dataset/*.parquet",
                }
            ]
        }
        datasets = croissant.parse_datasets(data)
        assert len(datasets) == 1
        assert datasets[0].name == "simple_dataset"
        assert datasets[0].file_glob == "simple_dataset/*.parquet"

    def test_missing_recordset_yields_empty_list(self):
        assert croissant.parse_datasets({}) == []

    def test_recordset_without_name_is_skipped(self):
        data = {"recordSet": [{"description": "no name here"}]}
        assert croissant.parse_datasets(data) == []


class TestCroissantUrl:
    def test_builds_expected_s3_url(self):
        assert croissant.croissant_url("26.06") == (
            "https://open-targets-public-data-releases.s3.amazonaws.com/"
            "platform/26.06/croissant.json"
        )


class TestGetCroissant:
    def test_fetches_and_caches_on_first_call(self, tmp_path):
        fetch = Mock(return_value=json.dumps(CROISSANT_FIXTURE).encode())

        data = croissant.get_croissant(tmp_path, "26.06", fetch=fetch)

        assert data == CROISSANT_FIXTURE
        fetch.assert_called_once_with("26.06")
        cache_file = tmp_path / "26.06" / "croissant.json"
        assert cache_file.exists()
        assert json.loads(cache_file.read_text()) == CROISSANT_FIXTURE

    def test_second_call_reuses_cache_never_refetches(self, tmp_path):
        fetch = Mock(return_value=json.dumps(CROISSANT_FIXTURE).encode())
        croissant.get_croissant(tmp_path, "26.06", fetch=fetch)

        data = croissant.get_croissant(tmp_path, "26.06", fetch=fetch)

        assert data == CROISSANT_FIXTURE
        fetch.assert_called_once()  # not called again, even without any TTL

    def test_different_releases_are_cached_independently(self, tmp_path):
        other_fixture = {**CROISSANT_FIXTURE, "name": "Open Targets Platform 25.12"}
        fetch = Mock(
            side_effect=lambda release: json.dumps(
                CROISSANT_FIXTURE if release == "26.06" else other_fixture
            ).encode()
        )

        first = croissant.get_croissant(tmp_path, "26.06", fetch=fetch)
        second = croissant.get_croissant(tmp_path, "25.12", fetch=fetch)

        assert first["name"] == "Open Targets Platform 26.06"
        assert second["name"] == "Open Targets Platform 25.12"
        assert fetch.call_count == 2

    def test_invalid_json_raises_croissant_error(self, tmp_path):
        fetch = Mock(return_value=b"not json")

        with pytest.raises(croissant.CroissantError):
            croissant.get_croissant(tmp_path, "26.06", fetch=fetch)

    def test_no_real_network_call_is_ever_made(self, tmp_path):
        fetch = Mock(return_value=json.dumps(CROISSANT_FIXTURE).encode())
        croissant.get_croissant(tmp_path, "26.06", fetch=fetch)
        assert fetch.called
