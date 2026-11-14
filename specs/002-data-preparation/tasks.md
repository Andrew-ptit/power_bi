# Tasks: Data preparation — phần 1

Input: spec.md, plan.md, research.md, data-model.md, contracts/preparation.md. Tất cả task chưa thực hiện. Các ID T001–T012 chỉ thuộc feature 002; không trùng nghĩa với T của baseline 001. TDD và synthetic/live checks bắt buộc theo AGENTS.md.

## Phase 1 — Contract setup

- [ ] T001 Chốt closed preparation schema và boundaries trong `contracts/preparation.md`, `pbip_assistant/schemas/preparation.schema.json`, `docs/current/{TASKPANE_UI,ARCHITECTURE,EXCEL_MCP_SPEC}.md`; characterization ở `tests/contracts/test_preparation_contracts.py` và route allowlist hiện có. Không đổi release version/legacy schemas.

**Consumes:** spec DP01–DP15. **Produces:** model field names/limits/error enums, schema version 1, existing source/Advanced boundaries unchanged.
1. Write `test_unknown_keys_rejected`, `test_preparation_cannot_expand_advanced_or_typed`, `test_original_routes_remain` with unchanged legacy fixtures and closed new shapes.
2. Run `py -m unittest tests.contracts.test_preparation_contracts -v`; observe new contract unavailable/invalid, not unrelated runtime failure.
3. Implement schema and owner-document mapping only; document imported-sheet exception and personal-result-copy boundary; do not globally broaden source writes.
4. Run same contract tests + `py -m unittest tests.contracts.test_coordinator_dispatch -v` after additive wiring exists; expected PASS at integration checkpoint, existing routes unchanged. Stage/commit only task paths.

## Phase 2 — Blocking foundations

- [ ] T002 Prove runtime preservation and restore feasibility using `tests/support/preparation.py`, `tests/live/preparation_gate_driver.js`, `tests/live/{create_fixture,server_support}.py`, `tools/live_excel_gate.py`; add isolated scenario selection without changing existing default sequence.

**Consumes:** T001 scope. **Produces:** supported-feature matrix and evidence for adapter in contract; this is a synthetic feasibility harness, not production write code.
1. Write independent expected oracle: two dependent sheets, same-named destination, scoped/global names, Table collisions, dates/styles/merged cells; personal-copy source fingerprint unchanged, undo/redo restoring stable-reference semantics. Include external links/protected structure as supported-or-explicit-reject cases.
2. Run new scenario against current implementation and record missing capability; no open user workbook. Extend harness `--scenario preparation` and gate marker guard without using deterministic planner as Codex evidence.
3. Exercise native all-sheet import, native personal copy, capture and restore actual affected content in marked disposable workbook; reject deleting/reinserting as proof if dependent formulas break. No arbitrary COM attachment to user instance.
4. Record live command/revision/time/dimensions/source hashes and success/recovery; set matrix supported/blocked per structure. If required baseline cannot round-trip, do not proceed to writable tasks T007/T009/T010; pure inventory/wizard can proceed. Commit harness/evidence metadata, no workbook binaries/secrets.

- [ ] T003 Build bounded journal in `pbip_assistant/sources/preparation/{__init__,model,journal}.py` with `tests/unit/test_preparation_journal.py`; use coordinator temp/clock owner, no workbook history raw payloads.

**Consumes:** contract models and T002 proof for production snapshot format. **Produces:** `RestoreJournal` interface exactly as contract.
1. Write tests `test_limits_include_pending_and_after_images`, `test_fifo_keeps_remaining_points_restorable`, `test_new_edit_discards_redo`, `test_oversize_and_backup_failure_zero_write`, `test_unknown_preserves_cursor`, `test_expiry_pinned_job` using injected small budgets and assert production defaults 10/256MiB/64MiB.
2. Run `py -m unittest tests.unit.test_preparation_journal -v`; observe missing journal behavior.
3. Implement reserve→verify-before→attempt→verify-after→commit, hash validation, point/cursor CAS, dependency-safe FIFO and marked cleanup. Bytes physical including reservation, not base64-character count. No executable grant in retained metadata.
4. Same command PASS; add disk-error and invalid snapshot injections; commit scope.

