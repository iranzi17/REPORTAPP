"""Gicumbi Pamela team: one read-only multi-asset QA profile.

Official assignment source: "Detailed plan for Gicumbi district revised 1(1).xlsx".
Senior Supervisor Pamela, direct field Supervisor Derrick. Team names are
verified against existing report_user_names.json; any unverified person is
kept on the roster and never assigned an invented portal username.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .progress_report import _as_date
from .asset_quality_runner import run_asset_quality
from .quality_watcher import run_quality_watcher

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"
PROFILE_PATH = CONFIG_ROOT / "gicumbi_pamela_team.json"
USER_NAMES_PATH = CONFIG_ROOT / "report_user_names.json"
ASSETS = ("pole", "transformer", "lv_line")
SCOPE_OPTIONS = ("team_only", "all_in_assigned_sectors")
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{3,80}$")


def load_pamela_profile(path: str | Path | None = None, user_map_path: str | Path | None = None):
    """Fail closed if profile roster drifts from the known portal-name mapping."""
    profile = json.loads(Path(path or PROFILE_PATH).read_text(encoding="utf-8"))
    names = json.loads(Path(user_map_path or USER_NAMES_PATH).read_text(encoding="utf-8"))
    if profile.get("district") != "Gicumbi" or profile.get("senior_supervisor") != "Pamela":
        raise ValueError("Unexpected district/senior supervisor in Pamela profile.")
    if profile.get("field_supervisor") != "Derrick":
        raise ValueError("Pamela profile field-supervisor reference has changed.")
    expected = {"Muko", "Mutete", "Nyamiyaga", "Nyankenke", "Rukomo", "Rushaki"}
    actual = {str(sector["sector"]) for sector in profile["sectors"]}
    if actual != expected or len(profile["sectors"]) != len(expected):
        raise ValueError("Pamela work-plan sectors differ from verified source.")
    mapped, unresolved, all_people, all_cells = [], [], set(), set()
    for sector in profile["sectors"]:
        if not sector["cells"] or not isinstance(sector["planned_transformers"], int):
            raise ValueError("Incomplete cell list or transformer plan.")
        for cell in sector["cells"]:
            key = (sector["sector"], cell)
            if key in all_cells:
                raise ValueError(f"Repeated sector/cell: {key}")
            all_cells.add(key)
        for person in sector["surveyors"]:
            title = person["name_in_plan"]
            if title.casefold() in all_people:
                raise ValueError(f"Duplicate planned team member: {title}")
            all_people.add(title.casefold())
            user = person.get("username")
            if not user:
                unresolved.append({"name":title,"sector":sector["sector"]})
                continue
            if not USERNAME_PATTERN.fullmatch(user):
                raise ValueError(f"Invalid portal username for {title}.")
            if user not in names or str(names[user]).strip().casefold() != str(
                person.get("mapped_full_name") or ""
            ).strip().casefold():
                raise ValueError(
                    f"Cannot confirm portal username {user} for {title} "
                    "against report_user_names.json."
                )
            mapped.append(user)
    if len(set(mapped)) != len(mapped):
        raise ValueError("The Pamela profile assigns one portal account to multiple names.")
    return profile, sorted(mapped, key=str.casefold), unresolved


def _roster_csv(path, profile, override_username):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as fh:
        writer=csv.writer(fh)
        writer.writerow([
            "Senior Supervisor","Field Supervisor","District","Sector",
            "Planned Surveyor","Portal Username","Mapping Status",
            "Planned Sector Cells","Planned Transformer Count","Planned Dates",
            "Replaces", "Staffing Change Note",
        ])
        for sector in profile["sectors"]:
            for person in sector["surveyors"]:
                username = person.get("username") or (
                    override_username if person["name_in_plan"] == "Kwizerwa Edison" else ""
                )
                status = (
                    "VERIFIED EXISTING USER MAP" if person.get("username")
                    else "USER SUPPLIED / REQUIRES PORTAL VERIFICATION" if username
                    else "UNMAPPED - NOT INCLUDED IN TEAM-ONLY FILTER"
                )
                writer.writerow([
                    "Pamela", "Derrick", "Gicumbi",sector["sector"],
                    person["name_in_plan"],username,status,
                    "; ".join(sector["cells"]),sector["planned_transformers"],
                    profile["planned_start"]+" to "+profile["planned_end"],
                    person.get("replaces", ""),
                    person.get("note", ""),
                ])


def _brief_asset_result(asset, result, members):
    known = {member.casefold() for member in members}
    if asset == "lv_line":
        by_user = result.get("user_summary", [])
        user_rows = [{
            "username": str(item.get("username") or ""),
            "checked": int(item.get("total_lines") or 0),
            "general_flagged": int(item.get("flagged_lines") or 0),
        } for item in by_user]
        metrics = {
            "checked": result.get("total_lines", 0),
            "outstanding_features": result.get("outstanding_lv_lines", 0),
            "outstanding_issues": result.get("outstanding_lv_issues", 0),
        }
    else:
        by_user = result.get("per_surveyor", [])
        user_rows = [{
            "username": str(item.get("username") or ""),
            "checked": int(item.get("total") or 0),
            "general_flagged": int(item.get("with_gaps") or 0),
        } for item in by_user]
        metrics = {
            "checked": result.get("total", 0),
            "outstanding_features": result.get("with_gaps", 0),
            "original_attribute_gap_features": result.get("original_attribute_gap_records", 0),
            "outstanding_issues": result.get("issue_count", 0),
            "duplicate_globalid_groups": result.get("duplicate_globalid_groups",0),
        }
    for row in user_rows:
        row["profile_membership"] = (
            "KNOWN_PAMELA_ACCOUNT" if row["username"].casefold() in known
            else "UNMAPPED_OR_OTHER_ACCOUNT_IN_AREA"
        )
    return {
        "asset": asset, "file":result.get("output_xlsx",""),
        **metrics,
        "by_surveyor": user_rows,
        "known_roster_records": sum(row["checked"] for row in user_rows
                                    if row["profile_membership"] == "KNOWN_PAMELA_ACCOUNT"),
        "other_or_unmapped_records": sum(row["checked"] for row in user_rows
                                        if row["profile_membership"] != "KNOWN_PAMELA_ACCOUNT"),
    }


def run_gicumbi_pamela_profile(
    output_folder: str | Path,
    start_date,
    end_date,
    assets: str = "all",
    scope: str = "team_only",
    kwizerwa_username: str | None = None,
    service_url: str | None = None,
    boundary_service_url: str | None = None,
    version: str = "sde.DEFAULT",
    gis: Any | None = None,
    profile_path: str | Path | None = None,
    user_map_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run three existing QA engines consistently over Pamela's six sectors."""
    profile, accounts, unresolved = load_pamela_profile(profile_path, user_map_path)
    if assets not in (*ASSETS, "all"):
        raise ValueError("assets must be 'all', 'pole', 'transformer' or 'lv_line'.")
    if scope not in SCOPE_OPTIONS:
        raise ValueError("Invalid Pamela review scope.")
    start, end = _as_date(start_date), _as_date(end_date)
    if end < start:
        raise ValueError("End date precedes start date.")
    override = str(kwizerwa_username or "").strip()
    if override:
        if not USERNAME_PATTERN.fullmatch(override):
            raise ValueError("Kwizerwa Edison portal username must contain only letters, digits, _, . or -.")
        if override.casefold() in {u.casefold() for u in accounts}:
            raise ValueError("Kwizerwa username duplicates another mapped team member.")
        accounts.append(override)
    # Team-only reports show verified accounts (plus explicitly supplied
    # override). All-in-area reports preserve accounts NOT on the roster.
    filtered_users = accounts if scope == "team_only" else None

    requested = ASSETS if assets == "all" else (assets,)
    base = Path(output_folder).expanduser().resolve()
    run_dir = base / ("Gicumbi_Pamela_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    run_dir.mkdir(parents=True, exist_ok=False)
    roster_path = run_dir / "Pamela_Team_Roster.csv"
    manifest_path = run_dir / "Pamela_Review_Manifest.json"
    _roster_csv(roster_path, profile, override)
    manifest: dict[str, Any] = {
        "status":"IN_PROGRESS","profile_id":profile["profile_id"],
        "senior_supervisor":"Pamela","field_supervisor":"Derrick",
        "district":"Gicumbi",
        "sectors":[sector["sector"] for sector in profile["sectors"]],
        "sector_cells":{sector["sector"]:sector["cells"] for sector in profile["sectors"]},
        "planned_transformer_total":sum(x["planned_transformers"] for x in profile["sectors"]),
        "planned_dates":[profile["planned_start"],profile["planned_end"]],
        "review_dates":[start.isoformat(),end.isoformat()],
        "date_rule":"created OR last edited in review period",
        "scope":scope,
        "scope_note":(
            "Team-only selects 11 verified portal usernames plus any provided "
            "Kwizerwa override; missing user cannot be assumed absent from GIS."
            if scope=="team_only" else
            "All creator accounts in the six sectors are included. Non-roster "
            "accounts are NOT automatically Pamela staff."
        ),
        "verified_usernames":accounts[:],
        "unresolved_planned_surveyors":unresolved if not override else [],
        "unverified_username_overrides":[
            {"name":"Kwizerwa Edison","username":override}
        ] if override else [],
        "roster_csv":str(roster_path),
        "requested_assets":list(requested),
        "completed_assets":[],
        "reports":[],
        "limitations":[
            "Sector-level assignment only; the plan does not assign individual cells to surveyors.",
            "Surveyor attribution uses created_user; a different last_edited_user may have corrected the record.",
            "Kwizerwa Edison replaced Manzi Intime in the staffing plan; no reuse of Intime's portal username is assumed without confirmation.",
            "Planned transformer totals are work-plan targets, not counts of GIS features.",
            "A QA run is not proof that work occurred only on the planned 14–16 Sep dates.",
            "Pole district/sector/cell may be missing from source attributes; geometry is scoped spatially.",
            "No network records are edited. Surveyor profile does not imply source topology validity.",
        ],
    }

    def save():
        manifest_path.write_text(
            json.dumps(manifest,indent=2,ensure_ascii=False,default=str)+"\n",
            encoding="utf-8",
        )
    save()
    sectors = manifest["sectors"]
    for asset in requested:
        try:
            if asset == "lv_line":
                result=run_quality_watcher(
                    output_xlsx=run_dir/"Pamela_LV_Lines.xlsx",
                    start_date=start, end_date=end,
                    district="Gicumbi",sectors=sectors,
                    usernames=filtered_users, output_flagged_feature_class=None,
                    service_url=service_url,
                    boundary_service_url=boundary_service_url,
                    version=version,gis=gis,
                )
            else:
                result=run_asset_quality(
                    asset=asset,
                    output_xlsx=run_dir/("Pamela_"+asset.title()+".xlsx"),
                    start_date=start,end_date=end,
                    district="Gicumbi",sectors=sectors,
                    usernames=filtered_users,
                    service_url=service_url,
                    boundary_service_url=boundary_service_url,
                    version=version,gis=gis,
                )
            brief=_brief_asset_result(asset,result,accounts)
            manifest["reports"].append(brief)
            manifest["completed_assets"].append(asset)
            save()
        except Exception as exc:
            manifest["status"]="INCOMPLETE"
            manifest["failed_asset"]=asset
            manifest["error"]=str(exc)
            save()
            raise RuntimeError(
                f"Gicumbi Pamela review stopped at {asset}. Successful earlier "
                f"reports are retained. See manifest {manifest_path}. "
                f"Reason: {exc}"
            ) from exc
    manifest["status"]="COMPLETE"
    save()
    return {
        "status":"COMPLETE",
        "manifest_json":str(manifest_path),
        "roster_csv":str(roster_path),
        "profile_directory":str(run_dir),
        "completed_assets":list(manifest["completed_assets"]),
        "reports":manifest["reports"],
        "unresolved_planned_surveyors":manifest["unresolved_planned_surveyors"],
        "scope":scope,
        "read_only":True,
    }
