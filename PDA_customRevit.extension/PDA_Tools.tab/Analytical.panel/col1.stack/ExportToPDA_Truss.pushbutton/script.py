# -*- coding: utf-8 -*-
"""
PDA Analysis Software - Tier 1 Geometry Exporter (truss2d variant).

Exports straight DetailLine elements from the active drafting view as canonical
PDA JSON (schema_version 1.0, solver "truss2d"). Merges coincident endpoints
within 1mm, splits at T-junctions, warns on mid-span crossings.

Quick task 260423-a0q. Clone of ExportToPDA.pushbutton (Phase 5, frame2d).
"""
__title__   = 'Export to\nPDA Truss'
__author__  = 'paulo@pda-structure.co.uk'
__doc__     = 'Export detail-line geometry to canonical PDA JSON (truss2d).'

import os
import re
import sys
import json
import math

# -- sys.path guard for lib/Snippets (resolves RESEARCH Open Question 4) -----
# pyRevit auto-adds `lib/` to sys.path, but not necessarily `lib/Snippets/`.
# Compute the Snippets path dynamically from this script's own location and
# insert it at the front of sys.path BEFORE any `_units_conversion` /
# `_selection_func` imports. This makes the imports work regardless of
# pyRevit's default path behaviour across versions.
# Script location: <ext_root>/PDA_Tools.tab/Analytical.panel/col1.stack/ExportToPDA_Truss.pushbutton/script.py
# Target:          <ext_root>/lib/Snippets/
# Relative hops up: ../../../../  (ExportToPDA_Truss.pushbutton -> col1.stack -> Analytical.panel -> PDA_Tools.tab -> ext_root)
_here = os.path.dirname(os.path.abspath(__file__))
_snippets_path = os.path.normpath(os.path.join(_here, '..', '..', '..', '..', 'lib', 'Snippets'))
if _snippets_path not in sys.path:
    sys.path.insert(0, _snippets_path)

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory,
    DetailLine, Line, ViewDrafting, XYZ,
)
from Autodesk.Revit.UI import (
    TaskDialog, TaskDialogCommonButtons, TaskDialogResult,
)
from pyrevit import forms, script

# Reuse from the extension lib (sys.path guard above ensures these work)
from _units_conversion import convert_internal_units  # noqa: E402
from _selection_func import get_selected_elements     # noqa: E402

# -- Constants ---------------------------------------------------------------
TOLERANCE_M = 0.001          # 1mm merge/split tolerance (matches Phase 5 D-07)
GRID_PX     = 20             # UI GRID constant - matches ui/truss2d/script.js
ORIGIN_PX   = {"x": 100, "y": 400}  # default canvas origin (non-null required)
DEFAULT_E   = 200e9          # Pa  (truss2d UI prefill)
DEFAULT_A   = 0.01           # m^2 (truss2d UI prefill)
# NB: truss2d has no flexural stiffness, so no second-moment-of-area default is emitted.

def _q4(x):
    """Quantize to 4 decimal places via string round-trip.

    `round(x, 4)` returns the closest binary double to x rounded - but for
    most decimals (e.g. 3.048) the closest double is slightly off. CPython 3
    hides this in json.dumps via shortest-round-trip repr; IronPython 2.7
    (which Revit/pyRevit uses) does NOT - it serialises the noisy form like
    `3.04800000001`. Going through `"%.4f" % x` then back through `float()`
    produces a fresh double that json serialises cleanly.

    Use everywhere coordinates are written to JSON. REVIT-T1-04 demands
    "at most 4 decimal places" in the exported file, not in memory.
    """
    return float("%.4f" % x)

# -- Revit globals -----------------------------------------------------------
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
app   = __revit__.Application

# -- Session-scoped warning flag (D-16) --------------------------------------
# pyRevit re-imports this script each click, so module globals don't persist.
# Use pyRevit's script.set_envvar/get_envvar - an in-process registry that
# lives for the Revit session. Truss exporter uses its OWN namespaced key so
# the once-per-session warning fires independently of the frame2d exporter
# (a user might export both in one Revit session and should see the banner
# once per tool, not once globally).
_SESSION_KEY_WARNING = 'PDA_EXPORT_TRUSS_WARNING_SHOWN'

def _warning_already_shown_this_session():
    return bool(script.get_envvar(_SESSION_KEY_WARNING))

