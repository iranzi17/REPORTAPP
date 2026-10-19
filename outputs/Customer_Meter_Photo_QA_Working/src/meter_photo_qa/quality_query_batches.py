"""Reliable, read-only retrieval of feature attributes from ArcGIS FeatureServer.

Spatially expensive searches return OBJECTIDs only. Attribute data is then
fetched in bounded batches by indexed OBJECTID. The same feature may touch
multiple selected sector polygons; it is counted exactly once.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable
import time


def _objectids_from_query(response: Any, area: str) -> list[int] | None:
    """Parse ArcGIS returnIdsOnly response.

    ArcGIS Server may send objectIds:null or omit objectIds entirely
    for a spatial query with ZERO matches. Those cases require a separate
    count verification before being treated as empty; None is the sentinel
    for "count verification required", never an implicit pass.
    """
    if not isinstance(response, dict):
        raise RuntimeError(
            f"{area}: the service did not return an ObjectID dictionary; "
            "cannot safely confirm all features were retrieved."
        )
    if response.get("error"):
        raise RuntimeError(f"{area}: ObjectID query failed: {response['error']}")
    ids = response.get("objectIds")
    if ids is None:
        return None
    if not isinstance(ids, (tuple, list)):
        raise RuntimeError(
            f"{area}: the service returned invalid objectIds ({type(ids).__name__})."
        )
    try:
        return sorted({int(oid) for oid in ids})
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{area}: the query returned invalid ObjectIDs.") from exc


def _confirm_empty_id_response(layer, query_fn, options, area):
    """Treat null/absent objectIds as empty only if a matching count is zero."""
    count_options = dict(options)
    count_options.pop("return_ids_only", None)
    count_options["return_count_only"] = True
    try:
        count_response = query_fn(layer, attempts=2, **count_options)
        # FeatureLayer.query(return_count_only=True) returns an integer;
        # a raw REST-like {'count': 0} response is also acceptable.
        if isinstance(count_response, dict):
            if count_response.get("error"):
                raise RuntimeError(str(count_response["error"]))
            if "count" not in count_response:
                raise RuntimeError("missing 'count' in count-only response")
            count_response = count_response["count"]
        if isinstance(count_response, bool):
            raise ValueError("boolean count response")
        count = int(count_response)
        if count < 0 or (isinstance(count_response, float) and count_response != count):
            raise ValueError(f"invalid count {count_response!r}")
    except Exception as exc:
        raise RuntimeError(
            f"{area}: the service omitted/nullified objectIds and a "
            f"count-only verification failed ({exc}). "
            "Cannot safely skip this area."
        ) from exc
    if count != 0:
        raise RuntimeError(
            f"{area}: the service omitted/nullified objectIds although the "
            f"matching count is {count}. Refusing to omit these records."
        )
    return []



def _query_with_default_version_recheck(
    layer: Any,
    query_fn: Callable[..., Any],
    *,
    attempts: int,
    area: str,
    progress: Callable[[str], None] | None,
    **query_options: Any,
) -> Any:
    """One delayed recheck for a transient failure resolving sde.DEFAULT.

    ArcGIS Server can intermittently fail to resolve its default version on
    particular instances. Preserve the explicitly selected gdb_version and
    all original query arguments, including polygon, WHERE, and ObjectIDs.
    Do not silently query the published map version; it may differ.
    """
    try:
        return query_fn(layer, attempts=attempts, **query_options)
    except Exception as exc:
        detail = str(exc).casefold()
        if (
            str(query_options.get("gdb_version") or "").casefold() != "sde.default"
            or "failed to find version" not in detail
            or "sde.default" not in detail
        ):
            raise
        if progress:
            progress(
                f"{area}: REG service could not resolve sde.DEFAULT; "
                "waiting 8 seconds for one final read-only retry "
                "(source version unchanged)."
            )
        time.sleep(8)
        # One additional request only. If the version is still unavailable,
        # propagate the original fail-closed reporting logic.
        return query_fn(layer, attempts=1, **query_options)

def query_attributes_in_batches(
    layer: Any,
    where: str,
    version: str,
    fields: list[str],
    geometry_filters: Iterable[tuple[str, Any]],
    query_fn: Callable[..., Any],
    batch_size: int = 150,
    progress: Callable[[str], None] | None = None,
    asset_label: str = "LV line",
    duplicate_globalid_policy: str = "error",
) -> list[dict[str, Any]]:
    """Retrieve all matches or fail; never issue partial 'clean' reports.

    geometry_filters contains tuples (human-readable area, geometry filter).
    For a national run pass [('All areas', None)].
    """
    if batch_size < 1:
        raise ValueError("Batch size must be positive.")
    if duplicate_globalid_policy not in ("error", "report"):
        raise ValueError("duplicate_globalid_policy must be error or report.")
    spatial_filters = list(geometry_filters)
    if not spatial_filters:
        raise ValueError("No boundary polygons were provided for the selected area.")
    def safe_query(target: Any, *, attempts: int = 2, **options: Any) -> Any:
        return _query_with_default_version_recheck(
            target,
            query_fn,
            attempts=attempts,
            area=asset_label,
            progress=progress,
            **options,
        )

    unique_ids: set[int] = set()
    for index, (area, spatial_filter) in enumerate(spatial_filters, 1):
        opts = {
            "where": where,
            "return_ids_only": True,
            "return_geometry": False,
            "gdb_version": version,
        }
        if spatial_filter is not None:
            opts["geometry_filter"] = spatial_filter
        try:
            response = safe_query(layer, attempts=2, **opts)
            ids = _objectids_from_query(response, area)
            if ids is None:
                ids = _confirm_empty_id_response(
                    layer, safe_query, opts, area,
                )
                if progress:
                    progress(
                        f"{asset_label}: no matching features in {area} "
                        "(confirmed by server count = 0); continuing."
                    )
        except Exception as exc:
            raise RuntimeError(
                f"Could not list {asset_label} ObjectIDs for {area} (area "
                f"{index}/{len(spatial_filters)}). The report was NOT generated; "
                f"there are no reliable counts until all areas succeed. "
                f"ArcGIS Server error: {exc}"
            ) from exc
        unique_ids.update(ids)
        if progress and (index == 1 or index == len(spatial_filters) or index % 10 == 0):
            progress(
                f"{asset_label} boundary {index}/{len(spatial_filters)}: "
                f"{len(unique_ids)} unique ObjectIDs identified."
            )

    sorted_ids = sorted(unique_ids)
    if not sorted_ids:
        return []

    max_records = getattr(getattr(layer, "properties", None), "maxRecordCount", None)
    if max_records is None and isinstance(getattr(layer, "properties", None), dict):
        max_records = layer.properties.get("maxRecordCount")
    try:
        safe_batch_size = min(batch_size, int(max_records)) if max_records else batch_size
    except (TypeError, ValueError):
        safe_batch_size = batch_size
    safe_batch_size = max(1, safe_batch_size)

    collected: dict[int, dict[str, Any]] = {}
    gid_to_oid: dict[str, int] = {}
    for offset in range(0, len(sorted_ids), safe_batch_size):
        batch = sorted_ids[offset: offset + safe_batch_size]
        try:
            feature_set = safe_query(
                layer,
                attempts=2,
                where="1=1",
                object_ids=",".join(str(oid) for oid in batch),
                out_fields=",".join(fields),
                return_geometry=False,
                return_all_records=False,
                gdb_version=version,
            )
        except Exception as exc:
            raise RuntimeError(
                f"{asset_label} attribute batch {offset // safe_batch_size + 1} failed "
                f"({len(collected)}/{len(sorted_ids)} records fetched). "
                f"No partial report was generated. ArcGIS Server error: {exc}"
            ) from exc
        if not hasattr(feature_set, "features"):
            raise RuntimeError("ArcGIS Server returned an invalid attribute batch.")
        if getattr(feature_set, "exceeded_transfer_limit", False):
            raise RuntimeError("ArcGIS Server exceeded the transfer limit in a bounded batch.")
        for feature in feature_set.features:
            attrs = dict(feature.attributes)
            if attrs.get("OBJECTID") is None:
                raise RuntimeError("ArcGIS Server returned a feature without OBJECTID.")
            oid = int(attrs["OBJECTID"])
            if oid not in batch:
                raise RuntimeError(f"Unexpected ObjectID {oid} returned in attribute batch.")
            if oid in collected:
                raise RuntimeError(f"ArcGIS Server returned ObjectID {oid} more than once.")
            gid = str(attrs.get("GLOBALID") or "").strip().strip("{}").casefold()
            if gid:
                previous = gid_to_oid.get(gid)
                if previous is not None and previous != oid:
                    if duplicate_globalid_policy == "error":
                        raise RuntimeError(
                            f"Duplicate GlobalID {gid} belongs to two different OBJECTIDs: "
                            f"{previous} and {oid}. Correct source data before reporting."
                        )
                    if progress:
                        progress(
                            f"DATA INTEGRITY WARNING: duplicate {asset_label} GlobalID "
                            f"{gid}: OBJECTIDs {previous} and {oid}. "
                            "Both records retained for QA and Excel duplicate register."
                        )
                else:
                    gid_to_oid[gid] = oid
            collected[oid] = attrs
        missing = set(batch) - collected.keys()
        if missing:
            raise RuntimeError(
                f"The service omitted {len(missing)} requested {asset_label} features from "
                f"an attribute batch. Report cancelled to avoid incomplete results."
            )
        if progress and (offset == 0 or offset + safe_batch_size >= len(sorted_ids)
                         or (offset // safe_batch_size + 1) % 20 == 0):
            progress(f"Loaded {len(collected)}/{len(sorted_ids)} {asset_label} attributes.")
    return [collected[oid] for oid in sorted_ids]
