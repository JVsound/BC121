%[text] # DXF Export from SpaceClaim
%[text] **J.G. Vermond, JVsound**
%[text] How to create DXF files from a SpaceClaim model with three scripts: one DXF of the open document, or one DXF for each component in the component `Nesting`, next to the model or in a folder of your choice. Status of 2026-10-04.
%%
%[text] ## Overview
%[text] The three scripts run inside SpaceClaim. Each one reads the edges and the sketch curves of the open document and writes them to a JSON file. It then starts `dxf_engine.py`, which runs in a separate Python and writes the DXF files, so SpaceClaim itself never needs the DXF libraries. The scripts and `dxf_engine.py` are in `Test\dxf` of the project `BC121`.
%[text:table]{"columnWidths":[260,-1]}
%[text] | Script | Result |
%[text] | --- | --- |
%[text] | `sc_export_dxf.py` | One DXF of the open document, in the same folder and with the same name as the `.scdocx`. |
%[text] | `sc_export_nesting_same_folder.py` | One DXF for each child component of `Nesting`, named after that component, in the same folder as the model. |
%[text] | `sc_export_nesting_choose_folder.py` | The same, but a dialog asks for the folder. It starts in the folder used last time. |
%[text:table]
%%
%[text] ## Computer setup
%[text:table]{"columnWidths":[160,-1]}
%[text] | Item | Value |
%[text] | --- | --- |
%[text] | SpaceClaim | Ansys Student 2026 R1 (v261); the student version runs scripts and allows the export. |
%[text] | Python | 3.13 from python.org, virtual environment `C:\Users\Jeroen Vermond\venvs\dxf` |
%[text] | Packages | `ezdxf` and `shapely` in that environment |
%[text] | Files | `D:\GIT\BC121\Test\dxf`; the paths `PYTHON` and `ENGINE` are at the top of each script |
%[text:table]
%[text] If a file or the environment moves, change `PYTHON` and `ENGINE` at the top of the three scripts.
%%
%[text] ## Working method
%[text] 1. Save the document. The layer names and colors are read from the saved file.
%[text] 2. Run the script from the Script panel of SpaceClaim, or from a ribbon button that you have linked to the script file.
%[text] 3. Read the result in the status line of SpaceClaim: the DXF files that were written, or the error.
%[text] 4. For the third script, choose the folder in the dialog. With `FOLDER = r"..."` at the top of the script the dialog is skipped and that folder is always used. \
%%
%[text] ## What is in the DXF
%[text] - The view is along the Z axis of the document, 1:1 in mm. A DXF of a component has the origin and the axes of that component.
%[text] - Per part the outer contour, as one closed `LWPOLYLINE`. A bevel or chamfer on the outside contributes only its widest edge.
%[text] - Every edge of a wall perpendicular to the plate: holes, cut-outs, steps and pockets. Walls that are perpendicular but freeform are included. Arcs are kept as arcs (bulges) and full circles as `CIRCLE`.
%[text] - Three layers, for the milling shop: `Basisplaat` (the sheet, from the sketch curves, lines that connect become one polyline), `Onderdelen` (outlines, cut-outs, steps, pockets and holes wider than 10 mm) and `Boorgaten` (full circles of 10 mm diameter or less).
%[text] - Everything else is left out: lines inside a face, the inner edge of a bevel, a countersink rim, and a sloped wall inside the part. \
%%
%[text] ## What was found
%[text] - A sloped wall inside a part is left out on purpose. It then shows up as a missing line, which points at a mistake in the design. A sloped wall on the outside is followed by the outer contour.
%[text] - A groove or pocket that runs out at a bevelled edge cuts the outline back by a fraction of a millimeter. `dxf_engine.py` bridges such a dent, but only on a bevelled edge: the dent goes inward, the edge carries on in the same line, the sides of the dent are bevel edges (they change height), its bottom is a groove floor and it is no deeper than the bevel is wide. The edge stays straight; the walls of the groove still run up to it. Square edges and through-cuts are never touched.
%[text] - A part of a component that itself has components is not supported; the script reports it and skips it.
%[text] - Whether a hole goes through or is blind cannot be seen in the edges, so both are written. Concentric circles, such as a countersink, are written as well.
%[text] - The end points of the edges of one part differ by about 0.0001 mm in SpaceClaim. `dxf_engine.py` merges points closer than 0.002 mm, otherwise the contours do not close.
%[text] - A dialog inside the script thread of SpaceClaim does not show and leaves the script running. The third script therefore asks for the folder in a separate PowerShell process.
%[text] - SpaceClaim, when started from Ansys, can set `PYTHONHOME` or `PYTHONPATH`. The scripts start Python with `-I` so that it ignores them; without it the packages in the environment were not found.
%[text] - A DXF read back with `ezdxf` lists a layer `Defpoints`, even though the file does not contain it. \

%[appendix]{"version":"1.0"}
%---
%[metadata:view]
%   data: {"layout":"inline"}
%---
