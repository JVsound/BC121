"""Write a view of the solids plus the part sketch of a .scdocx as a 1:1 DXF in mm.

Usage: python design2dxf.py in.scdocx out.dxf [edges.json] [--axis x|y|z]
The view looks along the given axis (default x). x is the Design tab view (Y to the left, Z up), y has X to the
right and Z up, z is the plan view with X to the right and Y up. A sketch is only included when it lies in a plane
perpendicular to that axis. The outline of curved surfaces (e.g. the side of a cylinder) is not an edge in
SpaceClaim, so it does not appear.
Without edges.json the solid edges are read by running SpaceClaim headless with sc_dump_edges.py (about 25 s);
sc_export_dxf.py instead runs inside an open SpaceClaim and passes edges.json. The student version allows both,
so circles, holes and their diameters come straight from the model. Edges on the solid go to SpaceClaim layer
"Layer0" (the default layer). Sketch lines are read from document.xml with their layer name and colour.
Circles and lines are checked; arcs are implemented but not yet tested.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import ezdxf

SPACECLAIM = r"C:\Program Files\ANSYS Inc\ANSYS Student\v261\scdm\SpaceClaim.exe"
DUMP_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sc_dump_edges.py")
TOL = 1e-6  # mm, end points closer than this count as connected
DEFAULT_LAYER = "0:9"  # layer id SpaceClaim gives to Layer0, which holds the solid


def solid_edges(src):
    """Run SpaceClaim headless and return the dumped edges (metres, model coordinates)."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, "edges.json")
        script = os.path.join(tmp, "dump.py")
        with open(DUMP_SCRIPT) as f:
            text = f.read().replace("@SRC@", os.path.abspath(src)).replace("@DST@", dst)
        with open(script, "w") as f:
            f.write(text)
        # one command-line string: a list would make Python escape the quotes SpaceClaim expects around the path
        subprocess.run(f'"{SPACECLAIM}" /RunScript="{script}" /ExitAfterScript=True /Splash=False /Welcome=False',
                       check=True, timeout=120)
        with open(dst) as f:
            log = json.load(f)
    if log["error"]:
        raise RuntimeError(log["error"])
    return log["edges"]


# view axis -> (index of DXF x, its sign, index of DXF y, its sign, handedness of x cross y relative to +axis)
VIEWS = {
    "x": (1, -1, 2, 1, -1),  # Design tab view along X: Y to the left, Z up
    "y": (0, 1, 2, 1, -1),   # X to the right, Z up
    "z": (0, 1, 1, 1, 1),    # plan view: X to the right, Y up
}
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def project(p, axis):
    """Metres in model coordinates -> mm in the DXF plane of the view along `axis`."""
    iu, su, iv, sv, _ = VIEWS[axis]
    return (su * p[iu] * 1000, sv * p[iv] * 1000)


def add_edges(msp, edges, layer, axis):
    """Project the edges along `axis`; coincident edges (front and back face) are added once.

    Only circles perpendicular to the view and straight lines are converted; other edges are counted and reported."""
    seen = set()
    k, handed = AXIS_INDEX[axis], VIEWS[axis][4]
    skipped = 0

    def p2(p):
        return project(p, axis)

    for e in edges:
        a, b = p2(e["start"]), p2(e["end"])
        if e["type"] == "Circle" and abs(abs(e["dirz"][k]) - 1) < 1e-9:
            c, r = p2(e["origin"]), e["radius"] * 1000
            if math.dist(a, b) < TOL:
                key = ("c", round(c[0], 4), round(c[1], 4), round(r, 4))
                if key not in seen:
                    seen.add(key)
                    msp.add_circle(c, r, dxfattribs={"layer": layer})
            else:
                start, end = (a, b) if e["dirz"][k] * handed > 0 else (b, a)  # arcs run counter-clockwise
                key = ("a", round(c[0], 4), round(c[1], 4), round(r, 4), round(start[0], 4), round(start[1], 4),
                       round(end[0], 4), round(end[1], 4))
                if key not in seen:
                    seen.add(key)
                    msp.add_arc(c, r, math.degrees(math.atan2(start[1] - c[1], start[0] - c[0])),
                                math.degrees(math.atan2(end[1] - c[1], end[0] - c[0])),
                                dxfattribs={"layer": layer})
        elif e["type"].startswith("Line"):
            if math.dist(a, b) > TOL:  # a line along the view axis projects to a point
                key = ("l",) + tuple(sorted((tuple(round(v, 4) for v in a), tuple(round(v, 4) for v in b))))
                if key not in seen:
                    seen.add(key)
                    msp.add_line(a, b, dxfattribs={"layer": layer})
        else:
            skipped += 1  # splines, ellipses, circles that are not perpendicular to the view, ...
    if skipped:
        print(f"warning: {skipped} edges (not lines or circles perpendicular to the view) were not converted")


