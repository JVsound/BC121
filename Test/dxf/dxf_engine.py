"""Turns the edges and sketch curves read by sc_common.py (from an open SpaceClaim) into DXF files, view along Z,
1:1 in mm. One DXF per 'sheet' in the dump, named "<sheet name>.dxf", with the origin and axes of that sheet.

Usage: python dxf_engine.py --dump dump.json --src model.scdocx --out-dir folder
(--src is not used at the moment.) Run by the three sc_export_*.py scripts, not by hand.

Three layers: "Basisplaat" (the sheet, from the sketch curves), "Onderdelen" and "Boorgaten" (full circles with a
diameter of 10 mm or less).

Per part the DXF gets, as LWPOLYLINEs (arcs as bulges) on layer "Onderdelen":
- the outer contour: the outline of everything the part covers when seen from above, so a bevel or chamfer on the
  outside contributes only its widest edge;
- every edge of a wall perpendicular to the plate (a vertical plane or a cylinder along Z, also a freeform surface that
  stands vertical): cut-outs, holes, steps and pockets. Edges that only bound a sloped or curved face (the inner edge
  of a bevel, a countersink rim, a sloped wall inside the part) are dropped.
Full circles that are wall edges become CIRCLE. Sketch curves go on "Basisplaat", lines joined to polylines.
"""
import argparse
import json
import math
import os
import re

import ezdxf
import shapely
from shapely.geometry import MultiLineString, Point
from shapely.ops import linemerge, polygonize, unary_union

SAG = 0.005  # mm, maximum deviation of the polygon from an arc while the outline is computed
GRID = 1e-5  # mm, coordinates are snapped to this grid
TOL_NODE = 2e-3  # mm, end points closer than this are the same corner (SpaceClaim's tolerance is about 1e-4 mm)
LAYER_BASE = "Basisplaat"  # the sheet (sketch curves)
LAYER_PARTS = "Onderdelen"  # outlines, cut-outs, steps and pockets of the parts, and holes wider than HOLE_MAX
LAYER_HOLES = "Boorgaten"  # full circles with a diameter of HOLE_MAX or less
HOLE_MAX = 10.0  # mm, diameter


def snap(p):
    return (round(p[0] * 1000 / GRID) * GRID, round(p[1] * 1000 / GRID) * GRID)  # metres -> mm


def snap_mm(p):
    return (round(p[0] / GRID) * GRID, round(p[1] / GRID) * GRID)


def key(p):
    return (round(p[0] / GRID), round(p[1] / GRID))


def ccw(a, b, c):
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) > 0


class Nodes:
    """Merge points closer than TOL_NODE: the end points of the edges of one part differ slightly in SpaceClaim."""

    def __init__(self, points):
        self.cells = {}
        for p in points:
            self(p)

    def __call__(self, p):
        cx, cy = math.floor(p[0] / TOL_NODE), math.floor(p[1] / TOL_NODE)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for r in self.cells.get((cx + dx, cy + dy), []):
                    if math.dist(p, r) < TOL_NODE:
                        return r
        self.cells.setdefault((cx, cy), []).append(p)
        return p


def place(e, node):
    """Where an edge lies in the plan, whatever its height: the edge at the other side of the plate has the same."""
    a, b = node(snap(e["start"])), node(snap(e["end"]))
    if e["type"] == "Circle" and a == b:  # a full circle starts at another point at the other side of the plate
        c = snap(e["origin"])
        return ("Circle", round(c[0], 2), round(c[1], 2), round(e["radius"] * 1000, 2))
    return (e["type"], frozenset((a, b)), round(e.get("radius", 0) * 1000, 1))


