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

# -- Idempotency precheck (D-03; Pitfall 1) ----------------------------------
def _is_already_associated(doc, physical_id):
    """REVIT-CONVERT-03 idempotency precheck.
    Returns True if the physical element already has an associated analytical member.
    CRITICAL: GetAssociatedElementId returns ElementId.InvalidElementId, NOT None (Pitfall 1)."""
    manager = AnalyticalToPhysicalAssociationManager.GetAnalyticalToPhysicalAssociationManager(doc)
    if manager is None:
        return False  # first call in document -- no manager yet => no associations
    associated_id = manager.GetAssociatedElementId(physical_id)
    return associated_id != ElementId.InvalidElementId

# -- Curve derivation (Pitfall 3; column vs beam branching) ------------------
def _derive_curve(elem):
    """Bounded curve for AnalyticalMember.Create. Returns (curve, None) on success
    or (None, skip_reason) on geometry failure. skip_reason is one of:
    'missing-location', 'unsupported-geometry'."""
    loc = elem.Location
    if isinstance(loc, LocationCurve):
        curve = loc.Curve
        if curve is None or not curve.IsBound:
            return None, 'unsupported-geometry'
        return curve, None
    if isinstance(loc, LocationPoint):
        # Column: derive vertical line from base level + top level (Pitfall 3)
        base_param = elem.LookupParameter('Base Level')
        top_param  = elem.LookupParameter('Top Level')
        if base_param is None or top_param is None:
            return None, 'missing-location'
        base_level_id = base_param.AsElementId()
        top_level_id  = top_param.AsElementId()
        if base_level_id == ElementId.InvalidElementId or top_level_id == ElementId.InvalidElementId:
            return None, 'missing-location'
        base_level = doc.GetElement(base_level_id)
        top_level  = doc.GetElement(top_level_id)
        if base_level is None or top_level is None:
            return None, 'missing-location'
        p0 = XYZ(loc.Point.X, loc.Point.Y, base_level.Elevation)
        p1 = XYZ(loc.Point.X, loc.Point.Y, top_level.Elevation)
        if p0.IsAlmostEqualTo(p1):
            return None, 'unsupported-geometry'
        return Line.CreateBound(p0, p1), None
    return None, 'missing-location'

# -- StructuralType capture (D-02; Pitfall 2) --------------------------------
def _structural_type(doc, physical_id):
    """D-02: capture StructuralType for diagnostic logging. Returns string name of
    the enum value, or 'Unknown' if the element has no StructuralType attribute.
    Pitfall 2: real enum members are {NonStructural, Beam, Brace, Column, Footing, UnknownFraming}.
    There is NO 'Girder' member."""
    elem = doc.GetElement(physical_id)
    if elem is None:
        return 'Unknown'
    try:
        st = elem.StructuralType
        return str(st)
    except AttributeError:
        return 'Unknown'

# -- Per-element conversion (D-11 reversed: Create + AddAssociation) ----------
def _convert_one(doc, physical_id):
    """D-11 (reversed 2026-04-29): AnalyticalMember.Create + AddAssociation.
    The previously-assumed single-call factory does NOT exist as a public API
    method; this two-call pattern is the only verifiable physical-to-analytical
    conversion path (verified by absence: revitapidocs 2024/2025/2025.3, GitHub,
    Autodesk Help). Caller MUST have an active Transaction. Returns the new
    analytical ElementId. Raises ValueError(skip_reason) when curve derivation
    fails -- caller routes the skip via its except clause."""
    elem = doc.GetElement(physical_id)
    curve, skip_reason = _derive_curve(elem)
    if skip_reason is not None:
        raise ValueError(skip_reason)
    analytical = AnalyticalMember.Create(doc, curve)
    manager = AnalyticalToPhysicalAssociationManager.GetAnalyticalToPhysicalAssociationManager(doc)
    manager.AddAssociation(analytical.Id, physical_id)
    return analytical.Id

# -- Read-back verification (D-10; Pitfall 10) --------------------------------
def _verify_section_and_material(doc, analytical_id):
    """D-10: confirm section + material associated post-AddAssociation, pre-commit.
    AddAssociation propagates section/material from the physical element automatically;
    a null result here means the source element had nothing to propagate.
    CRITICAL: this MUST be called BEFORE tx.Commit(); once committed, only a fresh
    transaction can roll back the orphan analytical member (Pitfall 10)."""
    am = doc.GetElement(analytical_id)
    if am is None:
        return False
    try:
        has_section  = am.SectionTypeId  != ElementId.InvalidElementId
        has_material = am.MaterialId     != ElementId.InvalidElementId
    except AttributeError:
        return False
    return has_section and has_material

