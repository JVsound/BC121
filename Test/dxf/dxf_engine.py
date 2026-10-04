"""Turns the edges and sketch curves read by sc_common.py (from an open SpaceClaim) into DXF files, view along Z,
1:1 in mm. One DXF per 'sheet' in the dump, named "<sheet name>.dxf", with the origin and axes of that sheet.

Usage: python dxf_engine.py --dump dump.json --src model.scdocx --out-dir folder
(--src is only read for the layer colours.) Run by the three sc_export_*.py scripts, not by hand.

Per part the DXF gets, as LWPOLYLINEs (arcs as bulges) on layer "Layer0":
- the outer contour: the outline of everything the part covers when seen from above, so a bevel or chamfer on the
  outside contributes only its widest edge;
- every edge of a wall perpendicular to the plate (a vertical plane or a cylinder along Z, also a freeform surface that
  stands vertical): cut-outs, holes, steps and pockets. Edges that only bound a sloped or curved face (the inner edge
  of a bevel, a countersink rim, a sloped wall inside the part) are dropped.
Full circles that are wall edges become CIRCLE. Sketch curves go on their own SpaceClaim layer, lines joined to polylines.
"""
import argparse
import json
import math
import os
import re
import xml.etree.ElementTree as ET
import zipfile

import ezdxf
import shapely
from shapely.geometry import MultiLineString, Point
from shapely.ops import linemerge, polygonize, unary_union

SAG = 0.005  # mm, maximum deviation of the polygon from an arc while the outline is computed
GRID = 1e-5  # mm, coordinates are snapped to this grid
TOL_NODE = 2e-3  # mm, end points closer than this are the same corner (SpaceClaim's tolerance is about 1e-4 mm)
LAYER = "Layer0"


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


class Part:
    """Lines, discretised arcs, sampled curves and full circles of one part in mm, seen along Z.

    Every element has a wall flag: it is an edge of a wall perpendicular to the plate."""

    def __init__(self, edges):
        self.lines, self.circles, self.arcs, self.skipped = [], [], [], 0  # lines: [a, b, wall]; circles: [x, y, r, wall]
        node = Nodes([snap(e[k]) for e in edges for k in ("start", "end")])
        seen_lines, seen_arcs, seen_curves = {}, {}, {}
        for e in edges:
            wall = bool(e.get("wall"))
            a, b = node(snap(e["start"])), node(snap(e["end"]))
            if e["type"] == "Line":
                if a == b:
                    continue
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

    def add_arc(self, c, r, a, m, b, wall):
        counter = ccw(a, m, b)
        s, e = math.atan2(a[1] - c[1], a[0] - c[0]), math.atan2(b[1] - c[1], b[0] - c[0])
        sweep = (e - s) % (2 * math.pi) if counter else -((s - e) % (2 * math.pi))
        n = max(2, math.ceil(abs(sweep) / (2 * math.acos(max(0.0, 1 - SAG / r)))))
        pts = [a] + [snap_mm((c[0] + r * math.cos(s + sweep * i / n), c[1] + r * math.sin(s + sweep * i / n)))
                     for i in range(1, n)] + [b]
        arc = {"pts": pts, "counter": counter, "step": abs(sweep) / n, "wall": wall}
        self.arcs.append(arc)
        return arc

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


