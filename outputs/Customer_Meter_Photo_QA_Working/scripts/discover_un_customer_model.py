"""Read-only discovery of customer, meter, and attachment schema in the UN service."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from arcgis.features import FeatureLayer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

OUTPUT = PROJECT_ROOT / "outputs" / "un_customer_model_discovery.json"
KEYWORDS = ("customer", "meter", "service", "serial", "photo", "image", "attachment")


def value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def relevant(text: Any) -> bool:
    normalized = str(text or "").lower()
    return any(keyword in normalized for keyword in KEYWORDS)


def subtype_rows(properties: Any) -> list[dict[str, Any]]:
    rows = []
    for asset_group in value(properties, "types", []) or []:
        group_id = value(asset_group, "id")
        group_name = value(asset_group, "name")
        domains = value(asset_group, "domains", {}) or {}
        asset_type_domain = value(domains, "ASSETTYPE", {}) or {}
        for coded in value(asset_type_domain, "codedValues", []) or []:
            row = {
                "asset_group": group_id,
                "asset_group_name": group_name,
                "asset_type": value(coded, "code"),
                "asset_type_name": value(coded, "name"),
            }
            if relevant(group_name) or relevant(row["asset_type_name"]):
                rows.append(row)
    return rows


def attachment_count(layer: FeatureLayer, where: str) -> dict[str, Any]:
    feature_count = int(layer.query(
        where=where,
        return_count_only=True,
        gdb_version="sde.DEFAULT",
    ))
    rows = [] if feature_count == 0 else (layer.attachments.search(
        where=where, max_records=2000, return_url=False
    ) or [])
    parent_ids = {row.get("PARENTOBJECTID") for row in rows}
    image_rows = [row for row in rows if str(row.get("CONTENTTYPE", "")).lower().startswith("image/")]
    return {
        "feature_count": feature_count,
        "features_inspected_for_attachments": feature_count,
        "features_with_attachments": len(parent_ids),
        "attachment_count": len(rows),
        "image_attachment_count": len(image_rows),
        "attachment_result_limit": 2000,
        "sample_attachment_metadata": [
            {
                "object_id": row.get("PARENTOBJECTID"),
                "attachment_id": row.get("ID"),
                "name": row.get("NAME"),
                "content_type": row.get("CONTENTTYPE"),
                "size": row.get("SIZE"),
            }
            for row in rows[:5]
        ],
    }


def main() -> None:
    import server

    gis = server.get_gis()
    service = server.get_flc()
    inspect_attachments = "--attachments" in sys.argv
    candidates = []
    layer_summaries = []
    for item in list(service.layers) + list(service.tables):
        layer = FeatureLayer(item.url, gis)
        props = layer.properties
        fields = []
        for field in value(props, "fields", []) or []:
            name = value(field, "name")
            alias = value(field, "alias")
            if relevant(name) or relevant(alias):
                fields.append({
                    "name": name,
                    "alias": alias,
                    "type": value(field, "type"),
                    "nullable": value(field, "nullable"),
                    "length": value(field, "length"),
                    "domain": value(value(field, "domain", {}) or {}, "name"),
                })
        subtypes = subtype_rows(props)
        has_attachments = bool(value(props, "hasAttachments", False))
        if fields or subtypes or has_attachments:
            summary = {
                "layer_id": value(props, "id"),
                "layer_name": value(props, "name"),
                "geometry_type": value(props, "geometryType"),
                "has_attachments": has_attachments,
                "global_id_field": value(props, "globalIdField"),
                "object_id_field": value(props, "objectIdField"),
                "relevant_fields": fields,
                "relevant_subtypes": subtypes,
            }
            layer_summaries.append(summary)
            for subtype in subtypes:
                where = f"ASSETGROUP = {int(subtype['asset_group'])} AND ASSETTYPE = {int(subtype['asset_type'])}"
                inventory = attachment_count(layer, where) if has_attachments and inspect_attachments else {
                    "feature_count": None,
                    "note": "Schema-only run; pass --attachments for live counts",
                }
                candidates.append({
                    **summary,
                    **subtype,
                    "where": where,
                    "inventory": inventory,
                })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "service_url": os.environ.get("UN_SERVICE_URL"),
        "version": "sde.DEFAULT",
        "read_only": True,
        "attachment_inventory_enabled": inspect_attachments,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "layers_with_relevant_schema": layer_summaries,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "candidate_count": len(candidates),
        "candidates": [
            {
                "layer_id": row["layer_id"],
                "layer_name": row["layer_name"],
                "asset_group": row["asset_group"],
                "asset_group_name": row["asset_group_name"],
                "asset_type": row["asset_type"],
                "asset_type_name": row["asset_type_name"],
                "feature_count": row["inventory"].get("feature_count"),
                "image_attachment_count": row["inventory"].get("image_attachment_count"),
            }
            for row in candidates
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