def plan_segments(e, node):
    """The edge as line segments in the plan (mm), only to find out which region it encloses."""
    a, b = node(snap(e["start"])), node(snap(e["end"]))
    if e["type"] == "Circle" and a == b:
        c = snap(e["origin"])
        ring = list(Point(c).buffer(e["radius"] * 1000, 16).exterior.coords)
        return list(zip(ring, ring[1:]))
    if e.get("pts"):
        pts = [node(snap(p)) if i in (0, len(e["pts"]) - 1) else snap(p) for i, p in enumerate(e["pts"])]
        return list(zip(pts, pts[1:]))
    if e.get("mid"):
        m = snap(e["mid"])
        return [(a, m), (m, b)]
    return [(a, b)] if a != b else []


def back_walls(edges, node, high):
    """The places (see place()) of walls that belong to milling from the back of the plate (the side at z = 0).

    A wall is milled from the front when it reaches the top of the part (high), or when it stands in the floor of a
    pocket from the front: a hole through that floor runs from the floor level downwards, and is a hole all the same.
    Everything else (a pocket or blind hole that starts at the underside) is left out."""
    eps = 1e-6
    groups = {}
    for e in edges:
        if not e.get("wall"):
            continue
        a, b = node(snap(e["start"])), node(snap(e["end"]))
        if e["type"] != "Circle" and a == b:  # a vertical edge, no length in the plan
            continue
        g = groups.setdefault(place(e, node), {"lo": e["start"][2], "hi": e["start"][2], "edges": []})
        g["lo"] = min(g["lo"], e["start"][2], e["end"][2])
        g["hi"] = max(g["hi"], e["start"][2], e["end"][2])
        g["edges"].append(e)
    # edges that leave a point of the plan vertically or on a slope: (height here, height at the other end)
    leaving = {}
    for e in edges:
        a, b = node(snap(e["start"])), node(snap(e["end"]))
        za, zb = e["start"][2], e["end"][2]
        if e["type"] == "Line" and abs(za - zb) > eps:
            leaving.setdefault(a, []).append((za, zb))
            leaving.setdefault(b, []).append((zb, za))
    # floor level (mm) -> plan segments of the edges at that height that have a wall going up from them: the floor of a
    # pocket from the front, also when the wall at the top lies somewhat further out (a bevelled edge)
    levels = {}
    for e in edges:
        z = e["start"][2]
        if abs(z - e["end"][2]) < eps:
            for p in (node(snap(e["start"])), node(snap(e["end"]))):
                if any(abs(zh - z) < eps and zo > z + eps for zh, zo in leaving.get(p, [])):
                    levels.setdefault(round(z * 1000, 1), []).extend(plan_segments(e, node))
                    break
    regions = {}
    for level, segs in levels.items():
        regions[level] = list(polygonize(unary_union(shapely.set_precision(MultiLineString(segs), GRID))))
    back = set()
    for pl, g in groups.items():
        if g["hi"] >= high - eps:
            continue
        e = g["edges"][0]
        a, b = node(snap(e["start"])), node(snap(e["end"]))
        if e["type"] == "Circle" and a == b:
            p = Point(snap(e["origin"]))
        else:
            m = snap(e["mid"]) if e.get("mid") else ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            p = Point(m)
        if not any(poly.buffer(TOL_NODE).contains(p) for poly in regions.get(round(g["hi"] * 1000, 1), [])):
            back.add(pl)
    return back


