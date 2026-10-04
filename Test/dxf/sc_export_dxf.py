# SpaceClaim script 1 of 3: a DXF of the open document, in the same folder and with the same name as the .scdocx.
# View along Z, 1:1 in mm: the outline of the parts, their holes, cut-outs and steps, and the sketch curves.
# The document must be saved (the layers are read from the saved file).
import json
import os
import tempfile
import traceback

from System.Diagnostics import Process, ProcessStartInfo


PYTHON = r"C:\Users\Jeroen Vermond\venvs\dxf\Scripts\python.exe"  # Python with ezdxf and shapely
ENGINE = r"D:\GIT\BC121\Test\dxf\dxf_engine.py"  # turns the dump into DXF files


def tf(m, p):
    """Point p through placement m (None = as is), as [x, y, z]."""
    if m is None:
        return [p.X, p.Y, p.Z]
    return [m[r, 0] * p.X + m[r, 1] * p.Y + m[r, 2] * p.Z + m[r, 3] for r in range(3)]


def tv(m, v):
    if m is None:
        return [v.X, v.Y, v.Z]
    return [m[r, 0] * v.X + m[r, 1] * v.Y + m[r, 2] * v.Z for r in range(3)]


def is_wall(face, mid, m):
    """A face perpendicular to the sheet at the point `mid` of its edge, whatever the type of surface.

    A sloped wall does not count: on the outside the outline already follows it, and inside the part it is a design
    mistake that should show up as a missing line."""
    try:
        return abs(tv(m, face.Shape.ProjectPoint(mid).Normal)[2]) < 1e-3
    except Exception:
        g = face.Shape.Geometry
        name = g.GetType().Name
        if name == "Plane":
            return abs(tv(m, g.Frame.DirZ)[2]) < 1e-6
        if name == "Cylinder":
            return abs(abs(tv(m, g.Frame.DirZ)[2]) - 1) < 1e-6
        return False


def edge_mid(shape):
    b = shape.Bounds
    return shape.Geometry.Evaluate((b.Start + b.End) / 2.0).Point


def shape_dict(shape, m):
    """Type, end points and, for circles and arcs, centre, radius, axis and a mid point; other curves as 25 points."""
    g = shape.Geometry
    e = {"type": g.GetType().Name, "start": tf(m, shape.StartPoint), "end": tf(m, shape.EndPoint)}
    if hasattr(g, "Radius"):
        e["radius"] = g.Radius
        e["origin"] = tf(m, g.Frame.Origin)
        e["dirz"] = tv(m, g.Frame.DirZ)
        try:  # a point half-way along the edge fixes which way round an arc goes
            e["mid"] = tf(m, edge_mid(shape))
        except Exception:
            e["mid"] = None
    elif e["type"] != "Line":  # splines and the like: sample them as a polyline
        try:
            b = shape.Bounds
            e["pts"] = [tf(m, g.Evaluate(b.Start + (b.End - b.Start) * i / 24.0).Point) for i in range(25)]
        except Exception:
            e["pts"] = None
    return e


def dump_bodies(name, bodies, m):
    edges = []
    for body in bodies:
        for edge in body.Edges:
            e = shape_dict(edge.Shape, m)
            try:
                mid = edge_mid(edge.Shape)
                e["wall"] = any(is_wall(f, mid, m) for f in edge.Faces)
            except Exception:
                e["wall"] = None
            edges.append(e)
    return {"name": name, "edges": edges}


def dump_sketch(part):
    """Sketch curves of a part: those on its datum planes (with the plane normal) and its loose design curves."""
    curves = []
    for dp in part.DatumPlanes:
        normal = tv(None, dp.Shape.Geometry.Frame.DirZ)
        for cv in dp.Curves:
            d = shape_dict(cv.Shape, None)
            d["layer"] = cv.Layer.Name if cv.Layer else None
            d["construction"] = bool(cv.IsConstruction)
            d["normal"] = normal
            curves.append(d)
    for cv in part.Curves:
        d = shape_dict(cv.Shape, None)
        d["layer"] = cv.Layer.Name if cv.Layer else None
        d["construction"] = bool(cv.IsConstruction)
        d["normal"] = None  # the engine checks that these curves lie in one plane perpendicular to Z
        curves.append(d)
    return curves


def dump_leaves(part):
    """The parts below `part`: one entry per child component (without children of its own)."""
    parts = []
    for c in part.Components:
        if len(list(c.Template.Components)) == 0:
            parts.append(dump_bodies(c.Content.Master.Name, c.Template.Bodies, c.Placement))
        else:
            parts.append({"name": c.Content.Master.Name, "error": "nested components are not supported"})
    return parts


def dump_document(name):
    """The active document as one 'sheet': the bodies of the main part, its child components and its sketch."""
    root = GetRootPart()
    parts = []
    if len(list(root.Bodies)):
        parts.append(dump_bodies(name, root.Bodies, None))
    parts += dump_leaves(root)
    return {"name": name, "parts": parts, "sketch": dump_sketch(root)}


def say(text):
    try:
        Application.ReportStatus(text, StatusMessageType.Information, None)
    except Exception:
        pass
    print(text)


def run_engine(sheets, src, out_dir):
    """Write the dump and run dxf_engine.py on it; -I makes Python ignore PYTHONHOME and the like, which a SpaceClaim
    started from ANSYS may set. Returns (ok, text)."""
    dump = os.path.join(tempfile.gettempdir(), "sc_dxf_dump.json")
    with open(dump, "w") as fh:
        json.dump({"sheets": sheets}, fh)
    info = ProcessStartInfo(PYTHON, '-I "%s" --dump "%s" --src "%s" --out-dir "%s"' % (ENGINE, dump, src, out_dir))
    info.UseShellExecute = False
    info.CreateNoWindow = True
    info.RedirectStandardError = True
    info.RedirectStandardOutput = True
    proc = Process.Start(info)
    out = proc.StandardOutput.ReadToEnd()
    err = proc.StandardError.ReadToEnd()
    proc.WaitForExit()
    return proc.ExitCode == 0, (out if proc.ExitCode == 0 else err)


def saved_path():
    path = Window.ActiveWindow.Document.Path
    if not path:
        say("DXF export: save the document first (the layers are read from the saved file).")
    return path


def export():
    path = saved_path()
    if not path:
        return
    name = os.path.splitext(os.path.basename(path))[0]
    ok, text = run_engine([dump_document(name)], path, os.path.dirname(path))
    say(("DXF written:\n" if ok else "DXF export failed: ") + text)


try:
    export()
except Exception:
    say("DXF export failed: " + traceback.format_exc())
