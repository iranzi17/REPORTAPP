"""Focused LV correction register, separate from the 60% completeness score.

The categories mirror the field-review issues previously agreed with the
surveyors. All other quality checks remain visible in the general QA report.
"""
from __future__ import annotations

from collections import Counter, defaultdict

GAP_CATEGORIES = (
    "Missing phases",
    "Missing transformer name",
    "Voltage not selected",
    "Material unknown/missing",
    "Insulation missing",
    "Phase/type conflicts",
)

RULE_CATEGORY = {
    "phases": "Missing phases",
    "transformer_name": "Missing transformer name",
    "voltage": "Voltage not selected",
    "conductor_material": "Material unknown/missing",
    "conductor_insulation": "Insulation missing",
}


def priority_gaps(quality: dict, phase_conflict: str | None = None) -> list[dict]:
    """Return only our original LV correction categories.

    A failed value/domain check is included under its corresponding gap
    category, with the exact validation issue retained in 'detail'.
    Distinguishing the reason from the summary label avoids losing evidence.
    """
    found = []
    for check in quality.get("checks", []):
        category = RULE_CATEGORY.get(check.get("key"))
        if category and not check.get("valid", False):
            found.append({
                "category": category,
                "detail": str(check.get("issue_detail") or "Missing or invalid"),
            })
    if phase_conflict:
        found.append({"category": "Phase/type conflicts", "detail": str(phase_conflict)})
    return found


def summarize_priority_gaps(results: list[dict]) -> list[dict]:
    """Counts issues and affected lines separately, grouped by creator."""
    by_user: dict[str, dict] = {}
    for result in results:
        username = result.get("username") or "(unattributed)"
        if username not in by_user:
            by_user[username] = {
                "username": username,
                "full_name": result.get("full_name") or username,
                "lines_checked": 0,
                "affected_lines": 0,
                "total_issues": 0,
                **{category: 0 for category in GAP_CATEGORIES},
            }
        item = by_user[username]
        item["lines_checked"] += 1
        issues = result.get("priority_gaps", [])
        if issues:
            item["affected_lines"] += 1
        for issue in issues:
            category = issue["category"]
            if category not in GAP_CATEGORIES:
                raise ValueError(f"Unexpected LV gap category: {category}")
            item[category] += 1
            item["total_issues"] += 1
    return sorted(by_user.values(), key=lambda row: (-row["affected_lines"], row["username"].casefold()))