class Part:
    """Lines, discretised arcs, sampled curves and full circles of one part in mm, seen along Z.

    Every element has a wall flag: it is an edge of a wall perpendicular to the plate."""

    def __init__(self, edges):
        self.lines, self.circles, self.arcs, self.skipped = [], [], [], 0  # lines: [a, b, wall]; circles: [x, y, r, wall]
        # edges that change height while they run in the plane: where a vertical wall meets a sloped (bevelled) side
        # face; bevel is the longest of them, the width of the bevel seen from above
        self.ramps, self.bevel = set(), 0.0
        # edges at a constant height between the lowest and the highest edge of the part: the floor of a groove or pocket
        self.floors = set()
        heights = [e[k][2] for e in edges for k in ("start", "end")]
        low, high = min(heights), max(heights)
        node = Nodes([snap(e[k]) for e in edges for k in ("start", "end")])
        seen_lines, seen_arcs, seen_curves = {}, {}, {}
        back = back_walls(edges, node, high)
        for e in edges:
            wall = bool(e.get("wall")) and place(e, node) not in back
            a, b = node(snap(e["start"])), node(snap(e["end"]))
            if e["type"] == "Line":
                if a == b:
                    continue
                if abs(e["start"][2] - e["end"][2]) > 1e-6:  # metres
                    self.ramps.add(frozenset((key(a), key(b))))
                    self.bevel = max(self.bevel, math.dist(a, b))
                elif low + 1e-6 < e["start"][2] < high - 1e-6:
                    self.floors.add(frozenset((key(a), key(b))))
                k = frozenset((a, b))  # the edge on the other side of the part is the same
                if k in seen_lines:
                    self.lines[seen_lines[k]][2] |= wall
                else:
                    seen_lines[k] = len(self.lines)
                    self.lines.append([a, b, wall])
            elif e["type"] == "Circle" and abs(abs(e["dirz"][2]) - 1) < 1e-6:
                c, r = snap(e["origin"]), e["radius"] * 1000
                if a == b:
                    for o in self.circles:
                        if math.dist(c, o[:2]) < TOL_NODE and abs(r - o[2]) < TOL_NODE:
                            o[3] |= wall
                            break
                    else:
                        self.circles.append([c[0], c[1], r, wall])
                elif e.get("mid"):
                    m = snap(e["mid"])
                    for om, arc in seen_arcs.setdefault((frozenset((a, b)), round(r, 1)), []):
                        if math.dist(m, om) < 0.05:
                            arc["wall"] |= wall
                            break
                    else:
                        seen_arcs[(frozenset((a, b)), round(r, 1))].append((m, self.add_arc(c, r, a, m, b, wall)))
                else:
                    self.skipped += 1
            elif e.get("pts"):
                pts = [node(snap(p)) if i in (0, len(e["pts"]) - 1) else snap(p) for i, p in enumerate(e["pts"])]
                mid = pts[len(pts) // 2]
                for om, idx in seen_curves.setdefault(frozenset((a, b)), []):  # the same curve on the other side
                    if math.dist(mid, om) < 0.05:
                        for i in idx:
                            self.lines[i][2] |= wall
                        break
                else:
                    idx = []
                    for p, q in zip(pts, pts[1:]):
                        if p != q:
                            idx.append(len(self.lines))
                            self.lines.append([p, q, wall])
                    seen_curves[frozenset((a, b))].append((mid, idx))
            else:
                self.skipped += 1
        self.merge_arcs()

    def add_arc(self, c, r, a, m, b, wall):
        counter = ccw(a, m, b)
        s, e = math.atan2(a[1] - c[1], a[0] - c[0]), math.atan2(b[1] - c[1], b[0] - c[0])
        sweep = (e - s) % (2 * math.pi) if counter else -((s - e) % (2 * math.pi))
        arc = {"c": c, "r": r, "counter": counter, "wall": wall, "a": a, "b": b, "s": s, "sweep": sweep}
        self.arcs.append(arc)
        self.discretise(arc)
        return arc

    @staticmethod
    def discretise(arc):
        c, r, s, sweep = arc["c"], arc["r"], arc["s"], arc["sweep"]
        n = max(2, math.ceil(abs(sweep) / (2 * math.acos(max(0.0, 1 - SAG / r)))))
        arc["pts"] = [arc["a"]] + [snap_mm((c[0] + r * math.cos(s + sweep * i / n), c[1] + r * math.sin(s + sweep * i / n)))
                                   for i in range(1, n)] + [arc["b"]]
        arc["step"] = abs(sweep) / n

    def merge_arcs(self):
        """Arcs on one circle (same centre, radius and wall flag) that overlap or touch become one arc.

        SpaceClaim gives the bottom edge, the top edge and the floor of a groove of one cylindrical wall as separate
        arcs; discretised apart they do not coincide, which leaves slivers and loose fragments."""
        groups = {}
        for arc in self.arcs:
            groups.setdefault((round(arc["c"][0], 2), round(arc["c"][1], 2), round(arc["r"], 2), arc["wall"]), []).append(arc)
        merged = []
        for arcs in groups.values():
            ivs = []  # [lo, hi, point at lo, point at hi], counter-clockwise from lo to hi
            for arc in arcs:
                lo, hi = (arc["s"], arc["s"] + arc["sweep"]) if arc["counter"] else (arc["s"] + arc["sweep"], arc["s"])
                p_lo, p_hi = (arc["a"], arc["b"]) if arc["counter"] else (arc["b"], arc["a"])
                shift = math.floor(lo / (2 * math.pi)) * 2 * math.pi
                ivs.append([lo - shift, hi - shift, p_lo, p_hi])
            ivs.sort(key=lambda v: v[0])
            eps = TOL_NODE / arcs[0]["r"]
            out = [ivs[0]]
            for iv in ivs[1:]:
                if iv[0] <= out[-1][1] + eps:
                    if iv[1] > out[-1][1]:
                        out[-1][1], out[-1][3] = iv[1], iv[3]
                else:
                    out.append(iv)
            if len(out) > 1 and out[0][0] + 2 * math.pi <= out[-1][1] + eps:  # runs through the angle 0
                out[0][0], out[0][2] = out[-1][0] - 2 * math.pi, out[-1][2]
                out[0][1] = max(out[0][1], out[-1][1] - 2 * math.pi)
                out.pop()
            for lo, hi, p_lo, p_hi in out:
                arc = dict(arcs[0], counter=True, a=p_lo, b=p_hi, s=lo, sweep=hi - lo)
                self.discretise(arc)
                merged.append(arc)
        self.arcs = merged

    def segments(self, wall_only=False):
        segs = [(a, b) for a, b, w in self.lines if w or not wall_only]
        for arc in self.arcs:
            if arc["wall"] or not wall_only:
                segs += list(zip(arc["pts"], arc["pts"][1:]))
        return segs

    def arc_index(self):
        """Map a vertex to the (arc number, index along the arc) pairs it belongs to."""
        index = {}
        for i, arc in enumerate(self.arcs):
            for j, p in enumerate(arc["pts"]):
                index.setdefault(key(p), []).append((i, j))
        return index


def to_polyline(coords, closed, part, index):
    """Vertices (x, y, bulge) of a line or ring, with runs of arc vertices merged back into bulge segments."""
    pts = [snap_mm(p) for p in (coords[:-1] if closed else coords)]
    n = len(pts)
    nseg = n if closed else n - 1

    def arc_step(i):  # (arc, direction) when pts[i] -> pts[i+1] runs along one discretised arc
        for ai, ji in index.get(key(pts[i]), []):
            for aj, jj in index.get(key(pts[(i + 1) % n]), []):
                if ai == aj and abs(ji - jj) == 1:
                    return ai, jj - ji
        return None

    steps = [arc_step(i) for i in range(nseg)]
    start = next((i for i in range(nseg) if steps[i - 1] != steps[i] or steps[i] is None), 0) if closed else 0
    out, i, done = [], start, 0
    while done < nseg:
        s = steps[i % nseg]
        k = 1
        if s is not None:
            while done + k < nseg and steps[(i + k) % nseg] == s:
                k += 1
        a = pts[i % n]
        bulge = 0.0
        if s is not None:
            arc = part.arcs[s[0]]
            bulge = math.tan(k * arc["step"] / 4) * (1 if arc["counter"] == (s[1] > 0) else -1)
        out.append((a[0], a[1], bulge))
        i, done = i + k, done + k
    if not closed:
        out.append((pts[-1][0], pts[-1][1], 0.0))
    # merge straight vertices that lie on one line
    res = []
    for j, (x, y, bg) in enumerate(out):
        if not closed and j in (0, len(out) - 1):
            res.append((x, y, bg))
            continue
        px, py, pbg = out[j - 1]
        nx, ny, _ = out[(j + 1) % len(out)]
        if bg == 0 and pbg == 0 and abs((x - px) * (ny - y) - (y - py) * (nx - x)) < 1e-6 * max(
                1.0, math.dist((px, py), (nx, ny))) and (x - px) * (nx - x) + (y - py) * (ny - y) > 0:
            continue
        res.append((x, y, bg))
    return res


def bridge_notches(ring, part):
    """Closed ring (first point repeated) without the dents that a bevelled edge gets from a groove.

    A groove or pocket that runs out at a bevelled edge leaves a dent of a fraction of a millimetre in the outline
    (the edge is cut at the depth of the groove floor, where the bevel lies further in). The edge itself runs on
    straight, so such a dent is bridged: a chain of vertices that leaves a straight edge to the inside, comes back
    onto the same line, is no deeper than the bevel is wide, whose first and last edge are bevel edges (they change
    height, see Part.ramps) and whose bottom is the floor of a groove (Part.floors). Nothing happens on a part without
    a bevel; dents to the outside (tabs) and through-cuts stay."""
    pts = ring[:-1]
    if not part.ramps:
        return ring
    area =sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    side = 1 if area > 0 else -1  # +1: the inside is on the left of the walking direction
    changed = True
    while changed and len(pts) > 4:
        changed = False
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            length = math.dist(a, b)
            if length < 1:
                continue
            d = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)

            def off(p):  # distance of p from the line through a and b, positive to the inside
                return side * (d[0] * (p[1] - a[1]) - d[1] * (p[0] - a[0]))

            for k in range(2, min(9, n - 2)):
                e, f = pts[(i + k) % n], pts[(i + k + 1) % n]
                length_ef = math.dist(e, f)
                if length_ef < 1 or abs(off(e)) > 1e-3 or abs(off(f)) > 1e-3:
                    continue
                if (f[0] - e[0]) * d[0] + (f[1] - e[1]) * d[1] <= 0:
                    continue  # the second edge does not carry on in the same direction
                chain = [off(pts[(i + m) % n]) for m in range(1, k)]

                def seg(j):  # the edge from vertex j to the next one
                    return frozenset((key(pts[j % n]), key(pts[(j + 1) % n])))

                if (max(chain) <= part.bevel + 1e-3 and min(chain) >= -1e-3 and max(chain) > 1e-3
                        and seg(i + 1) in part.ramps and seg(i + k - 1) in part.ramps
                        and all(seg(j) in part.floors for j in range(i + 2, i + k - 1))):
                    drop = {(i + m) % n for m in range(1, k + 1)}
                    pts = [p for j, p in enumerate(pts) if j not in drop]
                    changed = True
                    break
            if changed:
                break
    return pts + pts[:1]