def add_part(msp, part):
    index = part.arc_index()
    segs = part.segments()
    faces = list(polygonize(unary_union(shapely.set_precision(MultiLineString(segs), GRID)))) if segs else []
    shape = unary_union(faces) if faces else None
    # the outline: the exterior of what the part covers, always one closed polyline per piece
    outline = []
    if shape is not None:
        for poly in (shape.geoms if hasattr(shape, "geoms") else [shape]):
            c = list(poly.exterior.coords)
            outline.append(c)
            msp.add_lwpolyline(to_polyline(c, True, part, index), format="xyb", close=True,
                               dxfattribs={"layer": LAYER})
    # plus the wall edges that are not on the outline (holes, cut-outs, steps); snapped first so that identical
    # edges have identical coordinates
    wall = part.segments(wall_only=True)
    if wall:
        rest = unary_union(shapely.set_precision(MultiLineString(wall), GRID))
        if outline:
            on_outline = unary_union(shapely.set_precision(
                MultiLineString([s for c in outline for s in zip(c, c[1:])]), GRID))
            rest = rest.difference(on_outline)
        merged = linemerge(rest) if not rest.is_empty else rest
        for line in (merged.geoms if hasattr(merged, "geoms") else [merged]):
            if line.is_empty:
                continue
            c = list(line.coords)
            closed = key(c[0]) == key(c[-1])
            pts = to_polyline(c, closed, part, index)
            if len(pts) >= 2:
                msp.add_lwpolyline(pts, format="xyb", close=closed, dxfattribs={"layer": LAYER})
    for cx, cy, r, w in sorted(part.circles):
        if w and (shape is None or shape.buffer(TOL_NODE).contains(Point(cx, cy))):
            msp.add_circle((cx, cy), r, dxfattribs={"layer": LAYER})
    if shape is None and part.circles and not any(c[3] for c in part.circles):
        cx, cy, r, _ = max(part.circles, key=lambda c: c[2])  # a round plate whose edge is not a wall: its widest circle
        msp.add_circle((cx, cy), r, dxfattribs={"layer": LAYER})


def add_sketch(msp, curves):
    """Sketch curves (lines, arcs, circles) of one child: joined into polylines per layer, circles as CIRCLE."""
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
        by_layer.setdefault(cv["layer"] or LAYER, []).append(dict(cv, wall=True))
    for layer, edges in by_layer.items():
        part = Part(edges)
        index = part.arc_index()
        segs = part.segments()
        if segs:
            merged = linemerge(unary_union(shapely.set_precision(MultiLineString(segs), GRID)))
            for line in (merged.geoms if hasattr(merged, "geoms") else [merged]):
                c = list(line.coords)
                closed = key(c[0]) == key(c[-1])
                msp.add_lwpolyline(to_polyline(c, closed, part, index), format="xyb", close=closed,
                                   dxfattribs={"layer": layer})
        for cx, cy, r, _ in part.circles:
            msp.add_circle((cx, cy), r, dxfattribs={"layer": layer})
        if part.skipped:
            print(f"warning: {part.skipped} sketch curves were not converted")


def layer_colors(src):
    """SpaceClaim layer name -> (r, g, b)."""
    with zipfile.ZipFile(src) as z:
        root = ET.fromstring(z.read("SpaceClaim/document.xml"))
    colors = {}
    for e in root.iter():
        if e.tag.rsplit("}", 1)[-1] == "LayerDef":
            kids = {c.tag.rsplit("}", 1)[-1]: c.text for c in e}
            colors[kids["name"]] = tuple(int(v) for v in kids["color"].split(","))
    return colors


def safe(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .")


def main(dump_file, src, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    colors = layer_colors(src)
    with open(dump_file) as f:
        sheets = json.load(f)["sheets"]
    for sheet in sheets:
        doc = ezdxf.new("R2018")
        doc.units = ezdxf.units.MM
        for name in {LAYER} | {cv["layer"] for cv in sheet["sketch"] if cv["layer"]}:
            layer = doc.layers.add(name)
            if name in colors:
                layer.rgb = colors[name]
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
        path = os.path.join(out_dir, safe(sheet["name"]) + ".dxf")
        doc.saveas(path)
        print(f"{path}: {len(sheet['parts'])} parts, {len(msp)} entities" + (f", {skipped} edges skipped" if skipped else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True, help="JSON written by sc_common.py")
    ap.add_argument("--src", required=True, help="the saved .scdocx, for the layer colours")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    main(a.dump, a.src, a.out_dir)
