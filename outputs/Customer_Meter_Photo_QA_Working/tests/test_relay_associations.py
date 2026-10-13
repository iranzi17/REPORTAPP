from meter_photo_qa.progress_report import load_province_index
from meter_photo_qa.relay_associations import (
    _allowed_rules_for_pair,
    build_relay_apply_edits,
    resolve_relay_bay,
)


class _Feature:
    def __init__(self, **attributes):
        self.attributes = attributes


def test_rwanda_province_index_covers_all_districts_once():
    provinces = load_province_index()
    assert list(provinces) == [
        "City of Kigali",
        "Eastern Province",
        "Northern Province",
        "Southern Province",
        "Western Province",
    ]
    districts = [district for values in provinces.values() for district in values]
    assert len(districts) == 30
    assert len(set(districts)) == 30
    assert provinces["City of Kigali"] == ["Gasabo", "Kicukiro", "Nyarugenge"]


def test_relay_type_resolves_line_or_transformer_bay_before_generic_id():
    bays = [
        _Feature(
            OBJECTID=1,
            Substation_ID="TEST_SS",
            assetid="TEST-EBAY01",
            Line_Bay_ID="E01",
            Trx_Bay_ID=None,
            Bay_ID=None,
        ),
        _Feature(
            OBJECTID=2,
            Substation_ID="TEST_SS",
            assetid="TEST-EBAY02",
            Line_Bay_ID=None,
            Trx_Bay_ID="E01",
            Bay_ID=None,
        ),
    ]
    distance = {
        "ASSETTYPE": 1,
        "NameofSubstation": "TEST",
        "Bay_ID": "E01",
    }
    differential = {
        "ASSETTYPE": 2,
        "NameofSubstation": "TEST",
        "Bay_ID": "E01",
    }
    line_matches, line_field, _ = resolve_relay_bay(distance, bays)
    trx_matches, trx_field, _ = resolve_relay_bay(differential, bays)
    assert [item.attributes["OBJECTID"] for item in line_matches] == [1]
    assert line_field == "Line_Bay_ID"
    assert [item.attributes["OBJECTID"] for item in trx_matches] == [2]
    assert trx_field == "Trx_Bay_ID"


def test_transformer_differential_keeps_every_configured_winding_rule():
    rules = {
        (2, 11, 4): [
            {"device_terminal": 4, "relay_terminal": 1},
            {"device_terminal": 5, "relay_terminal": 1},
        ],
        (2, 11, 1): [
            {"device_terminal": 6, "relay_terminal": 1},
            {"device_terminal": 7, "relay_terminal": 1},
            {"device_terminal": 8, "relay_terminal": 1},
        ],
    }
    schema = {
        "asset_configuration": {(11, 4): 3, (11, 1): 4},
        "configuration_terminals": {3: {4, 5}, 4: {6, 7, 8}},
    }
    two_winding = _allowed_rules_for_pair(
        rules, 2, {"ASSETGROUP": 11, "ASSETTYPE": 4}, schema
    )
    three_winding = _allowed_rules_for_pair(
        rules, 2, {"ASSETGROUP": 11, "ASSETTYPE": 1}, schema
    )
    assert [item["device_terminal"] for item in two_winding] == [4, 5]
    assert [item["device_terminal"] for item in three_winding] == [6, 7, 8]


def test_relay_apply_payload_preserves_rule_direction_and_terminals():
    payload = build_relay_apply_edits(
        [
            {
                "status": "PROPOSE",
                "_from_source_id": 16,
                "_from_globalid": "{DEVICE}",
                "_from_terminal_id": 4,
                "_to_source_id": 21,
                "_to_globalid": "{RELAY}",
                "_to_terminal_id": 1,
            },
            {
                "status": "EXISTING",
                "_from_source_id": 16,
                "_from_globalid": "{SKIP}",
                "_from_terminal_id": 5,
                "_to_source_id": 21,
                "_to_globalid": "{SKIP-RELAY}",
                "_to_terminal_id": 1,
            },
        ]
    )
    attrs = payload[0]["adds"][0]["attributes"]
    assert payload[0]["id"] == 500001
    assert len(payload[0]["adds"]) == 1
    assert attrs == {
        "fromNetworkSourceId": 16,
        "fromGlobalId": "{DEVICE}",
        "fromTerminalId": 4,
        "toNetworkSourceId": 21,
        "toGlobalId": "{RELAY}",
        "toTerminalId": 1,
        "associationType": 1,
        "isContentVisible": 0,
    }