def add_part(msp, part):
    index = part.arc_index()
    segs = part.segments()
    faces = list(polygonize(unary_union(shapely.set_precision(MultiLineString(segs), GRID)))) if segs else []
    shape = unary_union(faces) if faces else None
    # the outline: the exterior of what the part covers, always one closed polyline per piece
    outline = []
    if shape is not None:
        for poly in (shape.geoms if hasattr(shape, "geoms") else [shape]):
            c = bridge_notches(list(poly.exterior.coords), part)
            outline.append(c)
            msp.add_lwpolyline(to_polyline(c, True, part, index), format="xyb", close=True,
                               dxfattribs={"layer": LAYER_PARTS})
    # plus the wall edges that are not on the outline (holes, cut-outs, steps); snapped first so that identical
    # edges have identical coordinates
    wall = part.segments(wall_only=True)
    if wall:
        rest = unary_union(shapely.set_precision(MultiLineString(wall), GRID))
        if outline:
            on_outline = unary_union(shapely.set_precision(
                MultiLineString([s for c in outline for s in zip(c, c[1:])]), GRID))
            rest = rest.difference(on_outline)
        merged = rest if rest.is_empty or rest.geom_type == "LineString" else linemerge(rest)
        for line in (merged.geoms if hasattr(merged, "geoms") else [merged]):
            if line.is_empty:
                continue
            c = list(line.coords)
            closed = key(c[0]) == key(c[-1])
            pts = to_polyline(c, closed, part, index)
            if len(pts) >= 2:
                msp.add_lwpolyline(pts, format="xyb", close=closed, dxfattribs={"layer": LAYER_PARTS})
    for cx, cy, r, w in sorted(part.circles):
        if w and (shape is None or shape.buffer(TOL_NODE).contains(Point(cx, cy))):
            msp.add_circle((cx, cy), r, dxfattribs={"layer": LAYER_HOLES if 2 * r <= HOLE_MAX + TOL_NODE else LAYER_PARTS})
    if shape is None and part.circles and not any(c[3] for c in part.circles):
        cx, cy, r, _ = max(part.circles, key=lambda c: c[2])  # a round plate whose edge is not a wall: its widest circle
        msp.add_circle((cx, cy), r, dxfattribs={"layer": LAYER_PARTS})


