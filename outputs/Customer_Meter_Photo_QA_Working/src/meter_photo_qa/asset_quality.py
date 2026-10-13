"""Conservative REG Utility Network QA for distribution transformers and LV poles.

Pure validation; no edits. Field mappings are resolved from the live feature
layer by explicit, case-insensitive candidate names. Unavailable fields are
NOT silently called complete. No plant equipment outside the verified
asset-group/type lists is assessed.
"""
from __future__ import annotations
import re
from collections import Counter

ASSETS = {
    "transformer": {
        "title": "Distribution Transformers",
        "layer_id": 7, "asset_group": 12,
        "types": {1:"30kV-400V", 2:"15kV-400V", 3:"17.32kV-220V",
                  4:"11kV-400V", 5:"6.6kV-400V", 6:"11kV-3.3kV"},
        "checks": {
            "name": ["Transfomer_name_", "Transformer_Name", "TransformerName", "Transformer_ID"],
            "owner_name": ["Owner_Name", "OwnerName", "Owner name", "Owner_Name_"],
            "installation_type": ["Type_of_Installation", "Type_of_installation",
                                  "TypeInstallation", "Installation_Type"],
            "phase_normal": ["Phase_Normal", "PhaseNormal", "Phase_Norm", "Phase Normal"],
            "protection_switch": ["Transformer_Protection_Switch", "TransformerProtectionSwitch",
                                  "Protection_Switch", "Transformer_protection_switch"],
            "mounting_support": ["Transformer_mounting_support", "TransformerMountingSupport",
                                 "Mounting_Support", "Transformer_mounting_support_"],
            "lv_feeder_count": ["Number_of_Low_Voltage_feeders", "Number_of_LV_feeders",
                                "Number_of_Low_Voltage_Feeders", "NumberLowVoltageFeeders",
                                "No_of_LV_Feeders", "No_LV_Feeder"],
            # Supplementary fields retained for technical context, not scored
            # as original field-correction gaps.
            "manufacturer": ["Manufacturer", "Manufacturer_Name", "ManufacturerName", "Make"],
            "serial": ["Serial_No", "Serial_Number", "SerialNo", "SerialNumber"],
            "capacity": ["Rated_kVA", "RatedPower_kVA", "Capacity_kVA",
                         "Rated_Capacity_kVA", "Power_kVA"],
        },
        "priority": ("owner_name", "installation_type", "phase_normal",
                     "protection_switch", "mounting_support", "name", "lv_feeder_count"),
    },
    "pole": {
        "title": "LV Poles",
        "layer_id": 12, "asset_group": 7,
        "types": {1:"Wooden", 2:"Concrete", 3:"Steel Pole"},
        "checks": {
            "manufacturer": ["Manufacturer", "Pole_Manufacturer", "Manufacturer_Name", "ManufacturerName", "Make"],
            "notes": ["Notes", "Remarks", "Pole_Notes"],
        },
        "priority": ("manufacturer", "notes"),
    },
}
UNKNOWN = {"", "unknown", "select value", "select", "n/a", "na", "null", "none", "-", "not known", "not recorded"}
NO_NAMEPLATE = re.compile(
    r"\b(?:no|without|missing|absent|not\s+(?:present|available|visible|found))\s+"
    r"(?:manufacturer(?:'s)?\s+)?(?:name\s*plate|nameplate)\b"
    r"|\b(?:name\s*plate|nameplate)\s+(?:missing|absent|not\s+(?:present|available|visible|found))\b",
    re.IGNORECASE,
)