- [ ] T004 Add safe recovery owner/reattach in `pbip_assistant/coordinator/{runtime,server}.py`, `pbip_assistant/coordinator/endpoints/preparation.py`, `pbip_assistant/sources/preparation/store.py`; tests `tests/integration/test_preparation_sessions.py` and existing session suites.

**Consumes:** T003 journal. **Produces:** `PreparationStore.attach`, preparation logical TTL, additive authenticated endpoints/capability, no legacy auth regression.
1. Write `test_page_close_retires_transport_but_retains_committed_recovery`, `test_reattach_cannot_reuse_old_approval`, `test_clone_and_unsaved_ambiguity_no_ownership`, `test_expiry_cannot_be_revived`, `test_two_requests_cas`, `test_close_waits_for_job`.
2. Run `py -m unittest tests.integration.test_preparation_sessions -v` RED. Preserve `test_session_close_invalidates_token_and_clears_state` and deferred cleanup tests unchanged.
3. Implement distinct server recovery owner/claim protocol and original TTL envelope. Preparation-only detach retires transport but retains committed recovery; explicit close clears attached recovery too. New bootstrap auth/verified claim needed; marker not credential, ambiguous unsaved target needs explicit fresh claim as contract. Add bounded image transfer begin/chunk/finish contracts and tests for offsets/hash/expanded bytes/wrong session. Expire process-local recovery on original TTL; restart excluded. Do not remove token retirement or keep bearer tokens in workbook/browser storage.
4. Run new session tests plus `py -m unittest tests.integration.test_coordinator_runtime tests.integration.test_coordinator_server -v`; PASS exact 1.800/28.800 boundaries and locks. Commit scope.

## Phase 3 — US1 source inventory and native import

- [ ] T005 [US1] Implement read-only inventory/mapping in `pbip_assistant/sources/preparation/inventory.py`, endpoint/controller selection; tests `tests/unit/test_preparation_inventory.py`.

**Consumes:** binding claim, existing bounded parser guards. **Produces:** `inventory_folder` and `review_import` immutable source/mapping review.
1. Tests `test_mixed_folder_one_csv_one_sheet_all_xlsx_sheets`, `test_names_case_unicode_length_collisions`, `test_source_hash_changes_block_review`, `test_root_escape_and_zip_bomb_blocked`, `test_existing_append_connector_unchanged`; assert exact oracle mapping and unchanged source bytes.
2. `py -m unittest tests.unit.test_preparation_inventory -v` RED.
3. Enumerate immediate sorted CSV/XLSX only, no recursive traversal; reject ambiguity/unsupported per file and expose explicit selection. Guard root/path/bytes/expanded package and stale metadata; don't log paths/cells.
4. Same suite PASS plus focused existing ingestion tests; commit scope. Depends T001/T004; can be built read-only before T002 passes.

- [ ] T006 [US1] Implement reviewed CSV literal import adapter in `pbip_assistant/excel_addin/preparation_runtime.js`, wiring in `taskpane.{html,js}`; tests `tests/taskpane/taskpane_preparation_runtime.js` and `tests/integration/test_preparation_import.py`.

**Consumes:** reviewed mapping + prepared journal attempt. **Produces:** runtime receipts with actual sheet IDs and full-scope fingerprint, not client-provided ownership.
1. Tests formula-like `=1+1` remains literal text, `00123` preserved, quoted/newline CSV parsed correctly, ambiguous encoding/delimiter/width blocks, collision doesn't touch existing sheet, no write when backup not verified.
2. `node tests/taskpane/taskpane_preparation_runtime.js` RED; `py -m unittest tests.integration.test_preparation_import -v` RED for new route.
3. Reuse CSV parser and safe text-before-values writer; capture bounded evidence and invalidate after partial writes. Add node script to existing automated discovery without removing any of 12 current scripts.
4. Same suites PASS and affected runtime import/undo success+failure from T002; commit scope. Write capability remains disabled until journal/live prerequisites pass.

