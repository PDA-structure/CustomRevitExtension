# -*- coding: utf-8 -*-
"""
PDA Analysis Software - Tier 1 Geometry Exporter (REVIT-T1-01..05).

Exports straight DetailLine elements from the active drafting view as canonical
PDA JSON (schema_version 1.0, solver "frame2d"). Merges coincident endpoints
within 1mm, splits at T-junctions, warns on mid-span crossings.

Phase 5. See pda_project/.planning/phases/05-revit-tier-1-geometry-exporter/.
"""
__title__   = 'Export to\nPDA'
__author__  = 'paulo@pda-structure.co.uk'
__doc__     = 'Export detail-line geometry to canonical PDA JSON (frame2d).'

import os
import re
import sys
import json

# -- sys.path guard for lib/Snippets (resolves RESEARCH Open Question 4) -----
# pyRevit auto-adds `lib/` to sys.path, but not necessarily `lib/Snippets/`.
# Compute the Snippets path dynamically from this script's own location and
# insert it at the front of sys.path BEFORE any `_units_conversion` /
# `_selection_func` imports. This makes the imports work regardless of
# pyRevit's default path behaviour across versions.
# Script location: <ext_root>/PDA_Tools.tab/Analytical.panel/col1.stack/ExportToPDA.pushbutton/script.py
# Target:          <ext_root>/lib/Snippets/
# Relative hops up: ../../../../../  (ExportToPDA.pushbutton -> col1.stack -> Analytical.panel -> PDA_Tools.tab -> ext_root)
_here = os.path.dirname(os.path.abspath(__file__))
_snippets_path = os.path.normpath(os.path.join(_here, '..', '..', '..', '..', '..', 'lib', 'Snippets'))
if _snippets_path not in sys.path:
    sys.path.insert(0, _snippets_path)

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory,
    DetailLine, Line, ViewDrafting, XYZ,
)
from Autodesk.Revit.UI import (
    TaskDialog, TaskDialogCommonButtons, TaskDialogResult,
)

# Reuse from the extension lib (sys.path guard above ensures these work)
from _units_conversion import convert_internal_units  # noqa: E402
from _selection_func import get_selected_elements     # noqa: E402

# -- Constants ---------------------------------------------------------------
TOLERANCE_M = 0.001          # D-07: 1mm merge/split tolerance in METRES
GRID_PX     = 20             # UI GRID constant - matches ui/frame2d/script.js
ORIGIN_PX   = {"x": 100, "y": 400}  # default canvas origin (non-null; see RESEARCH sec JSON Contract pitfall 3)
DEFAULT_E   = 200e9          # Pa   (D-09)
DEFAULT_I   = 1e-4           # m^4  (D-09)
DEFAULT_A   = 0.01           # m^2  (D-09)

# -- Revit globals -----------------------------------------------------------
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
app   = __revit__.Application

# -- Session-scoped warning flag (D-16) --------------------------------------
def _warning_already_shown_this_session():
    # pyRevit re-imports this script each click, so module globals don't persist.
    # Persist on __revit__.Application (lives for the Revit session).
    return getattr(app, '_pda_export_warning_shown', False)

def _mark_warning_shown_this_session():
    app._pda_export_warning_shown = True

def _show_2d_only_warning():
    """D-16: pre-run once-per-session TaskDialog with 'Don't show again' checkbox.
    Returns True if user clicked OK, False if Cancel."""
    td = TaskDialog("PDA Export")
    td.MainInstruction = "2D TRUSSES AND 2D FRAMES ONLY"
    td.MainContent = (
        "This exports detail-line geometry only. Supports and loads must be "
        "added in the frame2d browser UI after loading the JSON."
    )
    td.CommonButtons = TaskDialogCommonButtons.Ok | TaskDialogCommonButtons.Cancel
    td.DefaultButton = TaskDialogResult.Ok
    td.VerificationText = "Don't show this message again this session"
    result = td.Show()
    if result != TaskDialogResult.Ok:
        return False
    if td.WasVerificationChecked():   # method call, not property (pitfall 5)
        _mark_warning_shown_this_session()
    return True

