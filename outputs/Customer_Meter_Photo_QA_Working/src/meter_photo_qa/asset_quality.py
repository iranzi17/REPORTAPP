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
            "manufacturer": ["Manufacturers", "Manufacturer", "Pole_Manufacturer", "Manufacturer_Name", "ManufacturerName", "Make"],
            "notes": ["Notes", "Remarks", "Pole_Notes"],
            "append_cable": ["Append_Cable", "AppendCable", "Append Cable",
                             "Append_Cables", "AppendCables"],
            "height": ["Pole_Height", "PoleHeight", "Height_of_Pole", "Height_Of_Pole",
                       "Pole_Height_m", "Height_m", "Height", "Height of Pole"],
            # Exact field names confirmed in the Structure Junction pole schema.
            "service_pole": ["Service_Pole", "ServicePole", "Service Pole"],
            "structure": ["PoleStructure", "Pole_Structure", "Pole Structure"],
            "insulator_type": ["InsulatorTypes", "Insulator_Types",
                               "InsulatorType", "Insulator Type"],
            "number_of_circuit": ["Number_Circuit", "NumberOfCircuit",
                                  "Number_of_Circuit", "Number of Circuit"],
        },
        "priority": ("manufacturer", "notes", "append_cable",
                     "service_pole", "structure", "insulator_type", "number_of_circuit"),
    },
}
UNKNOWN = {"", "unknown", "select value", "select", "n/a", "na", "null", "none", "-", "not known", "not recorded"}
NO_NAMEPLATE = re.compile(
    r"\b(?:no|without|missing|absent|not\s+(?:present|available|visible|found))\s+"
    r"(?:manufacturer(?:'s)?\s+)?(?:name\s*plate|nameplate)\b"
    r"|\b(?:name\s*plate|nameplate)\s+(?:missing|absent|not\s+(?:present|available|visible|found))\b",
    re.IGNORECASE,
)
# Explicit Kinyarwanda statements mean that the pole has no nameplate.
# Deliberately do not accept "not clear" or "illegible": those say the
# nameplate may exist and warrant a different data-collection review.
NO_NAMEPLATE_RW = re.compile(
    r"\bnta\s+(?:name\s*plate|nameplate)\s+(?:iriho|ibaho|igaragara|yabonetse|ifite)\b"
    r"|\b(?:name\s*plate|nameplate)\s+ntayiriho\b",
    re.IGNORECASE,
)


def has_explicit_no_nameplate_note(note):
    return bool(NO_NAMEPLATE.search(str(note or "")) or
                NO_NAMEPLATE_RW.search(str(note or "")))



MV_HV_PURPOSE = re.compile(
    r"\b(?:mv|hv|medium[\s-]*voltage|high[\s-]*voltage)\s+"
    r"(?:lines?|poles?|towers?|conductors?)\b"
    r"|\b(?:for|supports?|supporting|serves?|serving|carries?|carrying|"
    r"used\s+for|belongs?\s+to)\s+(?:an?\s+)?"
    r"(?:mv|hv|medium[\s-]*voltage|high[\s-]*voltage)\b",
    re.IGNORECASE,
)


def has_explicit_mv_hv_note(note):
    """Accept an affirmative MV/HV use description, not a negated mention."""
    text=" ".join(str(note or "").split())
    for found in MV_HV_PURPOSE.finditer(text):
        previous=text[max(0,found.start()-32):found.start()]
        if re.search(r"\b(?:not|no|without|never|isn't|isnt)\s+"
                     r"(?:(?:used|designed)\s+)?(?:for\s+)?$", previous, re.I):
            continue
        if re.search(r"\b(?:not|no|without|never)\b.{0,16}$",previous,re.I):
            continue
        following=text[found.end():found.end()+28]
        if re.match(r"\s+(?:is\s+)?(?:not|never|absent|missing)\b",following,re.I):
            continue
        return True
    return False


