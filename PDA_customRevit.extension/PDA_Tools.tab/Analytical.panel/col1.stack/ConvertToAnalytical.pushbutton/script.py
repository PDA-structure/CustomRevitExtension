# -*- coding: utf-8 -*-
"""
PDA Analysis Software - Element-to-Analytical Conversion (REVIT-CONVERT-01..04).

Converts user-selected physical structural columns and framing into
AnalyticalMember instances via the Revit 2025+ analytical API. Idempotent;
preserves section/material associations; transactional with isolated rollback.

Phase 7. See pda_project/.planning/phases/07-revit-element-to-analytical-conversion/.
"""
__title__   = 'Convert to\nAnalytical'
__author__  = 'paulo@pda-structure.co.uk'
__doc__     = 'Convert selected columns/beams/bracings to AnalyticalMembers.'

# -- Imports -----------------------------------------------------------------
from Autodesk.Revit.DB import (
    BuiltInCategory, ElementId, XYZ,
    Line, LocationCurve, LocationPoint,
    Transaction, TransactionGroup, TransactionStatus,
)
from Autodesk.Revit.DB.Structure import (
    AnalyticalMember,
    AnalyticalToPhysicalAssociationManager,
    StructuralType,
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import script

# -- Revit globals -----------------------------------------------------------
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
app   = __revit__.Application

# -- Supported category registry (D-04) --------------------------------------
# Both v1.3 categories share the same handler (D-05 -- YAGNI per CLAUDE.md).
# v1.5+ Phase 15 (slabs) adds OST_Floors with a new handler without touching dispatch.
SUPPORTED_CATEGORIES = {
    BuiltInCategory.OST_StructuralColumns: 'convert_member',
    BuiltInCategory.OST_StructuralFraming: 'convert_member',  # covers beams + bracings
}

# -- Selection filter (inline per D-15; Pitfall 4) ---------------------------
class _SupportedCategoryFilter(ISelectionFilter):
    def __init__(self, allowed):
        self.allowed = list(allowed)
    def AllowElement(self, element):
        cat = element.Category
        return cat is not None and cat.BuiltInCategory in self.allowed
    def AllowReference(self, ref, point):
        return False  # Pitfall 4: must implement both methods

# -- Hybrid selection (D-01) -------------------------------------------------
def _resolve_input(uidoc, doc):
    """Hybrid input per D-01. Returns list of element ids or [] (cancelled/empty)."""
    pre_selected = list(uidoc.Selection.GetElementIds())
    if pre_selected:
        filtered = [
            eid for eid in pre_selected
            if doc.GetElement(eid).Category and
               doc.GetElement(eid).Category.BuiltInCategory in SUPPORTED_CATEGORIES
        ]
        if filtered:
            return filtered
        # else fall through to PickObjects -- pre-selection had nothing usable
    sel_filter = _SupportedCategoryFilter(SUPPORTED_CATEGORIES.keys())
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, sel_filter,
            "Select columns/beams/bracings to convert. Press Finish when done."
        )
    except OperationCanceledException:
        return []  # silent -- user pressed Escape (Pitfall 8)
    if not refs:
        TaskDialog.Show("PDA Convert", "No elements selected.")
        return []
    return [r.ElementId for r in refs]

# -- Main entry point (PLACEHOLDER -- Plan 7-02 wires conversion) ------------
def main():
    physical_ids = _resolve_input(uidoc, doc)
    if not physical_ids:
        return  # _resolve_input handled user-facing TaskDialog (or silent Escape)
    # Plan 7-02 replaces this placeholder with run_batch + _emit_summary.
    TaskDialog.Show(
        "PDA Convert",
        "Plan 7-01 placeholder: {0} element(s) accepted by selection filter. Conversion lands in Plan 7-02.".format(len(physical_ids))
    )

if __name__ == "__main__":
    main()
