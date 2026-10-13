"""Conservative phase/asset-type consistency checks for LV lines.

No asset-type code is assumed: expectations must be supplied from verified
utility-network subtype definitions. Unmapped cases are not flagged.
"""
from __future__ import annotations


def phase_type_conflict(attributes, phase_domain, expectations):
    """Return an issue or None.

    expectations: mapping of "ASSETGROUP:ASSETTYPE" to phase count (1 or 3).
    phase_domain: mapping of stored phase code to displayed label (e.g. {0:"1", 2:"3"}).
    """
    group = attributes.get("ASSETGROUP")
    asset_type = attributes.get("ASSETTYPE")
    expected = expectations.get(f"{group}:{asset_type}")
    if expected is None:
        return None
    if expected not in (1, 3):
        raise ValueError("Configured expected phase count must be 1 or 3")
    raw = attributes.get("Phases")
    if raw is None or str(raw).strip() == "":
        return None  # Missing phases are checked separately.
    label = phase_domain.get(raw)
    if label is None:
        return None  # Unrecognized code is handled by the domain validator.
    normalized = str(label).strip().casefold()
    recognized = {"1": 1, "1 phase": 1, "single phase": 1,
                  "3": 3, "3 phases": 3, "three phase": 3, "three phases": 3}
    actual = recognized.get(normalized)
    if actual is None:
        return None  # Do not infer from unknown domain labels.
    if actual != expected:
        return f"Phase/type conflict: asset type expects {expected} phase(s), recorded {actual}"
    return None