def assess_pole_height(height, note, *, threshold=12.0):
    """Compare raw stored pole height; value/unit not independently calibrated."""
    if height is None or not str(height).strip():
        return "UNRECORDED", None
    try:
        import math
        value=float(height)
        if not math.isfinite(value):
            return "INVALID_NUMERIC", None
    except (ValueError,TypeError):
        return "INVALID_NUMERIC", None
    if value<=threshold:
        return "WITHIN_THRESHOLD", None
    if has_explicit_mv_hv_note(note):
        return "MV_HV_NOTES_DOCUMENTED", None
    return (
        "MV_HV_NOTES_REQUIRED",
        "Pole height > 12: Notes must explicitly identify MV line or HV line/tower use",
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


def missing_pole_field_value(raw, domain=None):
    """Honor coded text zero only when the verified domain defines it.

    This preserves valid Yes/No answers while rejecting Unknown and blank.
    """
    if isinstance(raw, str) and raw.strip() == "0" and domain:
        label = next(
            (v for code, v in domain.items() if str(code).strip() == "0"),
            None,
        )
        return label is None or str(label).strip().casefold() in UNKNOWN
    return missing_value(raw, domain)


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
    if asset=="pole" and not mapping.get("height"):
        missing_checks.append("height_conditional_check")
    if not gid.strip():
        issues.append("GlobalID missing")
    try:
        type_code = int(asset_type)
    except (TypeError, ValueError):
        type_code = -1
    if type_code not in spec["types"]:
        issues.append("Unknown or unsupported asset type")
    available_attrs = {str(key).casefold(): value
                       for key, value in attributes.items()}
    def recorded_location(field):
        return str(available_attrs.get(field.casefold()) or "").strip()

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
        height_field = mapping.get("height")
        if height_field:
            height_status,height_issue=assess_pole_height(attributes.get(height_field),note)
            values["height_status"]=height_status
            if height_status=="INVALID_NUMERIC":
                issues.append("Pole height has an invalid nonnumeric value")
            if height_issue:
                issues.append(height_issue)
        else:
            values["height_status"]="NOT_VERIFIED_FIELD"
        append_field = mapping.get("append_cable")
        if not append_field:
            values["append_cable_status"] = "NOT_VERIFIED_FIELD"
        else:
            raw = attributes.get(append_field)
            coded_domain = (domains or {}).get(append_field, {})
            # ArcGIS may return a coded zero either as integer 0 or as
            # the text "0". A coded "No" is an explicit response, not
            # an incomplete value. An unmapped text zero is not assumed
            # to mean No.
            if isinstance(raw, str) and raw.strip() == "0":
                domain_value = next((label for code, label in coded_domain.items()
                                     if str(code).strip() == "0"), None)
                if domain_value is not None:
                    values["append_cable"] = str(domain_value)
                missing_append = (not domain_value or
                                  str(domain_value).strip().casefold() in UNKNOWN)
            else:
                missing_append = missing_value(raw, coded_domain)
            if missing_append:
                values["append_cable_status"] = "MISSING_OR_UNKNOWN"
                issues.append("Append Cable missing/unknown (mandatory LV pole field)")
            else:
                values["append_cable_status"] = "RECORDED"
        # Additional mandatory template fields for LV poles.
        for key, label in (
            ("service_pole", "Service Pole"),
            ("structure", "Structure"),
            ("insulator_type", "Insulator Type"),
            ("number_of_circuit", "Number of Circuit"),
        ):
            source = mapping.get(key)
            if not source:
                values[key + "_status"] = "NOT_VERIFIED_FIELD"
                continue
            raw = attributes.get(source)
            value_domain = (domains or {}).get(source, {})
            if missing_pole_field_value(raw, value_domain):
                values[key + "_status"] = "MISSING_OR_UNKNOWN"
                issues.append(f"{label} missing/unknown (mandatory LV pole field)")
            elif key == "number_of_circuit":
                try:
                    count = float(raw)
                    valid_count = count.is_integer() and count > 0
                except (TypeError, ValueError, OverflowError):
                    valid_count = False
                if not valid_count:
                    values[key + "_status"] = "INVALID_COUNT"
                    issues.append("Number of Circuit must be a positive whole number")
                else:
                    values[key + "_status"] = "RECORDED"
            else:
                values[key + "_status"] = "RECORDED"
        field = mapping.get("manufacturer")
        if field and missing_value(attributes.get(field), (domains or {}).get(field)):
            if not note:
                values["manufacturer_status"] = "MISSING_MANUFACTURER_NOTES"
                issues.append("Manufacturer missing and Notes empty")
            elif has_explicit_no_nameplate_note(note):
                values["manufacturer_status"] = "DOCUMENTED_NO_NAMEPLATE"
            else:
                values["manufacturer_status"] = "NOTES_PRESENT"
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
        "recorded_district": recorded_location("District"),
        "recorded_sector": recorded_location("Sector"),
        "recorded_cell": recorded_location("Cell"),
        "status": status,
        "issues": issues,
        "unverified_checks": missing_checks,
        "notes": note,
        "values": values,
    }