- [ ] T007 [US1] Implement native XLSX group insertion/preservation read-back in `preparation_runtime.js`, store ownership receipts in `sources/preparation/store.py`; extend `tests/taskpane/taskpane_preparation_runtime.js` and live preparation scenario.

**Consumes:** T002 support matrix, T003/T004, T005 reviewed packages. **Produces:** dependency-complete group import with exact mapping and receipts.
1. Tests `test_group_import_retains_cross_sheet_meaning`, `test_rename_and_table_collisions_no_external_source_links`, `test_unsupported_host_zero_write`, `test_partial_group_precise_receipt_no_replay` with real synthetic oracle as qualification.
2. Run taskpane runtime suite RED; stage new live assertions before implementation.
3. Native insertion of all sheets per XLSX, reviewed collision mapping, verify formulas/formats/names/shape and source unchanged. No generic OOXML replacement or use of Advanced values-only strip path. Commit ownership only after verified full group.
4. Same focused suites PASS plus actual live import/undo/redo proof; unsupported remains explicit blocked. Commit scope.

## Phase 4 — US2 local scan, questions and wizard

- [ ] T008 [US2] Implement `scan_sources`, `build_cleanup_preview`, `answer_question` in `sources/preparation/{cleaning,store}.py`; UI `preparation_controller.js`, taskpane HTML/CSS; tests `tests/unit/test_preparation_cleaning.py`, `tests/taskpane/taskpane_preparation_wizard.js`.

**Consumes:** source revision and contract answer CAS. **Produces:** immutable findings/questions/preview, no automatic write or Codex call.
1. Assert trim `" KH01 "→"KH01"`, `"00123"` unchanged, `03/04/2026` unresolved until explicit DMY/MDY, decimal separators explicit, formula/duplicate/missing only flagged; invalid date reported, not coerced. Tests count full vs sampled findings accurately.
2. Run `py -m unittest tests.unit.test_preparation_cleaning -v` and `node tests/taskpane/taskpane_preparation_wizard.js` RED.
3. Implement source→format→exceptions→review groups, one question at a time, answer index and Back/Next. CAS source/answer changes invalidate preview/grants; independent answers retained; use textContent for user input. Add controller asset to allowlisted static serving and test discovery.
4. Same commands PASS; taskpane keyboard/360px and dirty review/live mount check. Independent read-only MVP after T001/T005; simulated IO is not live qualification. Commit scope.

## Phase 5 — US3 apply and US4 recovery journey

- [ ] T009 [US3] Implement exact-preview Apply target strategies in `sources/preparation/store.py`, `preparation_runtime.js`, toolbar controller; tests `tests/integration/test_preparation_apply.py` and `tests/taskpane/taskpane_preparation_runtime.js`.

**Consumes:** T003/T004 + T006/T007 + T008. **Produces:** `approve_preview`, `begin_mutation`, `complete_attempt` contract with verified result and journal point.
1. Tests `test_imported_ownership_allows_inplace_only`, `test_personal_sheet_creates_new_result_original_unchanged`, `test_formula_and_format_outside_diff_preserved`, `test_stale_rejects_before_write`, `test_no_backup_no_write`, `test_readback_failure_partial_unknown_no_retry`.
2. `py -m unittest tests.integration.test_preparation_apply -v` and node runtime suite RED.
3. Native copy personal source to unique result; keep disclosed native dependencies, do not retarget guesses. Apply only approved cells/type/number-format changes. Verify full affected scope and original personal source; consume grant once; journal commits only on receipt verification.
4. Same suites PASS and affected actual Excel apply/recovery; commit scope. Do not claim complete until actual success/recovery gate passes.

- [ ] T010 [US4] Wire ↶/↷, reattach and conflict handling in `preparation_{runtime,controller}.js`, journal/store and additive endpoints; tests `tests/integration/test_preparation_recovery.py`, `tests/taskpane/taskpane_preparation_wizard.js`, live preparation driver.

