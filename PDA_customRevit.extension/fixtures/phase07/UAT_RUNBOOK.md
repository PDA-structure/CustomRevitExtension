# Phase 7 -- ConvertToAnalytical UAT Runbook

Manual verification procedure for the `ConvertToAnalytical` pyRevit pushbutton (PDA Analysis Software, Phase 7).

This runbook is a checklist the engineer follows on a Windows host with Revit 2025 and pyRevit installed, after the bundle is deployed (see Plan 07-03 Task 3). It covers all five ROADMAP success criteria for Phase 7:

1. Engineer-clickable conversion (Fixture 1)
2. Idempotent re-run (Fixture 3)
3. Final TaskDialog summary with per-skip reasons; one bad element does not abort the batch (Fixture 2)
4. Phase 5 / v1.2 Tier 1 round-trip on Fixture 1 (`Tier 1 Round-Trip` section)
5. Configurable category filter (`Configurable Filter Walkthrough` section)

References:
- Plan: `.planning/phases/07-revit-element-to-analytical-conversion/07-03-PLAN.md`
- Decisions: `07-CONTEXT.md` (D-03, D-08, D-09, D-12, D-13)
- Research: `07-RESEARCH.md` (Pitfall 5, Pitfall 7, Pattern 7)
- Roadmap: `.planning/ROADMAP.md` Phase 7 success criteria

## Pre-flight (one-time per session)

- Revit 2025 open on the Windows host (no document yet).
- pyRevit loaded; `PDA_Tools` tab visible in the ribbon.
- Confirm `PDA_Tools > Analytical > col1.stack > Convert to Analytical` button is present (deploy verification, Plan 07-03 Task 3).
- Hover the button: tooltip should match the bundle.yaml text "Convert selected physical structural columns, beams, and bracings into AnalyticalMember instances. Idempotent -- already-associated elements are skipped."
- If the button is missing or stale: re-run pyRevit Reload, then check for cached `.pyc` files in the pushbutton folder (Pitfall 7).

## Fixture 1: phase07_minimal_frame.rvt

**Purpose:** Prove the happy path. REVIT-CONVERT-01 + REVIT-CONVERT-02. ROADMAP success criterion 1.

**Geometry on disk:** 4 structural columns at the corners of a 6m x 4m grid (base level 0, top level 3m), 2 structural beams along the long edges connecting the column tops, 1 diagonal brace from one column base to the opposite column top. 7 physical elements; zero AnalyticalMembers.

### Procedure

1. Open `phase07_minimal_frame.rvt` in Revit 2025.
2. Optional: open the Analytical Model browser (View > User Interface) and confirm zero AnalyticalMember instances.
3. Click `PDA_Tools > Analytical > col1.stack > Convert to Analytical`.
4. The pushbutton enters PickObjects mode. Select all 7 physical elements (4 columns + 2 beams + 1 brace). Press Finish on the Modify ribbon.
5. Wait for the TaskDialog (typically 1-2 seconds for 7 elements).

### Expected TaskDialog

```
PDA: Convert to Analytical
converted: 7 | already-associated: 0 | skipped (errors): 0 | total: 7
All elements processed successfully.
```

### Expected post-conditions

