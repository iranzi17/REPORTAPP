"""Read-only ArcGIS inventory for LV service-meter photo readiness."""

from __future__ import annotations

import csv
import io
import logging
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .quality import evaluate_record
from .ocr.core import get_ocr_processor


DEFAULT_SERVICE_URL = "https://gisweb.reg.rw/server/rest/services/REG_UN_Service__/FeatureServer"


def run_inventory(
    output_csv: str | Path,
    limit: int = 500,
    extra_where: str = "1=1",
    service_url: str | None = None,
    ocr_engine: str = "tesseract",
) -> dict[str, Any]:
    from arcgis.features import FeatureLayer
    from arcgis.gis import GIS

    service_url = (service_url or os.environ.get("UN_SERVICE_URL") or DEFAULT_SERVICE_URL).rstrip("/")
    layer = FeatureLayer(f"{service_url}/22", GIS("pro"))
    service_point_layer = FeatureLayer(f"{service_url}/7", layer._gis)
    subtype_where = "ASSETGROUP = 3 AND ASSETTYPE = 1"
    where = f"({subtype_where}) AND ({extra_where or '1=1'})"
    feature_set = None
    last_error = None
    for attempt in range(1, 4):
        try:
            feature_set = layer.query(
                where=where,
                out_fields="OBJECTID,GLOBALID,MeterNumber,ParentGlobaliD,last_edited_date",
                return_geometry=False,
                gdb_version="sde.DEFAULT",
                result_record_count=max(1, int(limit)),
                return_all_records=False,
            )
            break
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(5 * attempt)
    if feature_set is None:
        raise RuntimeError(f"Meter-record query failed after three attempts: {last_error}")
    features = list(feature_set.features)
    object_ids = [str(feature.attributes["OBJECTID"]) for feature in features]
    attachment_rows = []
    if object_ids:
        attachment_rows = layer.attachments.search(
            object_ids=",".join(object_ids),
            max_records=max(100, len(object_ids) * 5),
            return_url=False,
        ) or []
    attachments_by_oid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in attachment_rows:
        attachments_by_oid[int(row["PARENTOBJECTID"])].append(row)

    parent_globalids = sorted({
        str(feature.attributes.get("ParentGlobaliD"))
        for feature in features
        if feature.attributes.get("ParentGlobaliD")
    })
    service_point_by_gid: dict[str, dict[str, Any]] = {}
    if parent_globalids:
        quoted = ",".join(f"'{global_id}'" for global_id in parent_globalids)
        parent_set = service_point_layer.query(
            where=f"GLOBALID IN ({quoted})",
            out_fields="OBJECTID,GLOBALID",
            return_geometry=False,
            gdb_version="sde.DEFAULT",
            result_record_count=len(parent_globalids),
            return_all_records=False,
        )
        service_point_by_gid = {
            str(feature.attributes["GLOBALID"]).upper(): dict(feature.attributes)
            for feature in parent_set.features
        }
    parent_object_ids = [str(row["OBJECTID"]) for row in service_point_by_gid.values()]
    service_point_attachment_rows = []
    if parent_object_ids:
        service_point_attachment_rows = service_point_layer.attachments.search(
            object_ids=",".join(parent_object_ids),
            max_records=max(100, len(parent_object_ids) * 5),
            return_url=False,
        ) or []
    service_point_attachments_by_oid: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in service_point_attachment_rows:
        service_point_attachments_by_oid[int(row["PARENTOBJECTID"])].append(row)

    # Initialize OCR processor
    logger = logging.getLogger(__name__)
    try:
        ocr_processor = get_ocr_processor(ocr_engine)
        logger.info(f"OCR processor initialized: {ocr_processor.__class__.__name__}")
    except RuntimeError as e:
        logger.warning(f"OCR initialization failed: {e}. Proceeding without OCR.")
        ocr_processor = None

    output_rows = []
    statuses = Counter()
    for feature in features:
        attrs = feature.attributes
        oid = int(attrs["OBJECTID"])
        attachments = attachments_by_oid.get(oid, [])
        parent_gid = str(attrs.get("ParentGlobaliD") or "").upper()
        parent = service_point_by_gid.get(parent_gid, {})
        service_point_attachments = service_point_attachments_by_oid.get(int(parent.get("OBJECTID", -1)), [])
        meter_images = [row for row in attachments if str(row.get("CONTENTTYPE", "")).lower().startswith("image/")]
        service_point_images = [
            row for row in service_point_attachments
            if str(row.get("CONTENTTYPE", "")).lower().startswith("image/")
        ]
        images = meter_images + service_point_images
        attachment_location = (
            "BOTH" if meter_images and service_point_images else
            "METER_OBJECT" if meter_images else
            "SERVICE_POINT" if service_point_images else
            "NONE"
        )
        
        # Process OCR if we have images and an OCR processor
        detected_meter_number = None
        ocr_confidence = None
        if images and ocr_processor is not None:
            # Process the first image found (could be enhanced to process all images)
            image_row = images[0]  # Take the first image
            try:
                image_data = image_row.get("DATA")
                if image_data:
                    detected_text, confidence = ocr_processor.extract_text(image_data)
                    if detected_text:
                        detected_meter_number = detected_text
                        ocr_confidence = confidence
                        logger.debug(f"OCR detected: '{detected_text}' with confidence {confidence:.2f}")
                    else:
                        logger.debug("OCR did not detect any text")
                else:
                    logger.warning("Image DATA is empty or missing")
            except Exception as e:
                logger.error(f"Error processing image for OCR: {e}")
        
        result = evaluate_record(
            attrs.get("MeterNumber"), 
            len(images),
            detected_meter_number,
            ocr_confidence
        )
        statuses[result.status] += 1
        output_rows.append({
            "OBJECTID": oid,
            "GLOBALID": attrs.get("GLOBALID"),
            "ParentGlobaliD": attrs.get("ParentGlobaliD"),
            "MeterNumber": attrs.get("MeterNumber"),
            "MeterNumberNormalized": result.entered_normalized,
            "MeterObjectAttachmentCount": len(attachments),
            "ServicePointAttachmentCount": len(service_point_attachments),
            "ImageAttachmentCount": len(images),
            "ImageAttachmentLocation": attachment_location,
            "PreflightStatus": result.status,
            "PreflightReason": result.reason,
            "LastEditedDate": attrs.get("last_edited_date"),
            "OCRDetectedNumber": detected_meter_number or "",
            "OCRConfidence": ocr_confidence if ocr_confidence is not None else 0.0,
        })

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(output_rows[0]) if output_rows else [
        "OBJECTID", "GLOBALID", "ParentGlobaliD", "MeterNumber", "MeterNumberNormalized",
        "MeterObjectAttachmentCount", "ServicePointAttachmentCount", "ImageAttachmentCount",
        "ImageAttachmentLocation", "PreflightStatus", "PreflightReason", "LastEditedDate",
        "OCRDetectedNumber", "OCRConfidence",
    ]
    with output_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)
    return {
        "read_only": True,
        "service_url": service_url,
        "layer_id": 22,
        "where": where,
        "records_scanned": len(output_rows),
        "meter_object_attachment_records_found": len(attachment_rows),
        "service_point_attachment_records_found": len(service_point_attachment_rows),
        "status_counts": dict(statuses),
        "output_csv": str(output_path.resolve()),
    }
