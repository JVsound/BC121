# SpaceClaim script (IronPython): dump the edges of the solids of a document to JSON.
# design2dxf.py copies this file, fills in SRC and DST and runs it with
# SpaceClaim.exe /RunScript=<copy> /ExitAfterScript=True
import json
import traceback

SRC = r"@SRC@"
DST = r"@DST@"
log = {"edges": [], "error": None}


def pt(p):
    return [p.X, p.Y, p.Z]


try:
    DocumentOpen.Execute(SRC)
    for body in GetRootPart().Bodies:
        for edge in body.Edges:
            c = edge.Shape.Geometry
            e = {"type": c.GetType().Name, "start": pt(edge.Shape.StartPoint), "end": pt(edge.Shape.EndPoint)}
            if hasattr(c, "Radius"):
                e["radius"] = c.Radius
                e["origin"] = pt(c.Frame.Origin)
                e["dirz"] = [c.Frame.DirZ.X, c.Frame.DirZ.Y, c.Frame.DirZ.Z]
            log["edges"].append(e)
except Exception:
    log["error"] = traceback.format_exc()

with open(DST, "w") as fh:
    json.dump(log, fh)
