"""Safe, deliberately bounded natural-language queries for REG Utility Network.

This is NOT an unrestricted SQL generator or an LLM. Requests are parsed
into explicit whitelisted asset/field/administrative predicates; unmatched
phrases fail closed rather than being silently ignored. The ArcGIS runner
produces a preview or optional locally copied filtered features, never edits
the REG FeatureServer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .area_selection import district_filters
from .asset_quality import ASSETS, resolve_fields
from .progress_report import LINE_LAYER_ID

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"
INDEX_PATH = CONFIG_ROOT / "rwanda_district_sectors.json"
ROSTER_PATH = CONFIG_ROOT / "gicumbi_pamela_team.json"

ASSET_PATTERNS = (
    ("pole", r"\b(?:lv\s+)?poles?\b"),
    ("transformer", r"\b(?:distribution\s+)?transformers?\b"),
    ("line", r"\b(?:lv\s+)?lines?\b|\blv\s+conductors?\b"),
)
ASSET_LAYERS = {"pole": 12, "transformer": 7, "line": LINE_LAYER_ID}
ASSET_GROUPS = {"pole": (7,), "transformer": (12,), "line": (9,10)}

FIELDS = {
    "pole": {
        "manufacturer": (r"manufacturers?|make", "manufacturer"),
        "notes": (r"notes?|remarks?", "notes"),
    },
    "transformer": {
        "name": (r"transformer\s+name|name", "name"),
        "owner_name": (r"owner(?:\s+name)?", "owner_name"),
        "installation_type": (r"(?:type\s+of\s+installation|installation\s+type)", "installation_type"),
        "phase_normal": (r"phase\s+normal|phases?", "phase_normal"),
        "protection_switch": (r"transformer\s+protection\s+switch|protection\s+switch", "protection_switch"),
        "mounting_support": (r"mounting\s+support", "mounting_support"),
        "lv_feeder_count": (r"number\s+of\s+(?:lv|low\s+voltage)\s+feeders?|lv\s+feeder\s+count", "lv_feeder_count"),
        "manufacturer": (r"manufacturers?|make", "manufacturer"),
        "serial": (r"serial(?:\s+number)?", "serial"),
        "capacity": (r"rated\s+(?:capacity|kva)|capacity|kva", "capacity"),
    },
    "line": {
        "name": (r"transformer\s+name", "Transformer_Name"),
        "voltage": (r"voltage", "Voltage_Level_kV"),
        "phases": (r"phases?", "Phases"),
        "material": (r"material", "Material"),
        "conductor_size": (r"conductor\s+size|cable\s+size", "CondustorSize"),
        "rated_current": (r"rated\s+current|current\s+capacity", "Rated_Current"),
        "insulation": (r"conductor\s+insulation|insulation", "ConductorInsulation"),
        "notes": (r"notes?", "Notes"),
    },
}
LINE_FIELDS = {
    "name": ("Transformer_Name",),
    "voltage": ("Voltage_Level_kV",),
    "phases": ("Phases",),
    "material": ("Material",),
    "conductor_size": ("CondustorSize",),
    "rated_current": ("Rated_Current",),
    "insulation": ("ConductorInsulation",),
    "notes": ("Notes",),
}
NUMERIC_TYPES = {
    "esriFieldTypeInteger", "esriFieldTypeSmallInteger",
    "esriFieldTypeSingle", "esriFieldTypeDouble",
    "esriFieldTypeBigInteger", "esriFieldTypeOID",
}
ACTION_PAT = re.compile(
    r"^\s*(?P<verb>show|find|filter|list|count|select|display)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?",
    re.IGNORECASE,
)
UNSAFE = re.compile(
    r"\b(delete|remove|erase|update|change|modify|fix|overwrite|truncate|drop|insert|edit)\b",
    re.IGNORECASE,
)
EXTRA_ALLOWED = re.compile(
    r"^(?:\s|,|\.|;|:|\?|and\b|with\b|where\b|that\b|have\b|has\b|missing\b|is\b|of\b|the\b|in\b|from\b|records?\b|features?\b|by\b)*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AttributeCondition:
    key: str
    op: str
    value: str | None = None


@dataclass(frozen=True)
class QueryPlan:
    action: str
    asset: str
    district: str | None
    sector: str | None
    cell: str | None
    surveyors: tuple[str, ...]
    conditions: tuple[AttributeCondition, ...]
    pamela_team: bool = False

    def serialize(self) -> dict:
        return {
            "action": self.action, "asset": self.asset,
            "district": self.district, "sector": self.sector,
            "cell": self.cell, "surveyors": list(self.surveyors),
            "conditions": [
                {"field": i.key, "operator": i.op, "value": i.value}
                for i in self.conditions
            ], "pamela_team": self.pamela_team,
        }


def _load_admin():
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return data["districts"], data["cells"]


def _consume(remaining: str, match: re.Match) -> str:
    return remaining[:match.start()] + " " * (match.end()-match.start()) + remaining[match.end():]


def parse_request(message: str) -> QueryPlan:
    """Interpret an intentionally finite query grammar; reject extra claims."""
    raw = str(message or "").strip()
    if not raw or len(raw) > 550:
        raise ValueError("Enter one query (up to 550 characters).")
    if UNSAFE.search(raw):
        raise ValueError("Data editing/deleting commands are not supported. Ask to show, find, count or filter records.")
    command = ACTION_PAT.match(raw)
    if not command:
        raise ValueError("Start with Show, Find, Filter, Count or Select. Example: 'Show LV poles in Gicumbi with missing manufacturer'.")
    action = command.group("verb").casefold()
    remaining = raw[command.end():]
    found = []
    for asset, regex in ASSET_PATTERNS:
        match = re.search(regex, remaining, flags=re.IGNORECASE)
        if match:
            found.append((asset, match))
    if len(found) != 1:
        raise ValueError("Specify exactly one asset: LV poles, distribution transformers, or LV lines.")
    asset, match = found[0]
    remaining = _consume(remaining, match)

    districts, cell_dict = _load_admin()
    found_districts = []
    for item in districts:
        m = re.search(r"(?<![\w])"+re.escape(item)+r"(?![\w])", remaining, re.I)
        if m:
            found_districts.append((item,m))
    if len(found_districts) > 1:
        raise ValueError("Choose one district per natural-language request; use the existing multi-district QA tools for batches.")
    district = found_districts[0][0] if found_districts else None
    if district:
        remaining = _consume(remaining, found_districts[0][1])

    pamela = bool(re.search(r"\bPamela(?:'s)?\s+team\b", remaining, flags=re.I))
    if pamela:
        if district and district.casefold() != "gicumbi":
            raise ValueError("Pamela's mapped team profile is Gicumbi only.")
        district = "Gicumbi"
        remaining = re.sub(r"\bPamela(?:'s)?\s+team\b", " ", remaining, flags=re.I)

    sector = cell = None
    sector_m = re.search(r"\bsector\s+([A-Za-z][A-Za-z '\-]*)", remaining, re.I)
    if sector_m:
        if not district:
            raise ValueError("State the district before a sector (e.g. 'in Gicumbi sector Muko').")
        candidate = sector_m.group(1).strip()
        # Match longest known sector that starts the captured text, retaining
        # any subsequent 'with' or 'where' expression for attribute parsing.
        matches = [s for s in districts[district]
                   if re.match(re.escape(s)+r"(?:\b|$)",candidate,re.I)]
        if len(matches)!=1:
            raise ValueError(f"Unknown or ambiguous sector in {district}: {candidate}.")
        sector = matches[0]
        start = sector_m.start()
        end = sector_m.start(1)+len(sector)
        remaining = remaining[:start]+" "*(end-start)+remaining[end:]
    cell_m = re.search(r"\bcell\s+([A-Za-z][A-Za-z '\-]*)",remaining,re.I)
    if cell_m:
        if not district or not sector:
            raise ValueError("State district and sector before cell.")
        candidate = cell_m.group(1).strip()
        choices = cell_dict.get(district,{}).get(sector,[])
        matches = [c for c in choices if re.match(re.escape(c)+r"(?:\b|$)",candidate,re.I)]
        if len(matches)!=1:
            raise ValueError(f"Unknown/ambiguous cell in {district}/{sector}: {candidate}.")
        cell=matches[0]
        start=cell_m.start()
        end=cell_m.start(1)+len(cell)
        remaining=remaining[:start]+" "*(end-start)+remaining[end:]
    if sector and pamela:
        raise ValueError("Pamela team means six assigned sectors; omit the additional sector condition.")

    surveyors: tuple[str,...] = ()
    user_m = re.search(r"\b(?:by|surveyor(?:\s+username)?|created\s+by)\s+([A-Za-z0-9._\-]{3,80})\b",remaining,re.I)
    if user_m:
        username=user_m.group(1)
        surveyors=(username,)
        remaining=_consume(remaining,user_m)
    if pamela:
        if surveyors:
            raise ValueError("Pamela team is a set of surveyors; omit the individual surveyor filter.")
        profile=json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        if profile.get("district")!="Gicumbi" or profile.get("senior_supervisor")!="Pamela":
            raise ValueError("Team roster configuration is inconsistent.")
        surveyors=tuple(sorted({
            s["username"] for sector_item in profile["sectors"]
            for s in sector_item["surveyors"] if s.get("username")
        },key=str.casefold))
        if len(surveyors)!=12:
            raise ValueError("Pamela team must have exactly 12 verified account usernames.")

    conditions=[]
    expressions=FIELDS[asset]
    for key, (pattern, _source) in expressions.items():
        field_pat=r"(?:%s)"%pattern
        # One explicit condition per supported field. Do not ignore unexplained
        # words; the final residue validator rejects unsupported queries.
        patterns = [
            (r"\b(?:missing|blank|empty|unknown|without|no)\s+(?P<field>"+field_pat+r")\b", "missing"),
            (r"\b(?P<field>"+field_pat+r")\s+(?:is\s+)?(?:missing|blank|empty|null|unknown|not\s+recorded)\b", "missing"),
            (r"\b(?P<field>"+field_pat+r")\s*(?:equals|is\s+equal\s+to|=|is)\s+(?P<value>\"[^\"]{1,90}\"|'[^']{1,90}'|[A-Za-z0-9._\-]{1,90}(?:\s*[Vv])?)", "equals"),
        ]
        matches=[]
        for ptn,op in patterns:
            m=re.search(ptn,remaining,re.I)
            if m:
                matches.append((m,op))
        if not matches:
            continue
        # Select earliest occurrence; if a second condition remains it is
        # detected as unsupported residue or a duplicate field reference.
        matches.sort(key=lambda x:(x[0].start(),-(x[0].end()-x[0].start())))
        m,op=matches[0]
        value=m.groupdict().get("value")
        if value:
            value=value.strip().strip("\"'")
            if key=="voltage":
                value=re.sub(r"\s*[Vv]$", "",value)
        conditions.append(AttributeCondition(key,op,value))
        remaining=_consume(remaining,m)

    if not EXTRA_ALLOWED.fullmatch(remaining):
        unknown=" ".join(remaining.split())
        raise ValueError(
            f"Unsupported or ambiguous part of the request: '{unknown}'. "
            "Use one asset and explicit fields such as missing manufacturer, "
            "missing transformer name, voltage = 400, or owner name is blank."
        )
    return QueryPlan(action,asset,district,sector,cell,surveyors,tuple(conditions),pamela)


def compile_attribute_where(plan: QueryPlan, live_fields: list[Mapping[str,Any]], domains=None):
    """Compile validated field identifiers and literal values only."""
    fields=[dict(f) for f in live_fields]
    lookup={str(f["name"]).casefold():f for f in fields}
    def resolve(key):
        if plan.asset=="line":
            names=LINE_FIELDS[key]
            matches=[lookup[v.casefold()] for v in names if v.casefold() in lookup]
            if len(matches)!=1:
                raise ValueError(f"The live LV line layer has no verified field for {key}; cannot query it.")
            return matches[0]
        name=resolve_fields(fields,plan.asset).get(key)
        if not name:
            raise ValueError(f"Cannot verify live {plan.asset} field for '{key}'; inspect the layer schema.")
        return lookup[name.casefold()]
    clauses=["ASSETGROUP IN ("+",".join(map(str,ASSET_GROUPS[plan.asset]))+")"]
    if plan.surveyors:
        fld=lookup.get("created_user")
        if not fld:
            raise ValueError("Live layer lacks created_user; cannot safely filter surveyors.")
        def quote(value):
            return "'"+str(value).replace("'","''")+"'"
        clauses.append("created_user IN ("+",".join(quote(u) for u in plan.surveyors)+")")
    for condition in plan.conditions:
        field=resolve(condition.key)
        field_name=field["name"]  # verified directly from live schema
        domain=(domains or {}).get(field_name,{})
        if condition.op=="missing":
            if field.get("type") in NUMERIC_TYPES:
                predicate=f"{field_name} IS NULL"
            else:
                predicate=f"({field_name} IS NULL OR {field_name} = '')"
            # Add only explicit coded 'Unknown' / 'N/A' domain values,
            # never infer that numerical zero is missing.
            unknown_codes=[
                code for code,label in domain.items()
                if str(label or "").strip().casefold() in (
                    "unknown","none","not known","n/a","null",
                )
            ]
            for code in unknown_codes:
                code_sql=str(code) if isinstance(code,(int,float)) else "'"+str(code).replace("'","''")+"'"
                predicate="("+predicate+f" OR {field_name} = {code_sql})"
        else:
            val=str(condition.value or "")
            if field.get("type") in NUMERIC_TYPES:
                if not re.fullmatch(r"-?\d+(?:\.\d+)?",val):
                    raise ValueError(f"{field_name} is numeric: provide a number, not '{val}'.")
                value_sql=val
            else:
                if len(val)>90:
                    raise ValueError("Field filter value is too long.")
                value_sql="'"+val.replace("'","''")+"'"
            predicate=f"{field_name} = {value_sql}"
        clauses.append("("+predicate+")")
    return " AND ".join(clauses)


def boundary_where(plan: QueryPlan):
    if not plan.district:
        return None
    if plan.pamela_team:
        profile=json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        return district_filters("Gicumbi",[x["sector"] for x in profile["sectors"]])
    sectors=[plan.sector] if plan.sector else None
    cells=[f"{plan.district} :: {plan.sector} :: {plan.cell}"] if plan.cell else None
    return district_filters(plan.district,sectors,cells)


EXAMPLES = (
    "Show LV poles in Gicumbi with missing manufacturer",
    "Find distribution transformers in Burera with protection switch is unknown",
    "Count LV lines in Gicumbi sector Muko with missing transformer name",
    "Filter LV lines in Gasabo with voltage = 400",
    "Show LV poles in Pamela team with missing notes",
)
