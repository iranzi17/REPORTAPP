import json

from meter_photo_qa.substation_containment import (
    _bay_label,
    _query_existing_containers,
    _report_containment_rows,
    build_apply_edits,
    classify_association,
    normalize_guid,
)


def test_normalize_guid_is_stable():
    assert normalize_guid(" {abc-def} ") == "{ABC-DEF}"


def test_bay_label_prefers_operational_name_and_id():
    assert _bay_label({"Line_Bay_ID": "E02", "Line_Bay_Name": "JABANA"}) == (
        "E02 - JABANA"
    )
    assert _bay_label({"Trx_Bay_Name": "TRANSFORMER 1"}) == "TRANSFORMER 1"


def test_classification_proposes_only_legal_unambiguous_new_pair():
    assert classify_association("{A}", True, []) == (
        "PROPOSE",
        "Legal, spatially unambiguous, and not already contained",
    )
    assert classify_association("{A}", False, [])[0] == "REVIEW"
    assert classify_association("{A}", True, [], "ambiguous")[0] == "REVIEW"


def test_classification_preserves_and_conflicts_with_existing_containment():
    assert classify_association("{A}", True, ["{a}"])[0] == "EXISTING"
    assert classify_association("{A}", True, ["{B}"])[0] == "CONFLICT"
    assert classify_association("{A}", True, ["{A}", "{B}"])[0] == "CONFLICT"


def test_apply_payload_contains_only_proposals():
    rows = [
        {
            "status": "PROPOSE",
            "_from_source_id": 6,
            "container_globalid": "{FROM}",
            "_to_source_id": 16,
            "content_globalid": "{TO}",
        },
        {
            "status": "REVIEW",
            "_from_source_id": 6,
            "container_globalid": "{SKIP}",
            "_to_source_id": 16,
            "content_globalid": "{SKIP-TO}",
        },
    ]
    payload = build_apply_edits(rows)
    assert payload[0]["id"] == 500001
    assert len(payload[0]["adds"]) == 1
    attrs = payload[0]["adds"][0]["attributes"]
    assert attrs["associationType"] == 2
    assert attrs["isContentVisible"] == 1
    assert attrs["fromTerminalId"] == -1
    assert attrs["toTerminalId"] == -1
    assert attrs["fromGlobalId"] == "{FROM}"
    assert attrs["toGlobalId"] == "{TO}"


class _Feature:
    def __init__(self, **attributes):
        self.attributes = attributes


class _FeatureSet:
    def __init__(self, features):
        self.features = features


class _AssociationLayer:
    def query(self, **_kwargs):
        return _FeatureSet(
            [
                _Feature(
                    FROMGLOBALID="{LIVE}",
                    TOGLOBALID="{CONTENT}",
                    STATUS=56,
                    ERRORCODE=0,
                ),
                _Feature(
                    FROMGLOBALID="{DELETED}",
                    TOGLOBALID="{CONTENT}",
                    STATUS=49,
                    ERRORCODE=0,
                ),
                _Feature(
                    FROMGLOBALID="{ERROR}",
                    TOGLOBALID="{CONTENT}",
                    STATUS=0,
                    ERRORCODE=1,
                ),
            ]
        )


def test_query_existing_containers_keeps_dirty_live_associations():
    result = _query_existing_containers(
        _AssociationLayer(), ["{CONTENT}"], "sde.DEFAULT"
    )
    assert result == {"{CONTENT}": ["{LIVE}"]}


def test_excel_report_rows_do_not_expose_global_ids():
    source = {
        "level": "Bay > Device",
        "substation_id": "TEST_SS",
        "_container_label": "E01 - LINE BAY",
        "_content_label": "DEVICE-01",
        "content_objectid": 10,
        "content_asset_id": "DEVICE-01",
        "content_asset_group_name": "Circuit Breaker",
        "content_asset_type_name": "HV Circuit Breaker",
        "status": "EXISTING",
        "reason": "Already contained",
        "container_globalid": "{PRIVATE-CONTAINER}",
        "content_globalid": "{PRIVATE-CONTENT}",
    }
    report = _report_containment_rows([source])
    assert all("global" not in key.lower() for key in report[0])
    assert "{PRIVATE" not in json.dumps(report)
