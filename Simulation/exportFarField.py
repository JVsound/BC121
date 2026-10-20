# Run this in Mechanical (IronPython): Automation tab > Scripting > open this file > Run. Or headless, from a Workbench
# journal: define OUT_DIR (and optionally ANALYSIS_NAMES) first and then run this file with exec.
# It exports every far-field result (Far-field Maximum Pressure ..., Far-field Phase ...) and every frequency response
# result under the Solution of the chosen analyses to a text file named after the result, in OUT_DIR.
# readFarField(OUT_DIR) reads the far-field files in MATLAB. Name the far-field results "Far-field Maximum Pressure
# <name>" and "Far-field Phase <name>" with the same <name> per microphone, for example "Mic5m". Nothing in the model is
# changed, only the results are evaluated.
import os
import traceback

try:
    OUT_DIR
except NameError:
    OUT_DIR = r"D:\GIT\BC121\Simulation\MeshStudy\175 mm"  # Folder of this mesh; change it per analysis
try:
    ANALYSIS_NAMES
except NameError:
    ANALYSIS_NAMES = []  # Names of the analyses to export, for example ["Harmonic Acoustics 2"]; empty is all analyses
TYPES = ("FarField", "FrequencyResponse")  # Parts of the type names of the results to export

if not os.path.isdir(OUT_DIR):
    os.makedirs(OUT_DIR)
log = []


def say(text):
    log.append(text)
    print(text)


def safe(name):
    return "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in name).strip()


try:
    model = ExtAPI.DataModel.Project.Model
    exported = 0
    for analysis in model.Analyses:
        if ANALYSIS_NAMES and analysis.Name not in ANALYSIS_NAMES:
            continue
        say("Analysis: %s" % analysis.Name)
        children = list(analysis.Solution.Children)
        for child in children:
            say("   %s | %s" % (child.Name, child.GetType().Name))
        results = [c for c in children if any(t in c.GetType().Name for t in TYPES)]
        say("   results to export: %d" % len(results))
        if not results:
            continue
        try:
            analysis.Solution.EvaluateAllResults()
        except Exception as err:
            say("   EvaluateAllResults: %s" % err)
        for result in results:
            path = os.path.join(OUT_DIR, safe(result.Name) + ".txt")
            try:
                result.ExportToTextFile(path)
                ok = os.path.isfile(path)
                say("   %s -> %s" % (result.Name, "written" if ok else "no file"))
                exported += int(ok)
            except Exception as err:
                say("   %s: export failed: %s" % (result.Name, err))
    say("Exported %d files to %s" % (exported, OUT_DIR))
except Exception:
    say(traceback.format_exc())

with open(os.path.join(OUT_DIR, "exportFarField_log.txt"), "w") as fh:
    fh.write("\n".join(log))
