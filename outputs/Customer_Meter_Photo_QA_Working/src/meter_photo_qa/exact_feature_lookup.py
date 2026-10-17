"""Strict read-only feature lookup based on Substations-Data-Assistant.

Standalone staging module: NOT wired to live notifications or navigation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Mapping
import math
import uuid


class ExactFeatureMismatch(RuntimeError):
    """The queried source cannot be proven to be the notified feature."""


def _globalid(value):
    try:
        return str(uuid.UUID(str(value).strip().strip("{}"))).lower()
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Expected a valid GlobalID.") from exc


def _objectid(value):
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError("Expected a positive OBJECTID.")
    oid = int(value)
    if not 0 < oid <= 9223372036854775807:
        raise ValueError("OBJECTID outside supported range.")
    return oid


def _value(attrs, name):
    return next((v for k, v in attrs.items()
                 if isinstance(k, str) and k.casefold() == name.casefold()), None)


def _milliseconds(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)) and math.isfinite(value):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def resolve_exact_feature(layer, *, globalid, objectid, gdb_version="sde.DEFAULT",
                          event_time_utc_ms=None, actor=None):
    """Return precisely the notified feature; fail closed on any mismatch.

    Uses ArcGIS FeatureLayer.query without updating, selecting or zooming.
    The source version is explicit. Never fall back to a recent creator result.
    If event_time_utc_ms is supplied, the source editor must also be supplied.
    """
    gid = _globalid(globalid)
    oid = _objectid(objectid)
    if str(gdb_version).strip().casefold() != "sde.default":
        raise ValueError("Requires the verified sde.DEFAULT source version.")
    if (event_time_utc_ms is None) != (actor is None):
        raise ValueError("Event timestamp/editor must be supplied together.")
    event = None
    if event_time_utc_ms is not None:
        event = _milliseconds(event_time_utc_ms)
        if event is None or not 946684800000 <= event <= 4102444800000:
            raise ValueError("Invalid source event timestamp.")
        if not str(actor).strip():
            raise ValueError("Source editor cannot be empty.")
    # Parse and reconstruct GUID; no arbitrary SQL from user input.
    result = layer.query(
        where=f"GlobalID='{{{gid}}}'",
        out_fields="OBJECTID,GLOBALID,created_date,created_user,last_edited_date,last_edited_user",
        return_geometry=False, gdb_version="sde.DEFAULT",
        result_record_count=2,
    )
    found = getattr(result, "features", None)
    if found is None and isinstance(result, Mapping):
        found = result.get("features")
    if not isinstance(found, (list, tuple)) or len(found) != 1:
        raise ExactFeatureMismatch("Exact GlobalID query did not return one feature.")
    feature = found[0]
    attrs = feature.get("attributes", feature) if isinstance(feature, Mapping) else getattr(feature, "attributes", None)
    if not isinstance(attrs, Mapping):
        raise ExactFeatureMismatch("ArcGIS returned no feature attributes.")
    try:
        exact = (_globalid(_value(attrs, "GLOBALID")) == gid
                 and _objectid(_value(attrs, "OBJECTID")) == oid)
    except ValueError as exc:
        raise ExactFeatureMismatch("Source feature identity is incomplete.") from exc
    if not exact:
        raise ExactFeatureMismatch("Source GlobalID/OBJECTID is not the notified feature.")
    if event is not None:
        created = _milliseconds(_value(attrs, "created_date"))
        edited = _milliseconds(_value(attrs, "last_edited_date"))
        if created is None and edited is None:
            raise ExactFeatureMismatch("No source editor timestamp available.")
        last_time = max(x for x in (created, edited) if x is not None)
        last_actor = (_value(attrs, "last_edited_user")
                      if edited is not None and (created is None or edited > created)
                      else _value(attrs, "created_user"))
        if abs(event - last_time) > 2000 or (
            str(actor).strip().casefold() != str(last_actor or "").strip().casefold()
        ):
            raise ExactFeatureMismatch(
                "Different source event time/editor; do not navigate.")
    return feature