# -- Detail-line collection (D-01, D-02, D-03) -------------------------------
def _collect_detail_lines(view):
    """Return list of straight-Line DetailLine elements in or selected for `view`.
    Selection override: if the user has DetailLines pre-selected, use the
    lib/Snippets/_selection_func.py helper `get_selected_elements([DetailLine])`
    (per CONTEXT D-03 and RESEARCH Reuse Map - do NOT hand-roll selection).
    Otherwise collect every DetailLine in the view via FilteredElementCollector.
    In both branches, silently skip arcs, splines, and other non-Line
    CurveElements (D-01)."""
    # Check whether the user has anything pre-selected first (cheap call).
    sel_ids = uidoc.Selection.GetElementIds()
    if sel_ids and len(sel_ids) > 0:
        # Selection-override branch - use the reusable snippet helper.
        selected = get_selected_elements([DetailLine])
        # Scope to the active view (helper returns from any view).
        candidates = [e for e in selected
                      if e is not None and getattr(e, 'OwnerViewId', None) == view.Id]
    else:
        # No selection - collect every detail line in the active view.
        candidates = list(
            FilteredElementCollector(doc, view.Id)
            .OfCategory(BuiltInCategory.OST_Lines)
            .WhereElementIsNotElementType()
            .ToElements()
        )
    # Filter to DetailLine + straight Line geometry (rejects arcs/splines per D-01).
    detail_lines = [
        e for e in candidates
        if isinstance(e, DetailLine) and isinstance(e.GeometryCurve, Line)
    ]
    return detail_lines

# -- Segment extraction (D-01, D-11, D-12, REVIT-T1-04) ---------------------
def _extract_segments(detail_lines):
    """Return list of ((x0_m, y0_m), (x1_m, y1_m)) tuples in metres, 4-dp-rounded.

    Drops the Z coordinate entirely (D-11 - drafting views are planar). Silently
    skips any line whose endpoints collapse to within TOLERANCE_M after rounding
    (zero-length line - Claude's Discretion silent-skip rule).
    """
    segs = []
    for el in detail_lines:
        curve = el.GeometryCurve
        if not isinstance(curve, Line):
            continue  # defensive - _collect_detail_lines already filtered
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        x0 = round(convert_internal_units(p0.X, get_internal=False, units='m'), 4)
        y0 = round(convert_internal_units(p0.Y, get_internal=False, units='m'), 4)
        x1 = round(convert_internal_units(p1.X, get_internal=False, units='m'), 4)
        y1 = round(convert_internal_units(p1.Y, get_internal=False, units='m'), 4)
        # Zero-length check (silent skip per Claude's Discretion)
        if abs(x1 - x0) < TOLERANCE_M and abs(y1 - y0) < TOLERANCE_M:
            continue
        segs.append(((x0, y0), (x1, y1)))
    return segs

# -- Endpoint-merge / node deduplication (D-07, REVIT-T1-03) ----------------
def _get_or_add_node(pt_m, nodes_m, tol=TOLERANCE_M):
    """Return 0-based index of an existing node within `tol` metres (Chebyshev),
    else append (4-dp-rounded) and return the new index.

    Chebyshev (Linf) tolerance matches REVIT-T1-03 literally: "within 1mm" is
    satisfied when both |dx| < tol AND |dy| < tol. Simpler than Euclidean and
    consistent with the legacy exporter.
    """
    for i, n in enumerate(nodes_m):
        if abs(n[0] - pt_m[0]) < tol and abs(n[1] - pt_m[1]) < tol:
            return i
    nodes_m.append([round(pt_m[0], 4), round(pt_m[1], 4)])
    return len(nodes_m) - 1

# -- Main entry point (partial - geometry pipeline + JSON added in plans 05-02 and 05-03) --
def main():
    view = uidoc.ActiveView

    # D-15 step 1: active view must be ViewDrafting
    if not isinstance(view, ViewDrafting):
        TaskDialog.Show(
            "PDA Export",
            "Active view must be a drafting view (found: {0}).".format(type(view).__name__)
        )
        return

    # D-16: once-per-session 2D-only warning
    if not _warning_already_shown_this_session():
        if not _show_2d_only_warning():
            return  # user cancelled

    # D-01/D-02/D-03: collect detail lines
    detail_lines = _collect_detail_lines(view)

    # D-04: empty-view / empty-selection
    if not detail_lines:
        TaskDialog.Show(
            "PDA Export",
            "No detail lines found in active drafting view - draw some first."
        )
        return

    # TODO(05-02): run geometry pipeline on detail_lines
    # TODO(05-03): build JSON, save via forms.save_file, show success TaskDialog
    TaskDialog.Show(
        "PDA Export",
        "Scaffold only - collected {0} detail line(s). Geometry pipeline and "
        "JSON emit land in plans 05-02 and 05-03.".format(len(detail_lines))
    )

if __name__ == "__main__":
    main()