- Analytical Model browser shows 7 `AnalyticalMember` instances.
- Each AnalyticalMember has a non-null `SectionTypeId` and `MaterialId` (D-10 read-back; the D-11 reversed `AddAssociation` path proves out section + material preservation).
- Each AnalyticalMember is 1:1 associated with its physical element (verify via the analytical browser's parent/child link, or by selecting an AnalyticalMember and using `Highlight Physical`).

### Single-undo check (Pitfall 5: TransactionGroup.Assimilate, not Commit)

1. Press `Ctrl+Z` (Undo) ONCE.
2. EXPECT all 7 AnalyticalMembers to disappear in a single undo step.
3. The undo history label should read `PDA: Convert to Analytical` (the TransactionGroup name), NOT 7 separate per-element undo entries.
4. Press `Ctrl+Y` (Redo) once -- AnalyticalMembers reappear.

If undo requires more than one press to revert all 7, the implementation is using `TransactionGroup.Commit()` instead of `Assimilate()`. This violates Pitfall 5 -- record as a fail.

### Pass criteria

- [ ] TaskDialog summary line matches exactly: `converted: 7 | already-associated: 0 | skipped (errors): 0 | total: 7`
- [ ] Body text reads "All elements processed successfully."
- [ ] 7 AnalyticalMembers visible in the analytical browser
- [ ] All 7 have non-null SectionTypeId + MaterialId
- [ ] Single Ctrl+Z reverts the entire batch (Pitfall 5)
- [ ] Single Ctrl+Y restores the batch

## Fixture 2: phase07_multi_storey.rvt

**Purpose:** Prove per-element error isolation and the diagnostic surface. REVIT-CONVERT-04. ROADMAP success criterion 3.

**Geometry on disk:** 2 storeys (levels at 0, 3m, 6m). 4 columns per storey (8 total) + 8 perimeter beams (4 per storey) = 16 physical elements. ONE element is deliberately broken to exercise the `missing-section` skip path (e.g., a column with `Structural Material` set to `<None>`, or assigned to a family that has no Section).

### Engineer authoring note (record at fixture-creation time)

When the fixture is authored in Revit, the engineer must record below:

- Total physical element count: __ (replace with actual count when fixture exists)
- Broken element kind: __ (e.g., "column at gridline A-1, level 1 -- Structural Material = None")
- Broken element ID (after first save): __ (record the Revit ElementId for verification)

These three values fill in the `N` and per-row content in the expected results below.

### Procedure

1. Open `phase07_multi_storey.rvt`.
2. Click `Convert to Analytical`. Select all physical structural elements (use a ribbon Filter to restrict to columns + beams + bracings if the model has other elements). Press Finish.
3. Wait for the TaskDialog.

### Expected TaskDialog

```
PDA: Convert to Analytical
converted: N-1 | already-associated: 0 | skipped (errors): 1 | total: N
1 element(s) were skipped. See the pyRevit Output window for clickable links to each.
```

Where `N` is the total selection count from the fixture authoring step above.

### Expected pyRevit Output Window content

A markdown table titled `Conversion Skips` with columns `Element | Reason | Structural Type` and exactly 1 row for the deliberately broken element:

| Element            | Reason          | Structural Type |
|--------------------|-----------------|-----------------|
| `<linkify link>`   | missing-section | Column          |

(`Structural Type` will read `Beam`, `Column`, or `Brace` depending on what the broken element is.)

### Linkify click verification (D-08)

1. Click the markdown link in the `Element` cell of the skip row.
2. EXPECT Revit to highlight (zoom to) the deliberately broken element from fixture authoring.
3. The highlighted element ID should match the value recorded in the fixture-authoring note above.

### Batch isolation check (D-06; per-element Transaction inside TransactionGroup)

The `converted` count is `N-1`, not `0`. This proves that one element's failure did not abort the rest of the batch -- per-element rollback (single Transaction per element, rolled back on the broken one only) is working.

### Pass criteria

- [ ] TaskDialog `skipped (errors)` count is exactly 1
- [ ] TaskDialog `converted` count is `total - 1`, not 0
- [ ] TaskDialog body mentions the Output Window
- [ ] Output Window shows a markdown table titled `Conversion Skips`
- [ ] Table has columns Element | Reason | Structural Type
- [ ] Skip row reason is exactly `missing-section` (one of the curated D-07 enum strings)
- [ ] Clicking the linkify link in the Element cell highlights the broken element in Revit
- [ ] Highlighted element ID matches the recorded broken-element ID

## Fixture 3: phase07_pre_converted.rvt

**Purpose:** Prove idempotency. REVIT-CONVERT-03 + Pitfall 1 (InvalidElementId sentinel comparison). ROADMAP success criterion 2.

**Geometry on disk:** Same geometry as Fixture 1 (4 cols + 2 beams + 1 brace = 7 elements), but ConvertToAnalytical (or Revit's Analytical Automation) has been run once already, so all 7 elements have associated AnalyticalMembers in 1:1 association. Saved as a separate file.

### Procedure

1. Open `phase07_pre_converted.rvt`.
2. Confirm in the Analytical Model browser that 7 AnalyticalMembers already exist (1:1 with the 7 physicals).
3. Click `Convert to Analytical`. Select the same 7 physical elements. Press Finish.
4. Wait for the TaskDialog.

### Expected TaskDialog

```
PDA: Convert to Analytical
converted: 0 | already-associated: 7 | skipped (errors): 0 | total: 7
All elements processed successfully.
```

The body reads "All elements processed successfully." because there are no actual errors -- already-associated is a benign no-op, not a failure (D-03).

### Expected post-conditions

- Document AnalyticalMember count is unchanged: still 7. No duplicates.
- The summary line clearly shows `already-associated: 7` as a distinct count, NOT bundled into `skipped (errors)` (D-03).
- No Output Window table appears (no skips in the curated error taxonomy).

### Pass criteria

- [ ] TaskDialog summary line matches: `converted: 0 | already-associated: 7 | skipped (errors): 0 | total: 7`
- [ ] AnalyticalMember count in the document is still 7 (no duplicates)
- [ ] `already-associated` is a distinct line item -- not folded into the error count
- [ ] No `Conversion Skips` table appears in the Output Window

## Tier 1 Round-Trip (D-13, ROADMAP success criterion 4)

**Purpose:** Prove the analytical model produced by Phase 7's ConvertToAnalytical is well-formed enough for the existing Phase 5 / v1.2 Tier 1 ExportToPDA pipeline -- which means downstream tooling (frame2d UI, /solve/frame2d API) can consume it.

This is the gating round-trip for Phase 7 closure.

### Procedure

1. Reopen `phase07_minimal_frame.rvt`. Run `Convert to Analytical` on all 7 elements (or use Fixture 3 which already has the AnalyticalMembers).
2. Switch to a drafting view that contains detail-line representations of the analytical model. If no such drafting view exists in the fixture, author one:
   - Create a drafting view at appropriate scale.
   - Trace each AnalyticalMember as a detail line in the drafting view (Phase 5 ExportToPDA reads detail lines on a drafting view, not analytical members directly -- this matches the Phase 5 contract).
3. Run `PDA_Tools > Analytical > col1.stack > Export to PDA` (the Phase 5 Tier 1 frame exporter) on that drafting view.
4. Save the resulting canonical PDA JSON to a known path (e.g., `~/Documents/UAT/phase07_minimal_frame.json` on the Windows host).
5. Move the JSON to a host that runs the PDA frame2d browser UI (or POST it directly to the API):
   - Browser UI path: open `ui/frame2d/index.html`; load the JSON; click Solve.
   - API path: `curl -X POST http://localhost:8000/solve/frame2d -H "Content-Type: application/json" -d @phase07_minimal_frame.json`.
6. Inspect the returned reactions (FG vector at the restrained DOFs) and member forces.

### Expected outcome

Reactions and member forces match the analytical reference for the minimal-frame geometry within the same tolerance Phase 5 / Phase 4 UAT used (typically 1e-3 relative tolerance for displacements; reactions exact to within float roundoff for statically determinate frames).

The reference values can be hand-calculated for the minimal frame:
- 4 columns + 2 beams + 1 brace under the loading the engineer applies in step 4. (If the fixture has no nodal loads, FG should be zero everywhere except at supports under self-weight, depending on whether self-weight is exported.)
- For a determinate frame with simple support conditions, vertical reactions should sum to the total applied load.

The point of this check is not to prove the solver -- the solver is already tested in Phase 4. The point is to prove the analytical-member geometry that ConvertToAnalytical produces is consumable by the round-trip without geometry corruption (e.g., no zero-length members, no missing material/section).

### Pass criteria

- [ ] Phase 5 ExportToPDA produces a valid JSON with the expected node and member counts (4 columns + 2 beams + 1 brace -> 6 nodes for a portal-style frame, or 7 nodes if the brace adds a free vertex; member count matches geometry)
- [ ] frame2d UI loads the JSON without errors
- [ ] /solve/frame2d returns 200 OK with reactions in `FG` and member forces in `member_forces`
- [ ] Reactions match the hand-calculated reference within tolerance
- [ ] No NaN, inf, or zero-everywhere displacement vector

If this fails, capture the JSON and the failure mode in the resume signal (e.g., "ExportToPDA produced JSON but solve returned singular matrix" -- that points to a geometry/topology issue that ConvertToAnalytical introduced).

## Configurable Filter Walkthrough (REVIT-CONVERT-01, ROADMAP success criterion 5)

**Purpose:** Visual confirmation that the category filter is data-driven (a module-level dict) and not hard-coded into call sites. No code change is performed in this step.

### Procedure

1. Open `script.py` from the deployed pushbutton folder on the Windows host (`%APPDATA%\pyRevit\Extensions\PDA_customRevit.extension\PDA_Tools.tab\Analytical.panel\col1.stack\ConvertToAnalytical.pushbutton\script.py`) -- OR view it on GitHub.
2. Locate the module-level `SUPPORTED_CATEGORIES` dict near the top of the file. It should map `BuiltInCategory` enum values to handler function references, e.g.:
   ```python
   SUPPORTED_CATEGORIES = {
       BuiltInCategory.OST_StructuralColumns: convert_column,
       BuiltInCategory.OST_StructuralFraming: convert_beam_or_brace,
   }
   ```
3. Mental walkthrough: imagine adding a new entry for floors:
   ```python
   BuiltInCategory.OST_Floors: convert_slab,
   ```
   Plus a new `convert_slab(...)` handler. The call site in `_convert_one` (or equivalent dispatch) should look up the category in this dict and call the handler -- no `if/elif` ladder, no string matching, no hard-coded category list elsewhere.

### Pass criteria

- [ ] `SUPPORTED_CATEGORIES` exists as a module-level dict literal
- [ ] Dispatch in the conversion engine reads from this dict (no parallel hard-coded category list elsewhere in the file)
- [ ] Adding a new category would require touching ONLY the dict + a new handler function (engineer confirms by inspection)
- [ ] In-code comment near the dict references the v1.5+ Phase 15 extension path (so future-self knows this is the configuration surface)

This is a visual audit, not a runtime check. No conversion is invoked.

## Phase 7 Sign-Off

After all 5 sections pass, fill in:

- Date of UAT pass: ______
- Engineer initials: ______
- Windows host (machine name + Revit version): ______
- Sibling-repo HEAD at deploy time: ______ (sha)
- Notes / deviations: ______

If anything fails, do not sign off here -- raise the failure in the resume signal of Plan 07-03 Task 4 instead.

## Resume signals (Plan 07-03)

This runbook is consumed by Plan 07-03 Tasks 2, 3, and 4. After running the UAT successfully, the resume signal expected by Task 4 is:

```
Phase 7 UAT pass -- all 5 criteria green
Fixture 1: converted: 7 | already-associated: 0 | skipped (errors): 0 | total: 7. Single undo OK.
Fixture 2: converted: <N-1> | already-associated: 0 | skipped (errors): 1 | total: <N>. Linkify highlighted element <id>.
Fixture 3: converted: 0 | already-associated: 7 | skipped (errors): 0 | total: 7. No duplicates.
Tier 1 round-trip: reactions match reference within tolerance <X>.
Configurable filter: SUPPORTED_CATEGORIES dict confirmed at script.py line <L>.
```

If anything fails, list the criterion + the specific failure mode (e.g., "Fixture 3: TaskDialog showed converted: 7 instead of 0 -- duplicate AnalyticalMembers were created; idempotency check broken").
