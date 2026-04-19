
"""
PDA Analysis Software - Revit Analytical Model Exporter

Exports the Revit analytical model (beams, columns, braces) to PDA's canonical
JSON interchange format (schema_version 1.0, solver "frame2d").

Usage: Run this script from a pyRevit button/script in Revit 2023+.

Requirements:
  - Revit 2023 or later (uses the AnalyticalMember API, not the removed
    element.GetAnalyticalModel() call from pre-2023 Revit).
  - pyRevit 4.8+ (for CPython support) or pyRevit with IronPython 2.7.4+.

Notes:
  - Revit internal coordinates are ALWAYS in feet, regardless of the project's
    display units. This script converts to metres (* 0.3048).
  - The exported JSON contains geometry only (nodes, members, default E/I/A).
    Supports, loads, and member property overrides must be added in the PDA
    browser UI or edited into the JSON file before solving.
  - Non-planar 3D models: only X and Y coordinates are exported; Z is ignored.
    Verify your model is approximately planar before using with the 2D frame
    solver.
  - IronPython 2.7 compatibility: do NOT use f-strings or other Python 3.6+
    syntax. Use str.format() throughout.
"""

import json

# Revit API imports — only available at runtime inside Revit.
from Autodesk.Revit.DB import FilteredElementCollector, AnalyticalMember
from pyrevit import forms, script

FEET_TO_METRES = 0.3048

doc = __revit__.ActiveUIDocument.Document  # noqa: F821  (Revit runtime global)


def xyz_to_metres(xyz):
    """Convert a Revit XYZ point (in feet) to [x, y] in metres."""
    return [
        round(xyz.X * FEET_TO_METRES, 4),
        round(xyz.Y * FEET_TO_METRES, 4),
    ]


def get_or_add_node(xyz, nodes_list, tol=1e-3):
    """Return 0-based index of an existing node within tolerance, or append new."""
    pt = xyz_to_metres(xyz)
    for i, n in enumerate(nodes_list):
        if abs(n[0] - pt[0]) < tol and abs(n[1] - pt[1]) < tol:
            return i
    nodes_list.append(pt)
    return len(nodes_list) - 1


# Collect all analytical members (beams, columns, braces) from the active doc.
# NOTE: This uses the Revit 2023+ API. The old element.GetAnalyticalModel() was
# removed in Revit 2023 and will raise AttributeError if called.
members_col = (
    FilteredElementCollector(doc).OfClass(AnalyticalMember).ToElements()
)

if not members_col:
    forms.alert(
        "No analytical members found in the active document.\n\n"
        "Make sure the Analytical Model is enabled and that members have "
        "analytical representations.",
        title="PDA Export",
    )
else:
    nodes = []
    members = []

    for mbr in members_col:
        curve = mbr.GetCurve()
        si = get_or_add_node(curve.GetEndPoint(0), nodes)
        ei = get_or_add_node(curve.GetEndPoint(1), nodes)
        # PDA API uses 1-based node indices
        members.append([si + 1, ei + 1])

    n_nodes = len(nodes)
    n_members = len(members)

    output = {
        "schema_version": "1.0",
        "solver": "frame2d",
        "nodes": nodes,
        "members": members,
        "ENForces": [[0, 0] for _ in range(n_members)],
        "ENMoments": [[0, 0] for _ in range(n_members)],
        "forceVector": [0] * (n_nodes * 3),  # 3 DOF/node for frame2d
        "E": 200e9,      # generic steel — edit in UI or JSON
        "I": 1e-4,
        "A": 0.01,
        "bars": [],
        "beamPinLeft": [],
        "beamPinRight": [],
        "restrainedDoF": [],
        "pinDoF": [],
        "springDoF": [],
        "springStiffness": [],
        "udl_x": [0] * n_members,
        "canvas": {
            "origin": None,
            "nodes": [],
            "members": [],
            "supports": [],
            "nodeLoads": [],
        },
    }

    save_path = forms.save_file(file_ext="json")
    if save_path:
        with open(save_path, "w") as f:
            json.dump(output, f, indent=2)
        script.get_output().print_md(
            "**PDA Export Complete**\n\n"
            "Exported {0} nodes, {1} members to:\n`{2}`\n\n"
            "Open this file in the PDA frame2d browser UI to add supports "
            "and loads.".format(n_nodes, n_members, save_path)
        )
