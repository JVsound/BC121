# SpaceClaim script (IronPython): export the active document to a DXF next to the .scdocx.
# Run it from the Script panel (Design tab > Script) or with the Script > Run Script button.
# The document must be saved: layers and sketch are read from the saved file, the solid edges from the open model.
import json
import os
import tempfile
import traceback

from System.Diagnostics import Process, ProcessStartInfo

PYTHON = r"C:\Users\Jeroen Vermond\venvs\dxf\Scripts\python.exe"
CONVERTER = r"D:\GIT\BC121\Test\dxf\design2dxf.py"
AXIS = "z"  # view direction: "z" = plan view (X right, Y up), "x" = Design tab view along X, "y" = X right, Z up


def say(text):
    try:
        Application.ReportStatus(text, StatusMessageType.Information, None)
    except Exception:
        pass
    print(text)


def pt(p):
    return [p.X, p.Y, p.Z]


def export():
    path = Window.ActiveWindow.Document.Path
    if not path:
        say("DXF export: save the document first.")
        return
    edges = []
    for body in GetRootPart().Bodies:
        for edge in body.Edges:
            c = edge.Shape.Geometry
            e = {"type": c.GetType().Name, "start": pt(edge.Shape.StartPoint), "end": pt(edge.Shape.EndPoint)}
            if hasattr(c, "Radius"):
                e["radius"] = c.Radius
                e["origin"] = pt(c.Frame.Origin)
                e["dirz"] = [c.Frame.DirZ.X, c.Frame.DirZ.Y, c.Frame.DirZ.Z]
            edges.append(e)
    tmp = os.path.join(tempfile.gettempdir(), "sc_edges.json")
    with open(tmp, "w") as fh:
        json.dump({"edges": edges}, fh)
    dxf = os.path.splitext(path)[0] + ".dxf"
    info = ProcessStartInfo(PYTHON, '"%s" "%s" "%s" "%s" --axis %s' % (CONVERTER, path, dxf, tmp, AXIS))
    info.UseShellExecute = False
    info.CreateNoWindow = True
    info.RedirectStandardError = True
    proc = Process.Start(info)
    err = proc.StandardError.ReadToEnd()
    proc.WaitForExit()
    say("DXF written: " + dxf if proc.ExitCode == 0 else "DXF export failed: " + err)


try:
    export()
except Exception:
    say("DXF export failed: " + traceback.format_exc())
