"""Provisional LV conductor continuity using endpoint geometry, NOT network topology.

A tolerance-based same-creator endpoint graph is useful where Utility Network
dirty areas prevent a trace. It is not an electrical feeder, energized-source,
or connectivity proof. Never use proximity/name labels to update GIS records.
"""
from __future__ import annotations

from collections import defaultdict
from math import floor, hypot
from typing import Any, Mapping, Sequence


def geometry_paths(shape: Mapping[str, Any]) -> list[list[tuple[float, float]]]:
    paths = []
    for path in (shape or {}).get("paths", []):
        points = [(float(pt[0]), float(pt[1])) for pt in path if len(pt) >= 2]
        if len(points) >= 2:
            paths.append(points)
    return paths


def _point_cell(point, cell_size):
    return (floor(point[0] / cell_size), floor(point[1] / cell_size))


class _UnionFind:
    def __init__(self, ids):
        self.parent = {item: item for item in ids}
        self.rank = {item: 0 for item in ids}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        if self.rank[a] < self.rank[b]:
            a, b = b, a
        self.parent[b] = a
        if self.rank[a] == self.rank[b]:
            self.rank[a] += 1


def group_line_continuity(
    lines: Sequence[Mapping[str, Any]],
    transformers: Sequence[Mapping[str, Any]],
    endpoint_tolerance: float = 1.5,
    seed_tolerance: float = 7.0,
    suggestion_tolerance: float = 3.0,
) -> dict[str, Any]:
    """Group same-creator endpoint-connected LV lines, seeded by local transformers.

    Transformer assignment is always tentative. A seed within 7 metres is
    merely nearby; sources are not directional or electrically verified.
    Cross-surveyor continuity will be missed, and no nearby end-to-segment
    or crossing-midspan link is promoted automatically.
    """
    if not 0.05 <= endpoint_tolerance <= 5:
        raise ValueError("Endpoint tolerance must be from 0.05 to 5 metres.")
    if not endpoint_tolerance <= seed_tolerance <= 30:
        raise ValueError("Transformer seed tolerance must be >= endpoint tolerance and <=30 metres.")
    if not endpoint_tolerance <= suggestion_tolerance <= 30:
        raise ValueError("Suggestion tolerance must be >= endpoint tolerance and <=30 metres.")
    known = {}
    index = defaultdict(list)
    endpoints = []
    grid_size = endpoint_tolerance
    parent_ids = []
    for item in lines:
        attributes = item["attributes"]
        oid = int(attributes["OBJECTID"])
        if oid in known:
            raise RuntimeError(f"Repeated LV line OBJECTID {oid}.")
        if int(attributes.get("ASSETGROUP") or 0) not in (9, 10):
            raise RuntimeError(f"Non-LV line ObjectID {oid} in geometry continuity scan.")
        paths = geometry_paths(item["geometry"])
        if not paths:
            raise RuntimeError(f"Missing LV line geometry for ObjectID {oid}.")
        user = str(attributes.get("created_user") or "").strip().casefold()
        if not user:
            user = "(unknown creator)"
        known[oid] = {
            "attributes": attributes, "geometry": item["geometry"],
            "user": user, "multipart": len(paths) > 1,
        }
        parent_ids.append(oid)
        for path in paths:
            for point in (path[0], path[-1]):
                endpoints.append((oid, user, point))
    uf = _UnionFind(parent_ids)
    for oid, user, point in endpoints:
        cx, cy = _point_cell(point, grid_size)
        for gx in range(cx-1, cx+2):
            for gy in range(cy-1, cy+2):
                for other_oid, other_user, other_point in index.get((gx, gy), []):
                    if (user == other_user and oid != other_oid and
                            hypot(point[0]-other_point[0],
                                  point[1]-other_point[1]) <= endpoint_tolerance):
                        uf.union(oid, other_oid)
        index[(cx,cy)].append((oid,user,point))
    # Same-creator constraints apply along the ENTIRE geometric chain.
    components = defaultdict(set)
    for oid in known:
        components[uf.find(oid)].add(oid)
    component_by_oid = {
        oid: root for root, ids in components.items() for oid in ids
    }

    # Transformer point can be near multiple creator components.
    # Proximity does not prove their supply; never choose one by label alone.
    seed_index = defaultdict(list)
    seed_grid = seed_tolerance
    for oid, user, point in endpoints:
        seed_index[_point_cell(point,seed_grid)].append((oid,user,point))
    component_sources = defaultdict(dict)
    point_status = []
    for point_asset in transformers:
        attrs=point_asset["attributes"]
        pt_id=int(attrs["OBJECTID"])
        geom=point_asset["geometry"]
        if not geom or "x" not in geom or "y" not in geom:
            raise RuntimeError(f"Transformer {pt_id} has no point geometry.")
        point=(float(geom["x"]),float(geom["y"]))
        cx,cy=_point_cell(point,seed_grid)
        candidates={}
        for x in range(cx-1,cx+2):
            for y in range(cy-1,cy+2):
                for oid, _user, endpoint in seed_index.get((x,y),[]):
                    d=hypot(point[0]-endpoint[0],point[1]-endpoint[1])
                    if d <= seed_tolerance:
                        root=component_by_oid[oid]
                        candidates[root]=min(d,candidates.get(root,float("inf")))
        for root,d in candidates.items():
            component_sources[root][pt_id]=d
        point_status.append({
            "objectid":pt_id,"globalid":attrs.get("GLOBALID"),
            "name":attrs.get("Transfomer_name_") or "",
            "candidate_components":len(candidates),
            "nearest_endpoint_m":min(candidates.values()) if candidates else None,
            "status":"PROVISIONAL_GEOMETRIC_SEED" if candidates else "NO_ENDPOINT_WITHIN_SEED_DISTANCE",
        })

    points_by_oid={int(item["attributes"]["OBJECTID"]):item["attributes"]
                   for item in transformers}
    results=[]
    for oid in sorted(known):
        item=known[oid]
        root=component_by_oid[oid]
        sources=component_sources.get(root,{})
        chosen=None
        if len(sources)==0:
            status="NO_DISTRICT_START_GEOMETRY"
            reason="No starting transformer endpoint proximity connects this same-creator line component."
        elif len(sources)>1:
            status="MULTIPLE_TRANSFORMERS_NEAR_COMPONENT"
            reason="Multiple in-district transformers are near this component; source is ambiguous."
        else:
            sid,dist=next(iter(sources.items()))
            chosen=points_by_oid[sid]
            label=str(item["attributes"].get("Transformer_Name") or "").strip()
            name=str(chosen.get("Transfomer_name_") or "").strip()
            if not name or not label:
                status="NAME_UNVERIFIED_GEOMETRY"
                reason="A transformer/line name is absent; the geometry cannot establish a correct name."
            elif label.casefold()!=name.casefold():
                status="NAME_DIFFERENCE_PROVISIONAL"
                reason="Recorded line name differs from nearby transformer; topology and source NOT verified."
            else:
                status="PROVISIONAL_GEOMETRY_MATCH"
                reason="Recorded name agrees with nearby transformer and same-creator endpoint chain, not a verified feeder."
            reason+=f" Closest transformer/line endpoint distance {dist:.2f}m."
        if item["multipart"]:
            reason+=" Multipart geometry may comprise disjoint segments."
        results.append({
            "objectid":oid,
            "globalid":str(item["attributes"].get("GLOBALID") or ""),
            "created_user":str(item["attributes"].get("created_user") or ""),
            "status":status,
            "evidence":reason,
            "component_id":min(components[root]),
            "component_size":len(components[root]),
            "source_count":len(sources),
            "source_objectids":sorted(sources),
            "transformer_objectid":int(chosen["OBJECTID"]) if chosen else None,
            "transformer_globalid":str(chosen.get("GLOBALID") or "") if chosen else "",
            "connected_transformer_name":str(chosen.get("Transfomer_name_") or "") if chosen else "",
            "multipart":item["multipart"],
        })
    # Identify close-but-not-joined same-creator endpoints; don't add
    # predicted connections to the feeder graph or counts.
    suggestions=set()
    if suggestion_tolerance>endpoint_tolerance:
        gap_grid=suggestion_tolerance
        cells=defaultdict(list)
        for oid,user,pt in endpoints:
            cx,cy=_point_cell(pt,gap_grid)
            for x in range(cx-1,cx+2):
                for y in range(cy-1,cy+2):
                    for other_oid,other_user,other_pt in cells.get((x,y),[]):
                        if (oid==other_oid or user!=other_user or
                                component_by_oid[oid]==component_by_oid[other_oid]):
                            continue
                        distance=hypot(pt[0]-other_pt[0],pt[1]-other_pt[1])
                        if endpoint_tolerance<distance<=suggestion_tolerance:
                            ids=tuple(sorted((oid,other_oid)))
                            suggestions.add((ids[0],ids[1],round(distance,3)))
            cells[(cx,cy)].append((oid,user,pt))
    return {
        "results":results,
        "components":len(components),
        "source_details":point_status,
        "suggested_gaps":[
            {"line_oid_a":a,"line_oid_b":b,"distance_m":d}
            for a,b,d in sorted(suggestions)
        ],
        "method":"PROVISIONAL_GEOMETRY_NO_UTILITY_NETWORK_TRACE",
        "endpoint_tolerance_m":endpoint_tolerance,
        "seed_tolerance_m":seed_tolerance,
    }