def rgb(text):
    return tuple(int(v) for v in text.split(","))


def floats(text):
    return [float(v) for v in text.split()]


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child(e, name):
    """Child element by local name (the XML uses default namespaces such as urn:sketch)."""
    return next(c for c in e if local(c.tag) == name)


def same(a, b):
    return abs(a[0] - b[0]) < TOL and abs(a[1] - b[1]) < TOL


def join(segs):
    """Chain line segments whose end points coincide; returns point lists (a closed chain repeats its first point)."""
    todo, chains = list(segs), []
    while todo:
        pts = list(todo.pop(0))
        grown = True
        while grown and not same(pts[0], pts[-1]):
            grown = False
            for s in todo:
                for a, b in (s, s[::-1]):
                    if same(a, pts[-1]):
                        pts.append(b)
                    elif same(b, pts[0]):
                        pts.insert(0, a)
                    else:
                        continue
                    todo.remove(s)
                    grown = True
                    break
                if grown:
                    break
        chains.append(pts)
    return chains


def sketch_segments(root, names, axis):
    """Sketch lines per layer name, projected along `axis`. A sketch whose curves do not all lie in one plane
    perpendicular to the view (they have different coordinates along the axis) is skipped."""
    k = AXIS_INDEX[axis]
    segments = {}
    for box in root.iter():
        if local(box.tag) != "PartSketchCurveContainerDef":
            continue
        found, planes = [], set()
        for e in box:
            if local(e.tag) != "SketchCurveDef":
                continue
            curve = child(e, "curve")
            if not curve.get("sctype").startswith("SpaceClaim.Geometry.LineSegment"):
                print("skipped", curve.get("sctype"))
                continue
            s, d = floats(child(curve, "start").text), floats(child(curve, "dir").text)
            n = float(child(curve, "length").text)
            q = [[s[i] + t * n * d[i] for i in range(3)] for t in (0, 1)]
            planes.update(round(p[k], 9) for p in q)
            found.append((names[child(e, "layerId").text], project(q[0], axis), project(q[1], axis)))
        if len(planes) > 1:
            print(f"skipped a sketch that is not perpendicular to the {axis.upper()} view")
            continue
        for layer, a, b in found:
            segments.setdefault(layer, []).append((a, b))
    return segments


def main(src, dst, edges_file=None, axis="x"):
    with zipfile.ZipFile(src) as z:
        root = ET.fromstring(z.read("SpaceClaim/document.xml"))
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.MM
    names = {}
    for e in root.iter():
        if local(e.tag) == "LayerDef":
            names[e.get("Id")] = child(e, "name").text
            layer = doc.layers.add(names[e.get("Id")])
            layer.rgb = rgb(child(e, "color").text)
    msp = doc.modelspace()
    if edges_file:  # edges dumped by sc_export_dxf.py from the open SpaceClaim session
        with open(edges_file) as f:
            edges = json.load(f)["edges"]
    else:
        edges = solid_edges(src)
    add_edges(msp, edges, names[DEFAULT_LAYER], axis)
    for layer, segs in sketch_segments(root, names, axis).items():
        for pts in join(segs):
            if len(pts) == 2:
                msp.add_line(pts[0], pts[1], dxfattribs={"layer": layer})
            else:
                closed = same(pts[0], pts[-1])
                msp.add_lwpolyline(pts[:-1] if closed else pts, close=closed, dxfattribs={"layer": layer})
    doc.layers.discard("Defpoints")  # added by ezdxf by default; unused here
    doc.saveas(dst)
    print(f"{dst}: {len(msp)} entities, layers {sorted(names.values())}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("edges", nargs="?", help="edges.json from sc_export_dxf.py; omit to run SpaceClaim headless")
    ap.add_argument("--axis", choices=sorted(VIEWS), default="x", help="view direction (default x)")
    a = ap.parse_args()
    main(a.src, a.dst, a.edges, a.axis)