**Consumes:** committed T009/T007 journal points and T004 reattachment. **Produces:** `checkout_restore`/`finish_restore` receipts, cursor, bounded UI history and remaining-step/expiry indicators.
1. Assert multi undo/redo, new edit truncates redo, native source sheet identity preserved, manual edit requires safe conflict handling, same-marker clone does not inherit write grant, pending failure keeps cursor, evicted/expired point rejected, pane reload retains valid journal.
2. `py -m unittest tests.integration.test_preparation_recovery -v` and wizard/runtime suites RED.
3. Before restore, recheck exact binding/source fingerprint and obtain fresh grant; restore proven scope, read-back then move cursor. Show precise expiry/eviction/unknown status and no automatic replay. Navigation buttons never invoke restore. Auth/close/TTL unchanged.
4. Same suites PASS plus real close/open pane, unsaved workbook claim, quota/expiry/conflict/recovery journey; commit scope.

## Phase 6 — Integration and qualification

- [ ] T011 Reconcile baseline overlap and regressions in `specs/002-data-preparation/acceptance.md`, `tests/required_cases.json`, `tests/taskpane/test_taskpane_js.py`, canonical owner docs and focused baseline journeys; preserve all required cases and old contracts.

**Consumes:** T001–T010. **Produces:** each DP/S/SC linked to retained or new behavior proof, no duplicate authority/framework.
1. Map baseline 001 US2 full read-back and US8 questions to reuse vs feature-specific behavior; no checkbox auto-completion of baseline.
2. Add only missing characterization for new error/guard/routing/asset; run affected tests RED then minimal integration fix then GREEN.
3. `py tools/run_checks.py fast`, `py tools/run_checks.py runtime`, `py -m unittest discover -s tests -v`; all existing taskpane scripts remain in gate, new scripts added.
4. Scope commit, retain exact-current commands/revision/elapsed/pass/fail/skip in acceptance matrix.

- [ ] T012 Qualify live synthetic success/recovery in `tests/live/preparation_gate_driver.js`, `tests/live/README.md`, `specs/002-data-preparation/acceptance.md` and `docs/current/CURRENT_STATUS.md`; no release bump before global qualification.

**Consumes:** T011 exact revision and existing synthetic gate. **Produces:** live evidence or honest Blocked/Not run.
1. Run complete import→scan→answer/edit→preview→approve→apply→undo→redo→pane reopen journey, plus unsupported XLSX, personal source, manual conflict, quota, expiry and injected read-back failure.
2. Report command/revision/layer/time/errors, revision/step changes, result dimensions, source fingerprints; independently assert formulas/formats/name semantics. No user workbook, no private gate key in report.
3. Advanced Deferred and Codex Not applicable for this local-only feature; missing Excel/UI/auth is Blocked, not handed to user as implementer testing. Commit evidence metadata only.

## Dependencies and execution order

`T001→T002→(write path)`; `T001→T003→T004`; `T005→T006/T007`; `T005→T008`; `T002+T004+T006/T007+T008→T009→T010→T011→T012`.

US1, US2 and US3 each have independent fixtures but writable stories depend on US4 journal foundation. Safe demo MVP is read-only US2 wizard/scan with fixture inputs; shipped part1 requires all four stories. No enablement of write paths on simulation alone.

## Parallel opportunities

After T001: synthetic host feasibility and pure cleaning fixtures can be explored independently; never parallel mutations against the same Excel workbook/coordinator. After inventory types are locked, a wizard test fixture and source-package oracle can be prepared separately. No tasks marked [P] because final deliverables share store/runtime interfaces and must integrate sequentially. Examples per story: US1 source fixture vs UI mock only; US2 pure parser assertions vs accessible markup review; US3/US4 serialize all runtime writes.

## Implementation strategy

Choose execution method after plan review; recommended native implementation with independent boundary review, because IO/journal/auth are tightly coupled. At execution start reconcile current dirty tree and isolate without resetting/stashing user work. Tests-first behavior and independent oracles, focused checks per batch, full regression only at cross-cutting boundary/new concerns. Commit only owned files after each coherent task/batch, update same acceptance matrix, and record next unfinished task there. No second plan.
