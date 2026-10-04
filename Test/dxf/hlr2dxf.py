"""Convert the hidden-line geometry of a SpaceClaim drawing (.scdocx) to DXF.

Usage: python hlr2dxf.py SpaceClaimDXFtest.scdocx [out.dxf]
Reads SpaceClaim/Graphics/hlr.xml and writes the object lines 1:1 in millimetres. The views keep their relative
layout (sheet offsets divided by the sheet scale); the lower-left of the drawing is moved to the origin.
No sheet border; dimensions and notes are not converted.
"""
import math
import sys
import zipfile
import xml.etree.ElementTree as ET

import ezdxf
from ezdxf import bbox

SCALE = 0.1  # sheet scale from document.xml; only used to space the views at full size


def floats(text):
    return [float(v) for v in text.replace(",", " ").split()]


def view_offset(model_transform):
    """Row-major 4x4 with the homogeneous weight in the last row: the weight carries the scale."""
    m = floats(model_transform)
    w = m[15]
    return m[3] / w, m[7] / w


def chains(positions, indices):
    """Join index pairs into polylines; returns lists of points."""
    pts = [tuple(positions[i:i + 3]) for i in range(0, len(positions), 3)]
    segs = list(zip(indices[0::2], indices[1::2]))
    out, cur = [], []
    for a, b in segs:
        if cur and cur[-1] == a:
            cur.append(b)
        else:
            if cur:
                out.append(cur)
            cur = [a, b]
    if cur:
        out.append(cur)
    return [[pts[i] for i in c] for c in out]


def add_chain(msp, pts, dx, dy, layer):
    p = [((x + dx / SCALE) * 1000, (y + dy / SCALE) * 1000) for x, y, _ in pts]
    closed = len(p) > 3 and math.dist(p[0], p[-1]) < 1e-9
    if closed:
        p = p[:-1]
        cx = sum(x for x, _ in p) / len(p)
        cy = sum(y for _, y in p) / len(p)
        r = [math.dist((cx, cy), q) for q in p]
        if max(r) - min(r) < 1e-6 * max(r):
            msp.add_circle((cx, cy), r[0], dxfattribs={"layer": layer})
            return
    if len(p) == 2:
        msp.add_line(p[0], p[1], dxfattribs={"layer": layer})
    else:
        msp.add_lwpolyline(p, close=closed, dxfattribs={"layer": layer})


def main(src, dst):
    with zipfile.ZipFile(src) as z:
        root = ET.fromstring(z.read("SpaceClaim/Graphics/hlr.xml"))
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.MM
    doc.layers.add("VISIBLE", color=7)
    doc.layers.add("HIDDEN", color=8, linetype="DASHED")
    msp = doc.modelspace()
    for view in root.iter("View"):
        dx, dy = view_offset(view.get("ModelTransform"))
        for item in view.iter("Item"):
            for kind, layer in (("Visible", "VISIBLE"), ("Hidden", "HIDDEN")):
                for node in item.findall(kind):
                    for ll in node.iter("LineList"):
                        pos, idx = floats(ll.get("Positions")), [int(v) for v in ll.get("Indices").split()]
                        for c in chains(pos, idx):
                            add_chain(msp, c, dx, dy, layer)
    box = bbox.extents(msp)
    for e in msp:
        e.translate(-box.extmin.x, -box.extmin.y, 0)
    doc.saveas(dst)
    print(f"{dst}: {len(msp)} entities")


if __name__ == "__main__":
    s = sys.argv[1]
    main(s, sys.argv[2] if len(sys.argv) > 2 else s.rsplit(".", 1)[0] + ".dxf")