def _mark_warning_shown_this_session():
    script.set_envvar(_SESSION_KEY_WARNING, True)

def _show_2d_only_warning():
    """D-16: pre-run once-per-session TaskDialog with 'Don't show again' checkbox.
    Returns True if user clicked OK, False if Cancel."""
    td = TaskDialog("PDA Truss Export")
    td.MainInstruction = "2D TRUSSES AND 2D FRAMES ONLY"
    td.MainContent = (
        "This exports detail-line geometry only. Supports and loads must be "
        "added in the truss2d browser UI after loading the JSON."
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
        x0 = _q4(convert_internal_units(p0.X, get_internal=False, units='m'))
        y0 = _q4(convert_internal_units(p0.Y, get_internal=False, units='m'))
        x1 = _q4(convert_internal_units(p1.X, get_internal=False, units='m'))
        y1 = _q4(convert_internal_units(p1.Y, get_internal=False, units='m'))
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
    nodes_m.append([_q4(pt_m[0]), _q4(pt_m[1])])
    return len(nodes_m) - 1

# -- Point-to-segment interior test (D-05 T-junction detection) -------------
def _point_on_segment_interior(p, a, b, tol):
    """True if point `p` is within `tol` metres of segment `a->b` AND the
    perpendicular foot lies STRICTLY inside the segment (not at or beyond
    either endpoint - an endpoint coincidence is handled by the merge step,
    not by splitting).

    `tol` is in METRES (Chebyshev for node-merge; Euclidean for this
    perpendicular distance). Parametric threshold scales with segment length
    (pitfall 10): `t_tol = tol / seg_len`.
    """
    ax, ay = a
    bx, by = b
    px, py = p
    dx = bx - ax
    dy = by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 < tol * tol:
        return False  # degenerate segment - nothing to split
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len2
    seg_len = math.sqrt(seg_len2)
    t_tol = tol / seg_len
    if t <= t_tol or t >= 1.0 - t_tol:
        return False  # foot at or past an endpoint (not a T-junction)
    foot_x = ax + t * dx
    foot_y = ay + t * dy
    dist = math.sqrt((px - foot_x) ** 2 + (py - foot_y) ** 2)
    return dist < tol

# -- Segment-segment interior crossing (D-06 warn, no split) ----------------
def _segments_cross_interior(a0, a1, b0, b1, tol):
    """Return (x, y) intersection if segments a0->a1 and b0->b1 cross at an
    interior point of BOTH (both parametric coords strictly inside
    (t_tol, 1-t_tol) per-segment), else None. Parallel or colinear -> None."""
    ax0, ay0 = a0
    ax1, ay1 = a1
    bx0, by0 = b0
    bx1, by1 = b1
    dax, day = ax1 - ax0, ay1 - ay0
    dbx, dby = bx1 - bx0, by1 - by0
    denom = dax * dby - day * dbx
    if abs(denom) < 1e-12:
        return None
    t = ((bx0 - ax0) * dby - (by0 - ay0) * dbx) / denom
    s = ((bx0 - ax0) * day - (by0 - ay0) * dax) / denom
    len_a = math.sqrt(dax * dax + day * day)
    len_b = math.sqrt(dbx * dbx + dby * dby)
    tol_t_a = tol / len_a
    tol_t_b = tol / len_b
    if t <= tol_t_a or t >= 1.0 - tol_t_a:
        return None
    if s <= tol_t_b or s >= 1.0 - tol_t_b:
        return None
    return (ax0 + t * dax, ay0 + t * day)

# -- Merge endpoints + split at T-junctions + detect crossings (D-05, D-06) --
def _merge_and_split(segments):
    """Given a list of ((x0, y0), (x1, y1)) segments in metres, return:
      - nodes_m : List[List[float]]      - deduplicated node coords
      - members_pairs : List[List[int]]  - [i_0based, j_0based] pairs, indices into nodes_m
      - crossings : List[Tuple[int, int, Tuple[float, float]]]
          - D-06 mid-span crossings (member_idx_a, member_idx_b, (x, y))

    Algorithm (verbatim from RESEARCH.md Algorithms):
      1. Build initial nodes_m + members_pairs via _get_or_add_node on every endpoint.
      2. For each node p: for each member (i, j): if p is NOT an endpoint of (i, j)
         AND _point_on_segment_interior(nodes_m[p], nodes_m[i], nodes_m[j], TOLERANCE_M)
         is True -> replace (i, j) with (i, p) and (p, j). Restart the inner loop
         since the list changed.
      3. After no more splits, walk all unordered pairs of members and call
         _segments_cross_interior on their node coordinates. Record any hit.
    """
    nodes_m = []
    members_pairs = []
    for (p0, p1) in segments:
        i = _get_or_add_node(p0, nodes_m)
        j = _get_or_add_node(p1, nodes_m)
        if i != j:  # guard against a segment collapsing into a single node (both endpoints within tol)
            members_pairs.append([i, j])

    # Step 2: T-junction split pass - restart on every successful split
    changed = True
    guard = 0
    max_iter = 10000  # safety bound; real drafting views are tiny
    while changed and guard < max_iter:
        changed = False
        guard += 1
        for p_idx in range(len(nodes_m)):
            p_coords = nodes_m[p_idx]
            for m_idx in range(len(members_pairs)):
                i, j = members_pairs[m_idx]
                if p_idx == i or p_idx == j:
                    continue
                if _point_on_segment_interior(p_coords, nodes_m[i], nodes_m[j], TOLERANCE_M):
                    # Split (i, j) -> (i, p_idx) + (p_idx, j)
                    members_pairs.pop(m_idx)
                    members_pairs.append([i, p_idx])
                    members_pairs.append([p_idx, j])
                    changed = True
                    break
            if changed:
                break

    # Step 3: Mid-span crossing detection (D-06) - no split, just warn
    crossings = []
    n_mem = len(members_pairs)
    for a_idx in range(n_mem):
        ai, aj = members_pairs[a_idx]
        a0 = (nodes_m[ai][0], nodes_m[ai][1])
        a1 = (nodes_m[aj][0], nodes_m[aj][1])
        for b_idx in range(a_idx + 1, n_mem):
            bi, bj = members_pairs[b_idx]
            # If members share a node, they meet at that node - not a crossing
            if bi == ai or bi == aj or bj == ai or bj == aj:
                continue
            b0 = (nodes_m[bi][0], nodes_m[bi][1])
            b1 = (nodes_m[bj][0], nodes_m[bj][1])
            hit = _segments_cross_interior(a0, a1, b0, b1, TOLERANCE_M)
            if hit is not None:
                crossings.append((a_idx, b_idx, hit))

    return nodes_m, members_pairs, crossings

# -- Lexicographic node sort (D-08) -----------------------------------------
def _sort_nodes_lexicographic(nodes_m, members_pairs):
    """Sort nodes by (x, y) ascending - node 0 is the smallest-x then smallest-y
    point - and remap member indices. Reproducible across Revit sessions for
    the same geometry; enables diffable fixtures."""
    indexed = list(enumerate(nodes_m))
    indexed.sort(key=lambda pair: (pair[1][0], pair[1][1]))
    old_to_new = {}
    new_nodes = []
    for new_idx, (old_idx, coords) in enumerate(indexed):
        old_to_new[old_idx] = new_idx
        new_nodes.append(coords)
    new_members = [[old_to_new[i], old_to_new[j]] for i, j in members_pairs]
    return new_nodes, new_members

# -- Filename sanitisation (D-13) -------------------------------------------
def _sanitise_filename(name):
    """Strip/replace filesystem-unsafe chars in the Revit view name. Falls back
    to literal 'view' if the result is empty (all chars stripped).

    Mitigates threat T-05-11 (path traversal) by removing path separators,
    wildcards, and whitespace before the string reaches the Save-As dialog's
    default filename. User still confirms final path via the dialog itself.
    """
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_')
    return cleaned or 'view'

# -- JSON payload builder (truss2d schema) ----------------------------------
def _build_json(nodes_m, members_pairs_0based):
    """Return a dict matching the truss2d UI Load handler contract
    (ui/truss2d/script.js ~lines 822-850).

    Tier 1 emits geometry + uniform default E/A only. Supports and loads
    are empty - the user adds them in the truss2d browser UI.

    Critical invariants:
    - `solver` MUST be the exact string "truss2d" (UI rejects otherwise at line 827).
    - `canvas.origin` MUST be a non-null object or nodes render at (0, 0).
    - Top-level `members` is 1-based; `canvas.members[*].start/end` is 0-based.
    - forceVector length = 2 * n_nodes (2 DOF/node - NOT 3 like frame2d).
    - No EN-Forces / EN-Moments / I / bars / beam-pin-Left / beam-pin-Right /
      pin-DoF / spring-DoF / spring-Stiffness / A-beam / A-bar / udl-x in the
      truss2d schema.
    - canvas.loads (NOT node-Loads) per ui/truss2d/script.js line 850.
    - canvas node shape: {id, x, y, realX, realY} - no type/pinLeft/overrides.
    - canvas member shape: {start, end} - no id/type/pinLeft/udl/overrides.
    """
    n_nodes = len(nodes_m)
    n_members = len(members_pairs_0based)

    # Canvas nodes - minimal truss2d shape
    canvas_nodes = []
    for i in range(n_nodes):
        rx, ry = _q4(nodes_m[i][0]), _q4(nodes_m[i][1])
        canvas_nodes.append({
            "id": i,
            "x": _q4(ORIGIN_PX["x"] + rx * GRID_PX),
            "y": _q4(ORIGIN_PX["y"] - ry * GRID_PX),  # Y axis inverted in canvas
            "realX": rx,
            "realY": ry,
        })

    # Canvas members - minimal truss2d shape (0-based start/end)
    canvas_members = []
    for i in range(n_members):
        s, e = members_pairs_0based[i][0], members_pairs_0based[i][1]
        canvas_members.append({
            "start": s,
            "end": e,
        })

    return {
        "schema_version": "1.0",
        "solver": "truss2d",

        # Flat arrays - mirror Truss2DRequest for direct POST to /solve/truss2d
        "nodes": nodes_m,
        "members": [[s + 1, e + 1] for (s, e) in members_pairs_0based],  # 1-based
        "E": DEFAULT_E,
        "A": DEFAULT_A,
        "forceVector": [0] * (n_nodes * 2),  # 2 DOF per node (truss2d)
        "restrainedDoF": [],

        # Canvas block - UI Load handler reads geometry from here
        "canvas": {
            "origin": ORIGIN_PX,
            "nodes": canvas_nodes,
            "members": canvas_members,
            "supports": {},
            "loads": [],
        },
    }

# -- Main entry point --------------------------------------------------------
def main():
    view = uidoc.ActiveView

    # D-15 step 1: active view must be ViewDrafting
    if not isinstance(view, ViewDrafting):
        TaskDialog.Show(
            "PDA Truss Export",
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
            "PDA Truss Export",
            "No detail lines found in active drafting view - draw some first."
        )
        return

    # Convert detail lines to (x_m, y_m) endpoint pairs (D-11, D-12, REVIT-T1-04)
    segments = _extract_segments(detail_lines)
    if not segments:
        TaskDialog.Show(
            "PDA Truss Export",
            "No straight detail lines found - every line was a zero-length segment."
        )
        return

    # Merge coincident endpoints (REVIT-T1-03, D-07), split T-junctions (D-05),
    # detect mid-span crossings (D-06)
    nodes_m, members_pairs, crossings = _merge_and_split(segments)

    # Sort nodes lexicographically by (x, y) (D-08) - reproducible output
    nodes_m, members_pairs = _sort_nodes_lexicographic(nodes_m, members_pairs)

    # Build canonical JSON payload (truss2d schema)
    payload = _build_json(nodes_m, members_pairs)

    # D-13: Save-As dialog - pre-populate with sanitised view name
    default_name = _sanitise_filename(view.Name) + '_pda_truss'
    save_path = forms.save_file(file_ext='json', default_name=default_name)
    if not save_path:
        return  # user cancelled - do NOT write a file (D-13 / D-15 fail-safe)

    # Write JSON (indent=2 for human-readable diff; ensure_ascii=True to avoid
    # IronPython 2.7 unicode-write issues - pitfall 9)
    with open(save_path, 'w') as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)

    # D-14: Success TaskDialog - counts + full path + optional crossings warning
    success_msg = "Exported {0} nodes, {1} members to:\n{2}".format(
        len(nodes_m), len(members_pairs), save_path
    )
    if crossings:
        success_msg += (
            "\n\nWarning: {0} mid-span crossing(s) detected and NOT split - "
            "add the connection node manually in the truss2d UI if intended."
            .format(len(crossings))
        )
    TaskDialog.Show("PDA Truss Export Complete", success_msg)

if __name__ == "__main__":
    main()