def add_sketch(msp, curves):
    """Sketch curves (lines, arcs, circles) of one child, all on the layer of the sheet: joined into polylines,
    circles as CIRCLE."""
    by_layer = {}
    zs = {round(p[2], 7) for cv in curves if cv.get("normal") is None for p in (cv["start"], cv["end"])}
    for cv in curves:
        if cv.get("normal") is not None:
            flat = abs(abs(cv["normal"][2]) - 1) < 1e-6  # drawn on a plane perpendicular to Z
        else:
            flat = len(zs) == 1  # loose curves: all at one height
        if not flat:
            print("skipped a sketch curve that does not lie in a plane perpendicular to Z")
            continue
        by_layer.setdefault(LAYER_BASE, []).append(dict(cv, wall=True))
    for layer, edges in by_layer.items():
        part = Part(edges)
        index = part.arc_index()
        segs = part.segments()
        if segs:
            merged = unary_union(shapely.set_precision(MultiLineString(segs), GRID))
            if merged.geom_type != "LineString":
                merged = linemerge(merged)
            for line in (merged.geoms if hasattr(merged, "geoms") else [merged]):
                c = list(line.coords)
                closed = key(c[0]) == key(c[-1])
                msp.add_lwpolyline(to_polyline(c, closed, part, index), format="xyb", close=closed,
                                   dxfattribs={"layer": layer})
        for cx, cy, r, _ in part.circles:
            msp.add_circle((cx, cy), r, dxfattribs={"layer": layer})
        if part.skipped:
            print(f"warning: {part.skipped} sketch curves were not converted")


