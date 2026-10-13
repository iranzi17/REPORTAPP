"""Compare LV line transformer labels with verified Utility Network trace membership.

Connected topology is evidence of component membership, not load-flow direction
or the energised supplying transformer. Conservative review statuses never
automatically rewrite transformer names.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence


def normalized_label(value: Any) -> str:
    """Case/whitespace-insensitive, but preserve meaningful punctuation."""
    return " ".join(str(value or "").split()).casefold()


def assess_line_transformer_names(
    lines: Sequence[Mapping[str, Any]],
    transformers: Sequence[Mapping[str, Any]],
    trace_results: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Produce one auditable row per line, with no name-based source assignment.

    Transformer records require OBJECTID, GLOBALID and Transfomer_name_.
    Trace results come from the secondary terminal of each group-12 point.
    Each trace must include the set of connected distribution transformer OIDs
    and LV line OIDs. A trace with multiple transformer sources is ambiguous.

    All transformers present in a trace, including outside the selected
    district, are taken into account in multi-source validation.
    """
    point_by_id = {}
    for point in transformers:
        if int(point["ASSETGROUP"]) != 12:
            raise ValueError("Only distribution transformer asset group 12 is allowed.")
        oid = int(point["OBJECTID"])
        if oid in point_by_id:
            raise ValueError(f"Duplicate transformer OBJECTID {oid}")
        point_by_id[oid] = point
        if oid not in trace_results:
            raise RuntimeError(f"Missing connectivity result for transformer OBJECTID {oid}")
        result = trace_results[oid]
        if oid not in set(result["connected_transformer_objectids"]):
            raise RuntimeError(f"Transformer {oid} is absent from its own trace.")

    membership: dict[int, set[int]] = defaultdict(set)
    ambiguous_lines: set[int] = set()
    trace_warning_lines: set[int] = set()
    for oid, trace in trace_results.items():
        if oid not in point_by_id:
            raise ValueError(f"Unexpected transformer trace source {oid}")
        line_ids = {int(v) for v in trace["line_objectids"]}
        connected_transformers = {int(v) for v in trace["connected_transformer_objectids"]}
        for line_oid in line_ids:
            membership[line_oid].add(oid)
        if len(connected_transformers) != 1:
            ambiguous_lines.update(line_ids)
        if trace.get("warnings"):
            trace_warning_lines.update(line_ids)

    output = []
    encountered = set()
    for line in lines:
        oid = int(line["OBJECTID"])
        gid = str(line.get("GLOBALID") or "").strip()
        if oid in encountered:
            raise ValueError(f"Duplicate LV line OBJECTID {oid}")
        encountered.add(oid)
        actual_label = str(line.get("Transformer_Name") or "").strip()
        candidates = membership.get(oid, set())
        proposed_name = ""
        transformer_globalid = ""
        transformer_objectid = None
        evidence = ""
        if oid in ambiguous_lines or len(candidates) > 1:
            status = "AMBIGUOUS_CONNECTED_SOURCES"
            evidence = "Trace reaches multiple distribution-transformer points; feeder source is not unique."
        elif oid in trace_warning_lines:
            status = "TRACE_WARNING_UNVERIFIED"
            evidence = "Utility Network trace returned warnings; verify network topology before judging the line label."
        elif not candidates:
            status = "SOURCE_UNVERIFIED"
            evidence = "Line is not in a trace from a selected-area transformer; its source may be outside the boundary."
        else:
            transformer_oid = next(iter(candidates))
            transformer = point_by_id[transformer_oid]
            transformer_objectid = transformer_oid
            transformer_globalid = str(transformer.get("GLOBALID") or "")
            proposed_name = str(transformer.get("Transfomer_name_") or "").strip()
            if not proposed_name or normalized_label(proposed_name) in (
                "unknown", "none", "n/a", "<null>", "null", "-",
            ):
                status = "TRANSFORMER_NAME_UNVERIFIED"
                evidence = "Connected transformer itself has an unknown or empty name."
            elif not actual_label or normalized_label(actual_label) in (
                "unknown", "none", "n/a", "<null>", "null", "-",
            ):
                status = "MISSING_LINE_TRANSFORMER_NAME"
                evidence = "A connected transformer has a name; the LV line does not."
            elif normalized_label(actual_label) == normalized_label(proposed_name):
                status = "MATCH"
                evidence = "LV label matches the only distribution-transformer point in connected topology."
            else:
                status = "NAME_MISMATCH_REVIEW"
                evidence = (
                    "LV label differs from the only distribution-transformer point "
                    "in connected topology. Verify switching and energized source "
                    "before correcting."
                )
        output.append({
            "objectid": oid,
            "globalid": gid,
            "username": str(line.get("created_user") or "").strip() or "(unattributed)",
            "line_transformer_name": actual_label,
            "connected_transformer_name": proposed_name,
            "transformer_objectid": transformer_objectid,
            "transformer_globalid": transformer_globalid,
            "candidate_transformer_count": len(candidates),
            "status": status,
            "evidence": evidence,
        })
    return output


def summary_by_surveyor(rows):
    result = defaultdict(Counter)
    for row in rows:
        user = row["username"]
        result[user]["checked"] += 1
        result[user][row["status"]] += 1
    return {
        key: dict(counts) for key, counts in sorted(result.items())
    }
