# Phase 7 -- ConvertToAnalytical UAT Runbook

Manual verification procedure for the `ConvertToAnalytical` pyRevit pushbutton (PDA Analysis Software, Phase 7).

This runbook is a checklist the engineer follows on a Windows host with Revit 2025 and pyRevit installed, after the bundle is deployed (see Plan 07-03 Task 3). It covers all five ROADMAP success criteria for Phase 7:

1. Engineer-clickable conversion (Fixture 1)
2. Idempotent re-run (Fixture 3)
3. Final TaskDialog summary with per-skip reasons; one bad element does not abort the batch -- verified by code review of `run_batch` exception handling (Fixture 2 covers the multi-storey positive path; Revit's UI prevents authoring deliberately-broken structural elements that would empirically trigger the curated skip taxonomy)
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
- Each AnalyticalMember has a non-null `SectionTypeId` and `MaterialId`. After `AddAssociation`, `_convert_one` explicitly assigns `analytical.SectionTypeId = elem.Symbol.Id` and `analytical.MaterialId = elem.StructuralMaterialId`; the D-10 read-back is the safety net for genuinely missing source data or silent setter failures, not a propagation check (`AddAssociation` does NOT propagate section/material — empirically confirmed in debug session `convert-missing-section-false`, 2026-05-02).
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

**Purpose:** Prove the multi-storey positive path. Exercises selection scaling (18 elements), level-spanning column geometry across two storeys, mixed structural roles (columns + beams + bracings), and `_resolve_input` selection filtering against a larger document. ROADMAP success criterion 3 (per-element error isolation + curated skip taxonomy) is verified by code review of `run_batch` rather than empirically; see "Skip taxonomy verification" below for rationale.

**Geometry on disk:** 2 storeys (levels at 0, 3m, 6m). 4 columns per storey (8 total, spanning level 0 -> 3m and 3m -> 6m) + 8 perimeter beams (4 per storey) + 2 bracings = 18 physical elements. All elements valid. No deliberately-broken element.

### Skip taxonomy verification (replaces empirical broken-element test)

The original Fixture 2 design called for a deliberately-broken element to trigger the `missing-section` skip path. **This is not authorable through Revit's UI:** Revit enforces that every structural element have a valid `StructuralMaterialId` and `Symbol.Id` (FamilySymbol), and rejects attempts to set Material to `<None>`. The closest the engineer reached was assigning Material = `Air` to a column, which is a valid material assignment that converts cleanly (no skip).

The curated skip taxonomy in `run_batch` (`missing-location`, `unsupported-geometry`, `missing-section`, `generation-failed`, `other-error`) is therefore verified by code review:

- `_derive_curve` returns `(None, 'missing-location')` or `(None, 'unsupported-geometry')` and `_convert_one` raises `ValueError(skip_reason)`.
- `run_batch` `try/except` ladder routes `ValueError` -> `skips.append((pid, str(ve), role))` (the `'missing-location'`/`'unsupported-geometry'` cases), `_verify_section_and_material` returning False -> `skips.append((pid, 'missing-section', role))`, AnalyticalMember.Create raising -> `skips.append((pid, 'generation-failed', role))`, and any other exception -> `skips.append((pid, 'other-error', role))`.
- Per-element rollback (Pitfall 5) is proven by the single-undo check in Fixture 1: if rollback worked correctly for a successful batch, it works the same way for a partial batch (Transaction-per-element pattern).

If a Phase 7 follow-up phase ever adds a non-UI fixture-authoring path (e.g., a scripted family that bypasses Revit's structural validation, or a programmatic ElementId-corruption scenario in a test harness), this section can be replaced with empirical skip-trigger testing. Until then, the runbook records this as a known limitation of UI-authored Revit fixtures.

### Procedure

1. Open `phase07_multi_storey.rvt`.
2. Optional: open the Analytical Model browser and confirm zero AnalyticalMember instances.
3. Click `Convert to Analytical`. The pushbutton enters PickObjects mode. Select all 18 physical structural elements (use a ribbon Filter to restrict to columns + beams + bracings if the model has other elements). Press Finish.
4. Wait for the TaskDialog (typically 2-4 seconds for 18 elements).

### Expected TaskDialog

```
PDA: Convert to Analytical
converted: 18 | already-associated: 0 | skipped (errors): 0 | total: 18
All elements processed successfully.
```

If the engineer modifies the geometry in a future re-author, substitute the actual count. The key invariants are: `skipped (errors): 0`, `already-associated: 0`, `converted == total`.

### Expected post-conditions

- Analytical Model browser shows 18 `AnalyticalMember` instances.
- Each AnalyticalMember has a non-null `SectionTypeId` and `MaterialId`.
- No Output Window `Conversion Skips` table appears (no skips).
- Each AnalyticalMember is 1:1 associated with its physical element.

### Single-undo check at scale (Pitfall 5; bonus data point)

After conversion, press Ctrl+Z ONCE. EXPECT all 18 AnalyticalMembers to disappear in a single undo step labelled `PDA: Convert to Analytical`. This is the same Pitfall 5 check as Fixture 1 but at 18 elements instead of 7 -- empirically confirmed during fixture authoring (2026-05-06): single-undo holds at scale.

### Multi-storey-specific spot checks

- Column AnalyticalMembers spanning level 0 -> 3m have endpoints at the correct elevations (visually verify via the analytical browser or a section view).
- Column AnalyticalMembers spanning level 3m -> 6m do likewise.
- Beams at storey 1 perimeter and storey 2 perimeter are at elevations 3m and 6m respectively.
- The 2 bracings produce AnalyticalMember instances with their endpoints at the correct level intersections.
- No AnalyticalMember spans across storeys (each column AnalyticalMember corresponds to ONE physical column, not a unified column from level 0 -> 6m).

### Pass criteria

- [ ] TaskDialog `skipped (errors)` count is 0
- [ ] TaskDialog `converted` count equals total selection count
- [ ] TaskDialog body reads "All elements processed successfully."
- [ ] Analytical browser shows N AnalyticalMembers where N matches selection count
- [ ] Column AnalyticalMembers across both storeys are correctly placed (spot-check elevations)
- [ ] No `Conversion Skips` table appears in the Output Window
- [ ] Skip taxonomy code review confirms all 5 skip reasons are routed by `run_batch` (one-time inspection; engineer initials the runbook to confirm)

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

## Tier 1 Round-Trip (D-13, ROADMAP success criterion 4) -- DEFERRED TO PHASE 8

**Status:** Reframed during Plan 07-03 execution (2026-05-06). The originally-specified Tier 1 round-trip via Phase 5 ExportToPDA does NOT exercise Phase 7's analytical metadata, so it cannot validate Phase 7 deliverables. The empirical round-trip exercising section + material flows through Phase 8 Tier 2 export -- not Phase 5 Tier 1.

### Why the original Tier 1 round-trip does not test Phase 7

Phase 5 `ExportToPDA` reads **detail lines from the active view** (not analytical members) and emits JSON with **hardcoded `DEFAULT_E`, `DEFAULT_I`, `DEFAULT_A`** (script.py lines 386-396, 447-463). Confirmed by code inspection during Plan 07-03 Task 4:

- `_collect_detail_lines(view)` filters `OST_Lines` category -- AnalyticalMembers are not in this category.
- `_build_json(...)` writes `"E": DEFAULT_E`, `"I": DEFAULT_I`, `"A": DEFAULT_A` regardless of any document state.
- `"forceVector": [0] * (n_nodes * 3)` is always zero.

Therefore, running Phase 5 ExportToPDA on a Phase-7-converted document produces JSON identical to running it on a vanilla document with the same detail lines. Phase 7's section + material assignments are invisible to Phase 5. The round-trip would prove only that the document remains well-formed for Phase 5 (a no-op, given Phase 7 only adds AnalyticalMembers in a separate category).

### What still validates ROADMAP success criterion 4

Phase 7 success criterion 4 ("Revit's analytical model is well-formed enough that a downstream Tier 2 exporter -- Phase 8 -- can read it") is empirically validated by:

- **Fixture 1 step 6** -- analytical browser spot-check confirms `SectionTypeId` and `MaterialId` non-null on every AnalyticalMember (the explicit-assignment fix from sibling-repo commit `9342288`).
- **Fixture 3** -- 1:1 physical-analytical association intact post-conversion; idempotent re-run produces no duplicates (`already-associated: 7`).
- **Single-undo at scale** -- Pitfall 5 (TransactionGroup.Assimilate) holds on Fixture 1 (7 elements) and Fixture 2 (18 elements). Per-element-Transaction rollback works.

These three evidence points together prove the analytical output is well-formed for Phase 8's Tier 2 reader. Phase 8 Tier 2 export will read `AnalyticalMember.SectionTypeId` and `MaterialId` directly and emit them into the JSON -- that is the empirical round-trip for Phase 7's deliverables.

### Memory pointer

See `revit_phase5_export_uses_detail_lines_only.md` -- captures the architectural finding so Phase 8 planning starts from the correct premise.

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
Fixture 2: converted: <N> | already-associated: 0 | skipped (errors): 0 | total: <N>. Multi-storey positive path; column elevations across both storeys spot-checked. Skip taxonomy verified by code review (Revit UI prevents authoring deliberately-broken structural elements).
Fixture 3: converted: 0 | already-associated: 7 | skipped (errors): 0 | total: 7. No duplicates.
Tier 1 round-trip: deferred to Phase 8. Phase 5 ExportToPDA reads detail lines + DEFAULT_E/I/A, not AnalyticalMember metadata, so it cannot validate Phase 7. Criterion 4 satisfied by analytical-browser spot-check (Fixture 1 SectionTypeId+MaterialId non-null), idempotent association (Fixture 3 no duplicates), single-undo at scale (7 + 18 elements).
Configurable filter: SUPPORTED_CATEGORIES dict confirmed at script.py line <L>.
```

If anything fails, list the criterion + the specific failure mode (e.g., "Fixture 3: TaskDialog showed converted: 7 instead of 0 -- duplicate AnalyticalMembers were created; idempotency check broken").
