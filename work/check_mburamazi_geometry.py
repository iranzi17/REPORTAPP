"""Read-only proximity diagnostic; proximity does not establish network connectivity."""

import math
from collections import Counter

from arcgis.features import FeatureLayer
from arcgis.gis import GIS

BASE = "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer"


def segment_distance(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    length_sq = vx * vx + vy * vy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / length_sq))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def main():
    gis = GIS("pro")
    transformers = FeatureLayer(BASE + "/7", gis)
    lines = FeatureLayer(BASE + "/10", gis)
    trf = transformers.query(where="OBJECTID=227017", out_fields="OBJECTID", return_geometry=True).features[0]
    lv = lines.query(where="ASSETGROUP IN (9,10) AND UPPER(Transformer_Name)='MBURAMAZI TRF'",
                     out_fields="OBJECTID", return_geometry=True, return_all_records=True)
    x, y = trf.geometry["x"], trf.geometry["y"]
    distances = []
    endpoint_distances = []
    line_ends = []
    line_segments = []
    for feature in lv.features:
        paths = feature.geometry.get("paths", [])
        segment_distances = []
        ends = []
        for path in paths:
            if not path:
                continue
            ends.extend((path[0], path[-1]))
            segment_distances.extend(segment_distance(x, y, *a[:2], *b[:2]) for a, b in zip(path, path[1:]))
        if segment_distances:
            distances.append(min(segment_distances))
        if ends:
            endpoint_distances.append(min(math.hypot(x-p[0], y-p[1]) for p in ends))
            line_ends.append((feature.attributes["OBJECTID"], [tuple(p[:2]) for p in ends]))
            line_segments.append((feature.attributes["OBJECTID"], [
                (tuple(a[:2]), tuple(b[:2]))
                for path in paths for a, b in zip(path, path[1:])
            ]))
    print("Spatial reference:", lv.spatial_reference)
    print("Transformer point:", (x, y))
    print("Line geometry returned:", len(distances))
    print("Nearest line segment distance:", min(distances) if distances else None)
    print("Nearest line endpoint distance:", min(endpoint_distances) if endpoint_distances else None)
    for threshold in (0.01, 0.1, 1, 5, 10, 25, 50, 100):
        print("Lines with some segment within", threshold, "map units:", sum(d<=threshold for d in distances))
    print("Max line segment distance from transformer point:", max(distances) if distances else None)
    for tolerance in (0.01, 0.1, 1, 5):
        nodes = [(x, y)] + [p for _, ends in line_ends for p in ends]
        parent = list(range(len(nodes)))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(a, b):
            parent[find(a)] = find(b)

        for a in range(len(nodes)):
            for b in range(a+1, len(nodes)):
                if math.hypot(nodes[a][0]-nodes[b][0], nodes[a][1]-nodes[b][1]) <= tolerance:
                    union(a, b)
        offset = 1
        line_node_indices = []
        for _, ends in line_ends:
            indices = list(range(offset, offset+len(ends)))
            for index in indices[1:]:
                union(indices[0], index)
            line_node_indices.append(indices)
            offset += len(ends)
        connected = sum(any(find(index) == find(0) for index in indices) for indices in line_node_indices)
        print("Geometry endpoint chain reachable within", tolerance, "meters:", connected, "of", len(line_ends))
        line_parent = list(range(len(line_ends)))

        def line_find(index):
            while line_parent[index] != index:
                line_parent[index] = line_parent[line_parent[index]]
                index = line_parent[index]
            return index

        def line_union(a, b):
            line_parent[line_find(a)] = line_find(b)

        for a, (_, ends_a) in enumerate(line_ends):
            for b in range(a+1, len(line_ends)):
                _, ends_b = line_ends[b]
                segments_a = line_segments[a][1]
                segments_b = line_segments[b][1]
                if (any(segment_distance(*p, *u, *v) <= tolerance for p in ends_a for u, v in segments_b)
                    or any(segment_distance(*p, *u, *v) <= tolerance for p in ends_b for u, v in segments_a)):
                    line_union(a, b)
        roots = {line_find(i) for i, (_, segments) in enumerate(line_segments)
                 if any(segment_distance(x, y, *u, *v) <= tolerance for u, v in segments)}
        chain_count = sum(line_find(i) in roots for i in range(len(line_ends)))
        print("Line chain with endpoint-to-segment taps within", tolerance, "meters:", chain_count, "of", len(line_ends))


if __name__ == "__main__":
    main()