def annotate_duplicate_asset_globalids(rows):
    """Mark every distinct source OBJECTID in repeated GlobalID groups.

    Keeps the original seven transformer correction checks separately from
    identity-integrity issues. This is scoped to the rows in this run;
    another copy outside the selected area/date/surveyor set may be missed.
    """
    from collections import defaultdict

    grouped = defaultdict(list)
    observed = set()
    for row in rows:
        oid = int(row["objectid"])
        if oid in observed:
            raise RuntimeError(f"Duplicate OBJECTID {oid} in an asset QA result.")
        observed.add(oid)
        row["attribute_gap_before_duplicate_check"] = row["status"] == "GAP"
        row["identifier_issues"] = []
        row["duplicate_peer_objectids"] = []
        raw = str(row.get("globalid") or "").strip().strip("{}").casefold()
        if raw:
            grouped[raw].append(row)
    duplicate_groups = {}
    for normalized, group in grouped.items():
        if len(group) < 2:
            continue
        all_ids = sorted(int(item["objectid"]) for item in group)
        duplicate_groups[normalized] = all_ids
        for row in group:
            other_ids = [oid for oid in all_ids if oid != int(row["objectid"])]
            row["duplicate_peer_objectids"] = other_ids
            issue = ("Duplicate GlobalID: this identifier also belongs to "
                     "OBJECTID(s) " + ", ".join(map(str, other_ids)))
            row["identifier_issues"].append(issue)
            row["issues"].append(issue)
            row["status"] = "GAP"
    return dict(sorted(duplicate_groups.items()))


def asset_duplicate_summary(rows):
    groups = {str(row["globalid"]).strip().strip("{}").casefold()
              for row in rows if row.get("duplicate_peer_objectids")}
    duplicates = sum(bool(row.get("duplicate_peer_objectids")) for row in rows)
    return {
        "duplicate_globalid_groups": len(groups),
        "duplicate_feature_records": duplicates,
        "extra_records_with_reused_globalids": duplicates - len(groups),
    }


def summarize_assets(rows):
    counts = Counter(row["status"] for row in rows)
    return {
        "total": len(rows),
        "with_gaps": counts["GAP"],
        "no_gaps_found": counts["NO_GAPS_FOUND"],
        "not_verified": counts["NOT_VERIFIED"],
        "issue_count": sum(len(row["issues"]) for row in rows),
        # Historic seven-category gap totals remain separable from
        # duplicate GlobalID integrity findings.
        "original_attribute_gap_records": sum(
            row.get("attribute_gap_before_duplicate_check", row["status"] == "GAP")
            for row in rows
        ),
        "original_attribute_issue_count": sum(
            len(row["issues"]) - len(row.get("identifier_issues", []))
            for row in rows
        ),
        **asset_duplicate_summary(rows),
    }
