"""Topology-aware read-only LV feeder engineering checks.

This module deliberately does NOT derive network topology by proximity,
GlobalID ordering, name matches or connected trace membership. Supply
verified, directed upstream -> downstream edges from authoritative network
connectivity. All findings are REVIEW/INFO, never automatic source edits.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable, Mapping


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _phase_set(value: Any, notation: Any = None) -> frozenset[str] | None:
    """Decode phase identity only when notation is unambiguous.

    'B' is ambiguous: it means phase B in ABC but Blue in RYB. When
    notation is unknown, return None unless explicit A/C or R/Y clarifies.
    """
    if value is None:
        return None
    if isinstance(value, (set, frozenset, list, tuple)):
        raw = [str(item).strip().upper() for item in value]
    else:
        text = str(value).strip().upper()
        raw = list(text) if text.isalpha() and len(text) <= 3 else [
            item for item in re.split(r"[,; /+]+", text) if item
        ]
    system = str(notation or "").strip().upper()
    if system not in ("ABC", "RYB"):
        if any(part in ("R", "Y") for part in raw):
            system = "RYB"
        elif any(part in ("A", "C") for part in raw):
            system = "ABC"
        else:
            return None  # Lone 'B' without a phase convention is ambiguous.
    aliases = {"A": "A", "B": "B", "C": "C"} if system == "ABC" else {
        "R": "A", "Y": "B", "B": "C"
    }
    if not raw or any(part not in aliases for part in raw):
        return None
    return frozenset(aliases[part] for part in raw)


def _id(value: Any) -> str:
    return str(value or "").strip().strip("{}").casefold()


def _finding(
    code: str, status: str, upstream: str, downstream: str,
    detail: str, evidence: str = "verified topology",
) -> dict[str, str]:
    return {
        "code": code,
        "status": status,
        "upstream_globalid": upstream,
        "downstream_globalid": downstream,
        "detail": detail,
        "evidence": evidence,
    }


def audit_lv_feeder(
    sections: Iterable[Mapping[str, Any]],
    directed_links: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Audit explicitly directed LV paths and protection data.

    Each section has a unique 'globalid'; optional attributes:
      phase_count (1,2,3), phase_set (A/B/C or R/Y/B),
      phase_notation (ABC or RYB when phase identity is ambiguous),
      nominal_voltage_v, voltage_basis ('LL' or 'LN'),
      rated_current_a (conductor ampacity in amperes, not load current),
      conductor_size, conductor_material,
      design_current_a, protective_setting_a, adjusted_ampacity_a.

    Rated ampacity may be a catalogue/reference-condition rating or already
    installation-adjusted: that provenance must be established separately.
    Only adjusted_ampacity_a is treated as verified design Iz.

    Each link has upstream_globalid, downstream_globalid and
    topology_verified=True. Optional:
      new_source_verified, conversion_device_verified.
    Linking via geometry alone is NOT an authoritative verification.

    This does not calculate voltage drop, branch load flow, ampacity, or
    short-circuit performance from insufficient survey attributes.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    for section in sections:
        identity = _id(section.get("globalid"))
        if not identity:
            raise ValueError("All feeder sections need a GlobalID")
        if identity in by_id:
            raise ValueError(f"Duplicate GlobalID in feeder sections: {identity}")
        by_id[identity] = section

    findings: list[dict[str, str]] = []
    evaluated_links = 0
    skipped_links = 0
    all_links = list(directed_links)
    incoming = Counter(_id(link.get("downstream_globalid")) for link in all_links
                       if link.get("topology_verified") is True)
    for link in all_links:
        upstream = _id(link.get("upstream_globalid"))
        downstream = _id(link.get("downstream_globalid"))
        if not upstream or not downstream or upstream == downstream:
            raise ValueError("Each link needs two different section GlobalIDs")
        if upstream not in by_id or downstream not in by_id:
            # Partial export cannot prove feeder order or support a change claim.
            skipped_links += 1
            continue
        if link.get("topology_verified") is not True or incoming[downstream] > 1:
            # Do not assert feeder orientation in loops / multi-supply junctions.
            skipped_links += 1
            continue
        evaluated_links += 1
        parent, child = by_id[upstream], by_id[downstream]
        if link.get("new_source_verified") is True or link.get("conversion_device_verified") is True:
            findings.append(_finding(
                "SOURCE_OR_CONVERSION_BOUNDARY", "INFO", upstream, downstream,
                "New supply/conversion equipment is verified; do not apply continuity assumptions.",
            ))
            continue

        parent_count = _number(parent.get("phase_count"))
        child_count = _number(child.get("phase_count"))
        reappeared = False
        if (parent_count in (1, 2, 3) and child_count in (1, 2, 3)
                and child_count > parent_count):
            findings.append(_finding(
                "PHASES_REAPPEAR_DOWNSTREAM", "REVIEW", upstream, downstream,
                f"Downstream records {int(child_count)} phases after {int(parent_count)}; "
                "verify phases and any independent supply.",
            ))
            reappeared = True

        parent_set = _phase_set(parent.get("phase_set"), parent.get("phase_notation"))
        child_set = _phase_set(child.get("phase_set"), child.get("phase_notation"))
        if parent_set is not None and child_set is not None and not child_set.issubset(parent_set):
            findings.append(_finding(
                "PHASE_IDENTITY_MISMATCH", "REVIEW", upstream, downstream,
                "Downstream phases include conductors not recorded upstream; "
                "verify phase identity and connections.",
            ))

        p_voltage = _number(parent.get("nominal_voltage_v"))
        c_voltage = _number(child.get("nominal_voltage_v"))
        p_basis = str(parent.get("voltage_basis") or "").strip().upper()
        c_basis = str(child.get("voltage_basis") or "").strip().upper()
        if (not reappeared and p_voltage and c_voltage and p_basis in ("LL", "LN")
                and p_basis == c_basis and abs(p_voltage-c_voltage) > 1.0):
            findings.append(_finding(
                "NOMINAL_VOLTAGE_TRANSITION", "REVIEW", upstream, downstream,
                f"Nominal {p_basis} voltage changes from {p_voltage:g} V to "
                f"{c_voltage:g} V with no verified conversion device.",
            ))
        # A 400-V LL three-phase trunk feeding a 230-V LN single-phase tap
        # is not a voltage transformation and is intentionally NOT flagged.
        # A 400-V LL trunk feeding a 400-V LL single-phase (two-phase wires)
        # may also be legitimate; no simplistic voltage-vs-phase rule.

        p_size = str(parent.get("conductor_size") or "").strip()
        c_size = str(child.get("conductor_size") or "").strip()
        if p_size and c_size and p_size.casefold() != c_size.casefold():
            findings.append(_finding(
                "CONDUCTOR_SIZE_CHANGED", "INFO", upstream, downstream,
                f"Conductor configuration changes {p_size} -> {c_size}; "
                "not an error without design and protection checks.",
            ))

        p_rating = _number(parent.get("rated_current_a"))
        c_rating = _number(child.get("rated_current_a"))
        if p_rating is not None and c_rating is not None and p_rating > 0 and c_rating > 0 and abs(p_rating-c_rating) > 1e-9:
            findings.append(_finding(
                "CONDUCTOR_AMPACITY_CHANGED", "INFO", upstream, downstream,
                f"Recorded conductor current-carrying capacity changes "
                f"{p_rating:g} A -> {c_rating:g} A; this is not measured "
                "load current and is not inherently a defect.",
            ))

    # Protection/thermal checks are independent of edge direction.
    for gid, section in by_id.items():
        ib = _number(section.get("design_current_a"))
        inn = _number(section.get("protective_setting_a"))
        iz = _number(section.get("adjusted_ampacity_a"))
        recorded_ampacity = _number(section.get("rated_current_a"))
        if recorded_ampacity is not None and recorded_ampacity <= 0:
            findings.append(_finding(
                "INVALID_CONDUCTOR_AMPACITY", "REVIEW", gid, gid,
                f"Conductor Rated_Current is {recorded_ampacity:g} A; "
                "capacity must be positive.",
                evidence="recorded conductor-ampacity field",
            ))
        if ib is not None and iz is not None and ib > iz:
            findings.append(_finding(
                "DESIGN_LOAD_EXCEEDS_ADJUSTED_AMPACITY", "REVIEW", gid, gid,
                f"Design current {ib:g} A exceeds independently verified "
                f"installation-adjusted ampacity {iz:g} A.",
                evidence="provided design/load and adjusted-ampacity data",
            ))
        if (ib is not None and recorded_ampacity is not None
                and recorded_ampacity > 0 and ib > recorded_ampacity and iz is None):
            findings.append(_finding(
                "DESIGN_LOAD_EXCEEDS_RECORDED_AMPACITY", "REVIEW", gid, gid,
                f"Design current {ib:g} A exceeds recorded conductor capacity "
                f"{recorded_ampacity:g} A; verify whether Rated_Current is "
                "reference-condition or installation-adjusted ampacity.",
                evidence="recorded capacity and provided design current; Iz unavailable",
            ))
        if ib is not None and inn is not None and ib > inn:
            findings.append(_finding(
                "LOAD_EXCEEDS_PROTECTION_SETTING", "REVIEW", gid, gid,
                f"Design load {ib:g} A exceeds protective setting {inn:g} A.",
                evidence="provided design/protection data",
            ))
        if inn is not None and iz is not None and inn > iz:
            findings.append(_finding(
                "PROTECTION_EXCEEDS_DERATED_AMPACITY", "REVIEW", gid, gid,
                f"Protective setting {inn:g} A exceeds adjusted ampacity {iz:g} A; "
                "check protection method and applicable exceptions.",
                evidence="provided protection/ampacity data",
            ))
    counts = Counter(item["status"] for item in findings)
    return {
        "sections_checked": len(by_id),
        "links_provided": len(all_links),
        "links_evaluated": evaluated_links,
        "links_not_verified_or_incomplete": skipped_links,
        "review_findings": counts["REVIEW"],
        "informational_findings": counts["INFO"],
        "findings": findings,
        "limitations": (
            "Rated_Current is conductor current-carrying capacity, NOT flowing current. "
            "Overload checks need design current and verified installation-adjusted "
            "ampacity. Directional checks need authoritative LV topology and voltage "
            "reference basis. No connection inferred from map proximity. "
            "No automatic corrections."
        ),
    }
