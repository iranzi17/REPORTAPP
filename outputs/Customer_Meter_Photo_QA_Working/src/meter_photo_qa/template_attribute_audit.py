"""Template-aware surveyor QA expressions, strictly resolved against live schema.

No machine-generated SQL. Exactly one asset, one known area, one supported
comparison OR a list of missing fields, grouped by created_user. Unknown
fields and ambiguous alias matches always fail closed.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Mapping
from .smart_query import _load_admin, ASSET_GROUPS, ASSET_LAYERS
from .asset_quality import ASSETS,resolve_fields

ASSET_TERMS = {
    "pole": r"\b(?:lv\s+)?poles?\b",
    "transformer": r"\b(?:distribution\s+)?transformers?\b",
    "line": r"\b(?:lv\s+lines?|low[\s-]*voltage\s+lines?|lv\s+conductors?)\b",
}
NUMBER = r"(-?\d+(?:\.\d+)?)"
OPERATORS = [
    ("gte", r"(?:greater\s+than\s+or\s+equal\s+to|at\s+least|>=)"),
    ("lte", r"(?:less\s+than\s+or\s+equal\s+to|at\s+most|<=)"),
    ("gt", r"(?:greater\s+than|higher\s+than|more\s+than|above|over|>)"),
    ("lt", r"(?:less\s+than|lower\s+than|below|under|<)"),
    ("eq", r"(?:equal\s+to|equals|=)"),
]
TYPE_NUMERIC = {
    "esriFieldTypeInteger", "esriFieldTypeSmallInteger",
    "esriFieldTypeSingle", "esriFieldTypeDouble",
    "esriFieldTypeBigInteger",
}
UNKNOWN_LABELS = {"unknown","n/a","not applicable","not known","null","no data","not recorded","unselected"}
RESERVED = {"objectid","globalid","createduser","lastediteduser","shape","geometry"}


@dataclass(frozen=True)
class Criterion:
    field_phrase: str
    operator: str
    value: float | None = None


@dataclass(frozen=True)
class TemplateAuditPlan:
    asset: str
    district: str
    sector: str | None
    cell: str | None
    criteria: tuple[Criterion, ...]
    condition_mode: str = "all"

    def serialize(self):
        return {
            "asset":self.asset,"district":self.district,
            "sector":self.sector,"cell":self.cell,
            "condition_mode":self.condition_mode,
            "criteria":[
                {"field_requested":c.field_phrase,"operator":c.operator,"value":c.value}
                for c in self.criteria
            ],
            "group_by":"created_user",
        }


def _canon(value):
    return re.sub(r"[^a-z0-9]+","",str(value or "").casefold())


def _strip_field_phrase(value, asset):
    value=str(value).strip().casefold()
    value=re.sub(r"\s+"," ",value).strip()
    value=re.sub(r"^(?:the|a|an|fields?|attributes?|values?|of)\s+","",value)
    value=re.sub(r"(?:\s+(?:fields?|attributes?|values?))+$","",value)
    value=re.sub(r"^(?:the|a|an)\s+","",value)
    if asset=="pole":
        value=re.sub(r"^(?:pole|lv pole)\s+","",value)
        value=re.sub(r"\s+of\s+(?:a\s+|the\s+)?(?:lv\s+)?poles?$","",value)
    if asset=="transformer":
        value=re.sub(r"^(?:distribution\s+)?transformer\s+","",value)
        value=re.sub(r"\s+of\s+(?:a\s+|the\s+)?(?:distribution\s+)?transformers?$","",value)
    if asset=="line":
        value=re.sub(r"^(?:lv\s+)?line\s+","",value)
        value=re.sub(r"\s+of\s+(?:a\s+|the\s+)?(?:lv\s+)?lines?$","",value)
    return value.strip(" .:-")


def parse_surveyor_template_request(request):
    """Examples:
    'Give me surveyors recording pole height greater than 12 in Gicumbi'
    'Show surveyors missing manufacturer and append cable on LV poles in Gicumbi sector Muko'
    """
    raw=str(request or "").strip().rstrip(".?!")
    if not 10<=len(raw)<=600:
        raise ValueError("Enter a surveyor/attribute audit request (10-600 characters).")
    if re.search(r"\b(delete|update|remove|edit|overwrite|drop|erase|fix)\b",raw,re.I):
        raise ValueError("This is a read-only surveyor template audit; editing commands are not supported.")
    if not re.match(r"^(?:give(?:\s+me|\s+the)?|show|find|list|identify|which|who|check)\b",raw,re.I):
        raise ValueError("Start with 'Show surveyors...' or 'Give me surveyors...'.")
    if not re.search(r"\bsurveyors?\b",raw,re.I):
        raise ValueError("This audit summarizes affected surveyors. Include the word 'surveyors'.")
    # An explicit 'on LV lines' context takes precedence over 'transformer
    # name', which is a line attribute and not a second asset category.
    explicit=[]
    for key,pattern in ASSET_TERMS.items():
        if re.search(r"\b(?:on|for)\s+(?:the\s+)?"+pattern+
                     r"\s+in\s+",raw,re.I):
            explicit.append(key)
    assets=explicit or [
        key for key,pattern in ASSET_TERMS.items()
        if re.search(pattern,raw,re.I)
    ]
    if len(assets)!=1:
        raise ValueError("Specify one asset category: LV poles, distribution transformers or LV lines.")
    asset=assets[0]
    districts,cells_map=_load_admin()
    options=[]
    for district in districts:
        m=re.search(r"\bin\s+"+re.escape(district)+r"\b",raw,re.I)
        if m:options.append((district,m))
    if len(options)!=1:
        raise ValueError("Specify exactly one recognized district, e.g. 'in Gicumbi'.")
    district,area_match=options[0]
    region=raw[area_match.end():].strip()
    sector=cell=None
    if region:
        region=re.sub(r"^\s*(?:district)?\s*","",region,flags=re.I)
        match=re.fullmatch(
            r"(?:sector\s+)?([\w \-']+?)(?:\s+cell\s+([\w \-']+))?",
            region, re.I,
        )
        if match and region:
            name=match.group(1).strip()
            if name.casefold().startswith("sector "):
                name=name[7:].strip()
            found=[s for s in districts[district] if s.casefold()==name.casefold()]
            if found:
                sector=found[0]
                if match.group(2):
                    matching=[x for x in cells_map.get(district,{}).get(sector,[])
                              if x.casefold()==match.group(2).strip().casefold()]
                    if len(matching)!=1:
                        raise ValueError(f"Cell '{match.group(2)}' is not verified in {district}/{sector}.")
                    cell=matching[0]
            else:
                raise ValueError(f"Unrecognized sector '{name}' in {district}.")
        elif region:
            raise ValueError(f"Unrecognized area qualifier after {district}: '{region}'.")
    main=raw[:area_match.start()].strip()
    main=re.sub(r"^(?:give(?:\s+me|\s+the)?|show|find|list|identify|which|who|check)\s+","",main,flags=re.I)
    main=re.sub(r"^(?:the\s+)?surveyors?\s+(?:who\s+|that\s+)?","",main,flags=re.I)
    main=re.sub(r"^(?:are\s+|have\s+|has\s+|were\s+)?","",main,flags=re.I)
    # Drop the asset phrase only as its OWN phrase, not inside e.g. height of pole.
    main=re.sub(r"\s+\b(?:on|for)\s+(?:the\s+)?"+ASSET_TERMS[asset]+r"\s*$","",main,flags=re.I)
    main=re.sub(r"^(?:"+ASSET_TERMS[asset]+r")\s+","",main,flags=re.I)
    main=main.strip()
    if not main:
        raise ValueError("Specify what to check, e.g. 'missing manufacturer' or 'height greater than 12'.")

    missing_match=re.match(
        r"^(?:(?:who\s+)?(?:are\s+)?(?:filling\s+|recording\s+|have\s+)?"
        r"(?:not\s+filled|not\s+recorded|missing|without|blank|empty)\s+)(.+)$",
        main,re.I,
    )
    if missing_match:
        rest=missing_match.group(1).strip()
        any_mode=False
        if re.match(r"^(?:any\s+of|either)\s+",rest,re.I):
            rest=re.sub(r"^(?:any\s+of|either)\s+","",rest,flags=re.I)
            any_mode=True
        pieces=re.split(r"\s+(?:and|or)\s+|,\s*",rest,flags=re.I)
        if len(pieces)>6:
            raise ValueError("Limit the audit to six mandatory fields at a time.")
        if re.search(r"\s+or\s+",rest,re.I):
            if re.search(r"\s+and\s+",rest,re.I):
                raise ValueError("Mixed AND/OR field conditions are ambiguous; choose all or any.")
            any_mode=True
        criteria=tuple(Criterion(_strip_field_phrase(p,asset),"missing") for p in pieces)
        if not all(c.field_phrase for c in criteria):
            raise ValueError("One of the missing attribute names is blank.")
        return TemplateAuditPlan(asset,district,sector,cell,criteria,"any" if any_mode else "all")

    main=re.sub(
        r"^(?:(?:who\s+)?(?:are\s+)?(?:filling(?:\s+in)?|recording|recorded|filled|have|has)"
        r"\s+(?:the\s+)?)", "",main,flags=re.I
    ).strip()
    main=re.sub(r"\s+(?:with\s+)?(?:the\s+)?values?\s*$","",main,flags=re.I).strip()
    matches=[]
    for key,op in OPERATORS:
        m=re.search(r"\s+"+op+r"\s*"+NUMBER+r"\s*(?P<unit>metres?|meters?|m|feet|ft)?\s*$",
                    main,re.I)
        if m:
            matches.append((key,m))
    if not matches:
        raise ValueError(
            "Use 'missing field A and field B' or one numeric check such as "
            "'height of pole greater than 12'. Unsupported expressions are not ignored."
        )
    key,matched=sorted(matches,key=lambda t:t[1].start())[0]
    field_raw=main[:matched.start()].strip()
    field_raw=re.sub(r"^(?:with|where|that\s+have)\s+","",field_raw,flags=re.I)
    field_raw=re.sub(r"\s+(?:with\s+)?(?:the\s+)?values?$","",field_raw,flags=re.I).strip()
    field=_strip_field_phrase(field_raw,asset)
    if not field:
        raise ValueError("Numeric comparison is missing the field name.")
    unit=(matched.groupdict().get("unit") or "").lower()
    # There is no generally reliable template unit metadata. A plain numeric
    # condition compares the stored unit. Explicit units require validation.
    if unit:
        raise ValueError(
            "The live GIS field's unit has not been verified. Omit 'm'/'ft' "
            "to compare the stored numeric value, and confirm the field unit."
        )
    return TemplateAuditPlan(asset,district,sector,cell,
                             (Criterion(field,key,float(matched.group(1))),))


def _field_tokens(phrase,asset):
    candidates=[_canon(phrase)]
    clean=_strip_field_phrase(phrase,asset)
    candidates.append(_canon(clean))
    if asset=="pole":
        candidates.extend([_canon("pole "+clean),_canon(clean+" of pole")])
    if asset=="transformer":
        candidates.extend([_canon("transformer "+clean),_canon(clean+" of transformer")])
    if asset=="line":
        candidates.extend([_canon("lv line "+clean),_canon(clean+" of line")])
    return list(dict.fromkeys(x for x in candidates if x))


def resolve_live_field(phrase,asset,fields):
    """Exact normalized name/alias match, never fuzzy best guess."""
    target=_field_tokens(phrase,asset)
    candidates=[]
    for field in fields:
        name=str(field.get("name") or "")
        alias=str(field.get("alias") or "")
        if not name or _canon(name) in RESERVED:
            continue
        if any(token in (_canon(name),_canon(alias)) for token in target):
            candidates.append(field)
    if len(candidates)==1:
        return candidates[0]
    if len(candidates)>1:
        raise ValueError(
            f"Ambiguous template attribute '{phrase}' matches "
            + ", ".join(sorted(str(f["name"]) for f in candidates))
            + ". Use its exact field name."
        )
    # Where the historical asset template explicitly declares a synonym
    # (e.g. Manufacturer vs live Manufacturers), use ONLY that verified
    # mapping. This is not fuzzy matching against arbitrary fields.
    if asset in ASSETS:
        known=ASSETS[asset]["checks"]
        lookup=resolve_fields(fields,asset)
        recognized=set(_field_tokens(phrase,asset))
        alias_keys=[
            key for key,aliases in known.items()
            if any(_canon(alias) in recognized for alias in aliases)
        ]
        selections={lookup.get(key) for key in alias_keys if lookup.get(key)}
        if len(selections)==1:
            selected=next(iter(selections))
            return next(f for f in fields if str(f["name"]).casefold()==selected.casefold())
        if len(selections)>1:
            raise ValueError(f"Attribute '{phrase}' maps to multiple template fields; use exact live name.")
    valid=", ".join(sorted(str(f.get("alias") or f["name"]) for f in fields
                           if _canon(f.get("name")) not in RESERVED)[:28])
    raise ValueError(
        f"Template attribute '{phrase}' was not found in the live {asset} layer. "
        f"Check its alias or field name. Examples: {valid}."
    )


def compile_template_filter(plan, fields, domains=None):
    """Return SQL, resolved field names, and display criteria; SQL only schema names."""
    lookup={str(f["name"]).casefold():dict(f) for f in fields}
    for required in ("ASSETGROUP","OBJECTID","created_user"):
        if required.casefold() not in lookup:
            raise ValueError(f"Live template is missing required field {required}.")
    terms=[]
    resolved=[]
    for criterion in plan.criteria:
        field=resolve_live_field(criterion.field_phrase,plan.asset,fields)
        name=str(field["name"])
        type_=str(field.get("type") or "")
        codes=(domains or {}).get(name,{})
        if criterion.operator=="missing":
            term=f"{name} IS NULL"
            if type_ not in TYPE_NUMERIC:
                term=f"({term} OR {name} = '')"
            invalid=[code for code,label in codes.items()
                     if str(label or "").strip().casefold() in UNKNOWN_LABELS]
            for code in invalid:
                if isinstance(code,(int,float)) and not isinstance(code,bool):
                    literal=str(code)
                else:
                    literal="'"+str(code).replace("'","''")+"'"
                term=f"({term} OR {name} = {literal})"
        else:
            if type_ not in TYPE_NUMERIC:
                raise ValueError(
                    f"{name} (alias {field.get('alias',name)}) is not numeric. "
                    "Greater-than/less-than requires a verified numeric field."
                )
            operator={"gt":">","gte":">=","lt":"<","lte":"<=","eq":"="}[criterion.operator]
            term=f"{name} {operator} {criterion.value:g}"
        terms.append("("+term+")")
        resolved.append({
            "requested":criterion.field_phrase,
            "live_field":name,
            "alias":field.get("alias") or name,
            "type":type_,"operator":criterion.operator,"value":criterion.value,
            "domain_unknown_codes":[str(k) for k in codes
                                     if str(codes[k]).strip().casefold() in UNKNOWN_LABELS],
        })
    joiner=" OR " if plan.condition_mode=="any" else " AND "
    sql="ASSETGROUP IN ("+",".join(map(str,ASSET_GROUPS[plan.asset]))+")"
    if plan.asset in ASSETS:
        if "ASSETTYPE" not in {str(f["name"]).upper() for f in fields}:
            raise ValueError("The live template lacks ASSETTYPE required to identify eligible assets.")
        allowed=sorted(ASSETS[plan.asset]["types"])
        sql+=" AND ASSETTYPE IN ("+",".join(map(str,allowed))+")"
    if terms:
        sql+=" AND ("+joiner.join(terms)+")"
    return sql,tuple(dict.fromkeys(x["live_field"] for x in resolved)),resolved