def safe(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .")


def main(dump_file, src, out_dir, suffix=""):
    os.makedirs(out_dir, exist_ok=True)
    with open(dump_file) as f:
        sheets = json.load(f)["sheets"]
    for sheet in sheets:
        doc = ezdxf.new("R2018")
        doc.units = ezdxf.units.MM
        for name in (LAYER_BASE, LAYER_PARTS, LAYER_HOLES):
            doc.layers.add(name).rgb = (0, 0, 0)  # all lines black
        doc.layers.discard("Defpoints")
        msp = doc.modelspace()
        skipped = 0
        add_sketch(msp, sheet["sketch"])
        for p in sheet["parts"]:
            if "edges" not in p:
                print(f"{sheet['name']}: {p['name']}: {p['error']}")
                continue
            part = Part(p["edges"])
            skipped += part.skipped
            add_part(msp, part)
        path = os.path.join(out_dir, safe(sheet["name"] + suffix) + ".dxf")
        doc.saveas(path)
        print(f"{path}: {len(sheet['parts'])} parts, {len(msp)} entities" + (f", {skipped} edges skipped" if skipped else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True, help="JSON written by sc_common.py")
    ap.add_argument("--src", required=True, help="the saved .scdocx (not used at the moment)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--suffix", default="", help="added to every file name, e.g. _2026-10-19")
    a = ap.parse_args()
    main(a.dump, a.src, a.out_dir, a.suffix)