def resolve_fields(layer_fields, asset):
    """Match verified service field names or aliases; never fuzzy guess."""
    if asset not in ASSETS:
        raise ValueError("Asset must be 'transformer' or 'pole'.")
    def norm(value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    fields = [dict(field) for field in layer_fields]
    available = {str(f["name"]).casefold(): str(f["name"])
                 for f in fields if f.get("name")}
    mapping = {}
    for key, candidates in ASSETS[asset]["checks"].items():
        direct = next((available[c.casefold()] for c in candidates
                       if c.casefold() in available), None)
        if direct:
            mapping[key] = direct
            continue
        normalized_candidates = {norm(name) for name in candidates}
        matched = {
            str(field["name"])
            for field in fields
            if field.get("name") and (
                norm(field["name"]) in normalized_candidates
                or norm(field.get("alias")) in normalized_candidates
            )
        }
        # Multiple possible live columns are ambiguous; ask for schema
        # verification rather than silently picking an incorrect one.
        mapping[key] = next(iter(matched)) if len(matched) == 1 else None
    return mapping


def missing_value(value, domain=None):
    """Decoding prevents treating valid coded zero as missing."""
    if value is None:
        return True
    if isinstance(value, str):
        candidate = value.strip().casefold()
        if candidate in UNKNOWN or candidate == "0":
            return True
    if domain and value in domain:
        label = str(domain[value] or "").strip().casefold()
        return label in UNKNOWN
    return False


def domain_map(layer_properties, group_code):
    """Read only subtype-coded domains for our asset group."""
    output = {}
    types = layer_properties.get("types", []) if hasattr(layer_properties, "get") else getattr(layer_properties, "types", [])
    for type_record in types:
        data = dict(type_record)
        if str(data.get("id")) != str(group_code):
            continue
        domains = dict(data.get("domains") or {})
        for field, details in domains.items():
            if not details:
                continue
            values = dict(details).get("codedValues") or []
            output[field] = {v["code"]: v.get("name") for v in values}
    return output


def evaluate_asset(attributes, asset, mapping, domains=None):
    """One record. MISSING_SCHEMA and data GAP are kept distinct."""
    spec = ASSETS[asset]
    if str(attributes.get("ASSETGROUP")) != str(spec["asset_group"]):
        raise ValueError("Asset group does not match requested audit.")
    gid = str(attributes.get("GLOBALID") or "")
    oid = attributes.get("OBJECTID")
    asset_type = attributes.get("ASSETTYPE")
    issues = []
    notes_field = mapping.get("notes")
    note = str(attributes.get(notes_field) or "").strip() if notes_field else ""
    missing_checks = sorted(key for key in spec["priority"] if not mapping.get(key))
    if not gid.strip():
        issues.append("GlobalID missing")
    try:
        type_code = int(asset_type)
    except (TypeError, ValueError):
        type_code = -1
    if type_code not in spec["types"]:
        issues.append("Unknown or unsupported asset type")
    values = {}
    for key, field in mapping.items():
        if not field:
            values[key] = ""
        else:
            raw = attributes.get(field)
            vals = (domains or {}).get(field, {})
            decoded = vals.get(raw, raw)
            values[key] = "" if raw is None else str(decoded)
    if asset == "transformer":
        # Exactly the seven gaps from the previous distribution-transformer
        # register (160 eligible records, 59 with outstanding corrections).
        # Branch and all supplementary nameplate fields are excluded.
        labels = {
            "owner_name": "Owner Name missing/unknown",
            "installation_type": "Type of Installation missing",
            "phase_normal": "Phase Normal missing",
            "protection_switch": "Transformer Protection Switch missing/unknown",
            "mounting_support": "Transformer mounting support missing/unknown",
            "name": "Transformer Name missing",
            "lv_feeder_count": "Number of Low Voltage feeders missing",
        }
        for key, label in labels.items():
            field = mapping.get(key)
            if not field:
                continue
            if missing_value(attributes.get(field), (domains or {}).get(field)):
                issues.append(label)
        # A positive feeder count is normal for commissioned distribution
        # installations, but 0 can be an intentional future/unused asset.
        # Never infer missing from numerical zero without an agreed business rule.
    else:
        field = mapping.get("manufacturer")
        if field and missing_value(attributes.get(field), (domains or {}).get(field)):
            if NO_NAMEPLATE.search(note):
                values["manufacturer_status"] = "DOCUMENTED_NO_NAMEPLATE"
            else:
                values["manufacturer_status"] = "MISSING_MANUFACTURER_EXPLANATION"
                issues.append("Manufacturer missing: Notes must state no name plate")
        elif field:
            values["manufacturer_status"] = "RECORDED"
        else:
            values["manufacturer_status"] = "UNVERIFIED_FIELD"
    status = "GAP" if issues else ("NOT_VERIFIED" if missing_checks else "NO_GAPS_FOUND")
    return {
        "asset": asset,
        "objectid": oid,
        "globalid": gid,
        "asset_group": spec["asset_group"],
        "asset_type": type_code,
        "asset_type_label": spec["types"].get(type_code, "[Unknown]"),
        "username": str(attributes.get("created_user") or "").strip() or "(unattributed)",
        "recorded_district": str(attributes.get("District") or "").strip(),
        "recorded_sector": str(attributes.get("Sector") or "").strip(),
        "recorded_cell": str(attributes.get("Cell") or "").strip(),
        "status": status,
        "issues": issues,
        "unverified_checks": missing_checks,
        "notes": note,
        "values": values,
    }


def summarize_assets(rows):
    counts = Counter(row["status"] for row in rows)
    return {
        "total": len(rows),
        "with_gaps": counts["GAP"],
        "no_gaps_found": counts["NO_GAPS_FOUND"],
        "not_verified": counts["NOT_VERIFIED"],
        "issue_count": sum(len(row["issues"]) for row in rows),
    }