# -- Batch driver (D-06 TransactionGroup + per-element Transaction) ----------
def run_batch(doc, physical_ids):
    """D-06 transactional batch with isolated per-element rollback.
    Outer TransactionGroup 'PDA: Convert to Analytical' wraps per-element
    Transaction instances. Single failed element rolls back its own tx and
    the group continues. Group ends with Assimilate() (Pitfall 5: NOT Commit)
    so the engineer sees one undo step covering the whole batch.

    Returns (converted, already, skips) where:
      converted: list[ElementId] -- physical ids whose conversion succeeded
      already:   list[ElementId] -- physical ids that were already associated (D-03)
      skips:     list[(ElementId, reason: str, role: str|None)] -- skip log

    Skip reasons (D-07, with D-11 unsupported-geometry addition):
      'missing-location', 'unsupported-geometry', 'missing-section',
      'generation-failed', 'other-error'.
    ('already-associated' is reported via the `already` list, NOT skips, per D-03.)"""
    converted, already, skips = [], [], []
    tg = TransactionGroup(doc, "PDA: Convert to Analytical")
    tg.Start()
    try:
        for pid in physical_ids:
            # D-03: already-associated is a non-error skip on a distinct line.
            if _is_already_associated(doc, pid):
                already.append(pid)
                continue
            role = _structural_type(doc, pid)
            tx = Transaction(doc, "Convert element {0}".format(pid.IntegerValue))
            tx.Start()
            try:
                new_id = _convert_one(doc, pid)
                if not _verify_section_and_material(doc, new_id):
                    # D-10: read-back BEFORE commit -- rollback the orphan analytical member.
                    tx.RollBack()
                    skips.append((pid, 'missing-section', role))
                    continue
                if tx.Commit() != TransactionStatus.Committed:
                    skips.append((pid, 'generation-failed', role))
                    continue
                converted.append(pid)
            except ValueError as ve:
                # _convert_one raised ValueError(skip_reason) from _derive_curve.
                if tx.HasStarted() and not tx.HasEnded():
                    tx.RollBack()
                skips.append((pid, str(ve), role))
            except Exception as exc:
                # Anything else: typed as 'other-error', carry str(exc) for diagnostics.
                if tx.HasStarted() and not tx.HasEnded():
                    tx.RollBack()
                skips.append((pid, 'other-error', role))
        tg.Assimilate()  # CRITICAL: Assimilate, NOT Commit (Pitfall 5)
    except Exception:
        # Total-batch failure: roll back ALL inner transactions (committed or not).
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()
        raise
    return converted, already, skips

# -- Diagnostic emission (D-08 dual surface; D-09 always shown) --------------
def _emit_summary(converted, already, skips):
    """D-08 + D-09. Two surfaces, both always run.

    Surface 1 (Output Window, only if there are skips): markdown table with
    clickable element links via output.linkify; columns: Element, Reason,
    Structural Type. Engineer clicks the link, Revit highlights the element.

    Surface 2 (TaskDialog, always): one-line summary
    'converted: N | already-associated: M | skipped (errors): K | total: T'
    with already-associated as a distinct line per D-03. Body text varies by
    whether there are skips. ASCII-only per Pitfall 9."""
    output = script.get_output()
    output.set_title("PDA: Convert to Analytical")

    if skips:
        rows = [
            [output.linkify(eid), reason, str(role) if role else '-']
            for (eid, reason, role) in skips
        ]
        output.print_table(
            table_data=rows,
            title='Conversion Skips',
            columns=['Element', 'Reason', 'Structural Type'],
        )

    summary = "converted: {0} | already-associated: {1} | skipped (errors): {2} | total: {3}".format(
        len(converted), len(already), len(skips),
        len(converted) + len(already) + len(skips),
    )
    td = TaskDialog("PDA: Convert to Analytical")
    td.MainInstruction = summary
    if skips:
        td.MainContent = "{0} element(s) were skipped. See the pyRevit Output window for clickable links to each.".format(len(skips))
    else:
        td.MainContent = "All elements processed successfully."
    td.Show()

# -- Main entry point --------------------------------------------------------
def main():
    physical_ids = _resolve_input(uidoc, doc)
    if not physical_ids:
        return  # _resolve_input handled user-facing TaskDialog (or silent Escape)
    converted, already, skips = run_batch(doc, physical_ids)
    _emit_summary(converted, already, skips)

if __name__ == "__main__":
    main()
