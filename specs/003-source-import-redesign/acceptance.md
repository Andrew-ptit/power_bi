# Evidence — Feature 003

| Task | Status | Command | Output | Revision |
|---|---|---|---|---|
| T301 | Blocked (§10) | `py tools/review_003.py --task T301` · `py -m unittest tests.contracts.test_source_import_contracts tests.contracts.test_preparation_contracts tests.contracts.test_coordinator_dispatch -v` | Static exit 0, 0/6 files changed since snapshot. Gate exit 1, 13 tests OK and 1 loader error (missing test_source_import_contracts). Stopped before implementation: the active inventory caller sends relativePath and its handler requires that field, while T301 replaces it with items. | bf26fda + pre-existing working tree |
| T301 | Pass | `py tools/review_003.py --task T301` · `py -m unittest tests.contracts.test_source_import_contracts tests.contracts.test_preparation_contracts tests.contracts.test_coordinator_dispatch -v` | 4/6 allowlisted files changed, exit 0. 21 tests in 0.472s, OK. Independent review ACCEPT after absolute-root fix. Isolated development only. | c3fdd51 |
| T303 | Blocked (§10.2) | `py tools/review_003.py --task T303` · `py -m unittest tests.unit.test_preparation_browse tests.unit.test_preparation_inventory -v` · `py -m unittest tests.contracts.test_source_import_contracts -v` | 0/5 changed. Nine inventory tests OK, one loader error (browse suite absent), exit 1. Eight contract tests OK. Required browse path absent from POST_ENDPOINTS, STATE_PATHS and route fixture. Registration and fixture outside allowlist. | c3fdd51 |
| T303 | Blocked (§10.1) | `py tools/review_003.py --task T303` · `py -m unittest tests.unit.test_preparation_browse tests.unit.test_preparation_inventory -v` · `py -m unittest tests.contracts.test_source_import_contracts tests.contracts.test_coordinator_dispatch tests.unit.test_csv_typing -v` | Static 7/7 in scope. Unit gate: 23 tests in 9.807s, 3 failures and 1 error (CP1252, single column, pre-inference cell limit, XLSX summary). 31 contract/dispatch/typing tests OK. HTTP browse and stale-claim cases passed. Independent review rejected malformed XLSX error isolation. Separate direct T302 frame check: column ["1.234","2.345"] returned [1.234,2.345] with GROUP_SEPARATOR; §4 requires [1234,2345]. Stop before editing read-only T302. T304 endpoint packages branch approved separately. | acb01cf + T303 WIP |
| T302 | Pass (grouped-number correction); further typing discrepancies blocked under §10.1 | `py tools/review_003.py --task T302` · `py -m unittest tests.unit.test_csv_typing -v` | Static exit 0, 2/3 in scope. 25 tests OK in 0.040s. Independent review ACCEPT. Dot/comma grouped values with plain integers produce 1234 and 12, General, GROUP_SEPARATOR. Separate spec fixture probe: empty numeric/date cells retain General/yyyy-mm-dd instead of @; US2 fixture yields five decisions including unit_price and note, but US3 specifies three exceptions. Wave B WIP retained pending scope decision. | e394997 |
| T302 | Pass | `py tools/review_003.py --task T302` · `py -m unittest tests.unit.test_csv_typing -v` | Two files in scope, 28 tests OK in 0.023s. Independent review ACCEPT. Fixture US2/US3 produced only qty/code/created exceptions. Empty numeric/date cells retained empty string and @. User confirmed SI04 for T305: show file count on selection, read selected files and show sheet/column statistics only after Import. | 1f97d2f |
| T303 | Pass (Wave B gate) | `py tools/review_003.py --task T303` · `py -m unittest tests.unit.test_preparation_browse tests.unit.test_preparation_inventory -v` · `py -m unittest tests.contracts.test_source_import_contracts tests.contracts.test_coordinator_dispatch -v` | Static exit 0; seven authorized files across both passes. 25 unit tests OK in 5.857s; 12 contract/dispatch tests OK in 0.382s. Reviewer ACCEPT. Loopback HTTP browse, stale claims, selected-only reads, mixed valid/malformed XLSX, CP1252 and size limits verified. Pending T304: legacy direct HTTP test still submits obsolete inventory payload. | 6696a4b |
| T304 | Blocked (10.1, before implementation) | `py tools/review_003.py --task T304` / `py -m unittest tests.contracts.test_source_import_contracts.SourceImportContractTests.test_packages_rejects_unknown_date_system -v` | 0/8 implementation files changed. T301 rejects explicit invalid enum as INVALID_REQUEST before dispatch; contract section 3 calls for DP_DATE_SYSTEM_REQUIRED for invalid/missing system when dates exist. Baseline package/API gate exit 0. Eight baseline recovery tests passed; conditional fixture update not applied. | c6e5e10 |
| T304 | Blocked (10.2/10.4, physical recovery verification) | `py tools/review_003.py --task T304` / `py -m unittest tests.unit.test_preparation_packages tests.integration.test_preparation_api -v` / `py -m unittest tests.integration.test_preparation_mutation.PreparationMutationTests.test_approved_import_requires_verified_before_and_actual_after -v` | 7/8 in scope. 19 package/API tests pass. Independent loopback probe: invalid 400 INVALID_REQUEST; omitted with date 409 DP_DATE_SYSTEM_REQUIRED; serials 46115/44653; nested CSV imported, broken peer skipped, changed file rejected. Conditional Qty fixture corrected after reproduction. Physical verifier still requires @ for all CSV cells; journal undoCount=0, expected 1 (1.054s). Independent review also reproduced delayed approval binding to a different date frame. No live write. | c6e5e10 + T304 WIP |

| T304 | Pass | `py tools/review_003.py --task T304` / `py -m unittest tests.unit.test_preparation_packages -v` / `py -m unittest tests.integration.test_preparation_api -v` / `py -m unittest tests.unit.test_csv_typing -v` / `py -m unittest tests.integration.test_preparation_mutation -v` / `py -m unittest tests.integration.test_preparation_direct -v` | Static exit 0: 16 allowlist, 14 changed, no red flags. Gate 16 package + 8 API + 28 typing + 8 mutation + 16 direct tests OK, exit 0 each; affected preparation batch 115 tests OK. CSV frame is typed unconditionally (no backup/text branch): Qty `2` + `General`, dated columns serial 1900/1904, empty cell `null` + `General`. Physical verifier compares package `numberFormats`; typed import now journals with undoCount=1 and a wrong format still fails. Delayed approval bound to the old `dateSystem` frame returns DP_REVIEW_STALE. Oversized/ragged file skipped per file. No live Excel write. Fast gate Not run (worktree has no .certs). | c6e5e10 + T304 completion |

After T303, `py tools/run_checks.py fast` ran 1,271 tests in 284.807s with 2 failures and 3 skips. The isolated worktree lacked local HTTPS development credentials. After linking its ignored .certs directory to the existing local development directory, `py -m unittest tests.integration.test_preparation_gate -v` passed in 3.153s. The direct-import HTTP test still expects the old request. Full fast regression has not been rerun.

| T305 | Pass | `node tests/taskpane/taskpane_assistant_browser.js` / `node tests/taskpane/preparation_native_mutations.js` / `node tests/taskpane/taskpane_preparation_startup.js` / `py -m unittest tests.taskpane.test_taskpane_js -v` | Browser gate 10/10 cases, exit 0: folders before files, breadcrumb, navigation keeps selection, select-all scoped to the folder, file count before import and sheet count after import, exact items + probed `dateSystem` posted, exceptions/skipped rendered without raw values or paths, no preview/question DOM, Vietnamese empty/cancel strings, text-not-HTML. Runtime writes typed rows with per-cell `numberFormats`, blank cells stay `null`, `probeDateSystem` returns 1900/1904 and rejects unknown. Taskpane module: 14 tests OK. No live Excel write. | e720bd6 + T305 completion |

| T306 | Pass | `node tests/taskpane/taskpane_assistant_journey.js` / `node tests/taskpane/taskpane_assistant_entry.js` / `node tests/taskpane/taskpane_preparation_wizard.js` / `py -m unittest tests.taskpane.test_taskpane_js -v` | Journey gate 6/6: two steps only, no cleaning wizard DOM, import → verified re-read enables `2. Đề bài`, workbook choice re-reads without importing, failed re-read disables Đề bài and shows `Đọc lại nguồn`, `+ Thêm nguồn` reopens the same folder and keeps the skipped selection. Entry 8 cases; headless controller scan keeps `wizard.state`; taskpane module 15 tests OK. Cleaning client path removed from entry/bridge/controller/taskpane; affected preparation batch 133 tests OK. No live Excel. | 96280ec + T306 completion |

| T307 | Pass (003 scope); runtime/full gate Blocked on Excel parity | `py tools/run_checks.py fast` / `py tools/run_checks.py runtime` / `py -m unittest discover -s tests -v` / `node tests/taskpane/taskpane_assistant_browser.js` / `node tests/taskpane/taskpane_assistant_journey.js` | fast `run=1288 failed=0 errors=0 skipped=3 elapsed=215.501s` exit 0; runtime `run=13 failed=2 errors=0 skipped=1 elapsed=434.416s` exit 1; discovery `Ran 1304 tests`, 1 failure, 7 skips, 667.843s, exit 1. All failures are the pre-existing `tests.runtime.test_typed_local_parity` `PARITY_FIXTURE_TIMEOUT` (no Excel COM fixture), outside 003. Matrix S01–S13 / SI01–SI15 / SC01–SC08 filled; two new taskpane cases registered; stale assistant-v1 required cases removed. Live Excel Not run. | 0046684 + T307 completion |

Approved contract amendment 2026-11-20: `readingDecisions` (`ENCODING_FALLBACK` / `DELIMITER_INFERRED`) and package `reviewHash` bound to `dateSystem`.
Approved scope expansion 2026-11-20: `pbip_assistant/sources/preparation/csv_typing.py`, `pbip_assistant/sources/preparation/package_preservation.py`, `tests/unit/test_csv_typing.py`, and the spec/contract/tasks/acceptance documents listed under T304.
Approved requirement change 2026-11-20: an empty CSV cell stays `null` with numberFormat `General` (replaces `""` + `@`); the physical verifier compares each package `numberFormats` entry instead of requiring `@`.
Approved decision 2026-11-20: keep `reviewHash = hash(mappingHash, reviewId)` so each explicit review is a distinct revision and rotates the native XLSX namespace.
Approved scope expansion 2026-11-20 (T305): `pbip_assistant/excel_addin/taskpane.js` (browser mount), `tests/taskpane/preparation_native_mutations.js` (typed write fixtures) and `tests/taskpane/taskpane_preparation_startup.js` (load the browser module).
Approved decision 2026-11-20 (T305): before Import the footer shows only the selected file count; column/kind statistics and the created-sheet count appear in the report after Import (SI04).
Approved decision 2026-11-20 (T305): a failed date-system probe blocks the import with a clear message; imported files leave the selection while skipped files stay selected for retry.
Approved decision 2026-11-20 (T306): the business handoff uses the post-import workbook scan (`businessSourcesFromScan`); no cleaning Apply runs and no extra cell is written.
Approved decision 2026-11-20 (T306): a failed re-read keeps the import report, disables `Đề bài` and offers `Đọc lại nguồn`; `+ Thêm nguồn` reopens the same folder with the pending selection.
Approved scope expansion 2026-11-20 (T306): headless `preparation_controller.js`, `businessSourcesFromScan` in the bridge with the client cleanup APIs removed, `assistant_browser.reopen()`, and the bridge/direct test fixtures.

## Acceptance matrix — S / SI / SC (T307)

Statuses: **Pass** = automated evidence on this revision; **Blocked** = no automated or live evidence yet; **Not run** = live Excel not executed. Unit/HTTP/Office.js simulation is never marked as live verification.

### US1–US4 scenarios

| ID | Evidence (test / file) | Status |
|---|---|---|
| S01 | `tests.unit.test_preparation_browse` (folders first, `.csv`/`.xlsx` only, name sort); `taskpane_assistant_browser` case 1 | Pass |
| S02 | browse escape/reparse tests; `taskpane_assistant_browser` cases 1–2 (breadcrumb, `↑ Lên cấp trên`) | Pass |
| S03 | browse/inventory selection tests; browser cases 2–3 (selection kept across folders, select-all scoped); footer counts files before import and sheets in the report (approved SI04) | Pass |
| S04 | browser case 9 (`Chưa chọn thư mục.`, `Thư mục này không có file .csv hoặc .xlsx.`) | Pass |
| S05 | `tests.unit.test_csv_typing`, `test_preparation_packages` (number + `General`), `test_preparation_direct` (typed after-image), `preparation_native_mutations` (typed write) | Pass (live Not run) |
| S06 | `test_csv_typing`: `LEADING_ZERO_TEXT`, `PRECISION_TEXT`, `MIXED_TYPE_TEXT` | Pass |
| S07 | `test_csv_typing` 1900/1904 serial, invalid date text; packages `DP_DATE_SYSTEM_REQUIRED`; runtime `probeDateSystem` | Pass (live Not run) |
| S08 | `test_csv_typing` header `@`, formula-like text, empty cell `null` + `General` (approved change 2026-11-20) | Pass |
| S09 | `test_import_report_lists_decisions_with_reason_codes`, `test_report_has_no_absolute_path_or_raw_row`; browser case 7 (samples never rendered) | Pass |
| S10 | `test_ragged_csv_skipped_but_other_files_import`, `test_oversized_csv_is_skipped_without_blocking_other_files` | Pass |
| S11 | `taskpane_assistant_journey` case 3 (import → re-read → `2. Đề bài` enabled) | Pass (live Not run) |
| S12 | `taskpane_assistant_entry` case 4 / journey case 4 (workbook choice imports nothing, no write path) | Pass (live Not run) |
| S13 | `taskpane_assistant_entry` case 9: no usable workbook data → no scan, `Đề bài` stays off, explicit message, no empty session | Pass |

### Functional requirements

| ID | Evidence | Status |
|---|---|---|
| SI01 | journey gate: HTML has `1. Nguồn`, `2. Đề bài`, no clean step | Pass |
| SI02 | browse + browser cases 1–2 | Pass |
| SI03 | browse/inventory tests (200-file limit, duplicates); browser cases 2–3 | Pass |
| SI04 | browser reads only on `Nhập vào workbook`; footer shows file count only before import | Pass |
| SI05 | `test_xlsx_package_unchanged`; `mapInventory` collision test; direct import | Pass (live Not run) |
| SI06 | `test_csv_typing` full rule table | Pass |
| SI07 | journey case 2 (no wizard/date select); browser case 8 (no preview DOM) | Pass |
| SI08 | package report tests; browser case 7 | Pass |
| SI09 | package/API skipped-file tests | Pass |
| SI10 | browse/inventory/package tests (ragged, 64 MiB, 100k rows, 200 columns, 400k cells, escape, stale source, protected) | Pass |
| SI11 | entry/journey workbook cases (no import, no cell write; Office.js simulation only) | Pass (live Not run) |
| SI12 | journey case 3; entry case 3 (`Đề bài` only after verified re-read) | Pass |
| SI13 | report has no raw rows/paths; browser renders every value with `textContent`; no AI call in source path | Pass |
| SI14 | Static contract (`taskpane_assistant_browser` case 12): 32px rows, `overflow-wrap`, `aria-live` regions, native button/checkbox controls; real 360px rendering | Pass (static); live visual Not run |
| SI15 | `tests.taskpane.test_taskpane_js` 15 tests; all taskpane scripts run in the gate; 2 new scripts registered in `tests/required_cases.json` | Pass |

### Success criteria

| ID | Evidence | Status |
|---|---|---|
| SC01 | `test_deterministic_twice_identical`; US2 oracle fixture | Pass |
| SC02 | typed frame assertions in `test_preparation_packages` and `test_csv_typing` | Pass (live Not run) |
| SC03 | `test_import_report_lists_decisions_with_reason_codes`; browser exceptions block | Pass |
| SC04 | journey cases 1–2; browser case 8 | Pass |
| SC05 | `taskpane_assistant_browser` case 11 (3 levels, selection survives two ups) + case 12 (narrow-layout/keyboard static contract); real 360px UI | Pass (automated); live visual Not run |
| SC06 | ragged/oversize skip tests; no-sheet-for-skipped assertions | Pass |
| SC07 | workbook branch simulated (no import); live fingerprint comparison | Not run (live) |
| SC08 | Fast green (`run=1288`, 3 skips); runtime and full discovery fail only the pre-existing Excel parity case (`PARITY_FIXTURE_TIMEOUT`, outside 003) | **Blocked** for "all three green"; 003 scope Pass |

## Gate evidence (T307, 2026-11-20)

Worktree `.artifacts/worktrees/source-import-003`, branch `codex/source-import-003`, HEAD `0046684` plus the T307 working tree.

| Command | Result |
|---|---|
| `py tools/run_checks.py fast` | `gate=fast run=1288 failed=0 errors=0 skipped=3 elapsed=215.501s`, exit 0 |
| `py tools/run_checks.py runtime` | `gate=runtime run=13 failed=2 errors=0 skipped=1 elapsed=434.416s`, exit 1 — both failures are `tests.runtime.test_typed_local_parity` raising `Blocked: PARITY_FIXTURE_TIMEOUT; [parity] save-synthetic-fixture` (no usable Excel COM fixture in this environment) |
| `py -m unittest discover -s tests -v` | `Ran 1304 tests in 667.843s`, `FAILED (failures=1, skipped=7)` — the single failure is the same `test_python_executor_matches_excel_m_for_all_15_operations` parity case with the same timeout |
| `node tests/taskpane/taskpane_assistant_browser.js` | `assistant browser: 10 cases passed` |
| `node tests/taskpane/taskpane_assistant_journey.js` | `assistant journey: 6 cases passed` |

Scope split (approved 2026-11-20): fast is green. The runtime/full-discovery failures are the pre-existing Excel-runtime parity gate (`PARITY_FIXTURE_TIMEOUT`), not feature 003 code; they remain **Blocked** and are not counted as 003 passes. Live Excel end-to-end remains **Not run**; no workbook was opened or written.

`tests/required_cases.json` now matches discovery again (three stale assistant-v1 ids removed, two feature-003 taskpane cases added): `py tools/run_checks.py fast --list` reports `gate=fast cases=1288`.

### T307 follow-up 2026-11-20 — closing the blocked rows

- **S13** now has an automated case: choosing workbook data with no usable source keeps `Đề bài` off, shows the explicit message, starts no scan and creates no empty session.
- **SI14 / SC05** are covered by a static accessibility/narrow-layout contract (32px row hit target, `overflow-wrap`, horizontal overflow disabled, `max-width: 100%`, `aria-live` regions, native button/checkbox controls) plus a real three-level browser navigation test that keeps the selection across two ups. Real 360px rendering is still only verified manually/live; it is not claimed as automated evidence.
- A real bug was found by the three-level test and fixed: folder navigation joined only the folder name, so entering a folder inside a folder produced the wrong `relativePath`.

Re-run after the follow-up: `node tests/taskpane/taskpane_assistant_browser.js` → `12 cases passed`; `node tests/taskpane/taskpane_assistant_entry.js` → `Assistant single entry guards passed` (9 cases); `node tests/taskpane/taskpane_assistant_journey.js` → `6 cases passed`; `py -m unittest tests.taskpane.test_taskpane_js` → 15 tests OK.

### Live verification runbook (user-run, Excel Desktop)

- **Typed parity / SC08**: `py tools/run_checks.py runtime` on a machine where Excel can be automated. Expect `run=13 failed=0 errors=0`. If it still prints `Blocked: PARITY_FIXTURE_TIMEOUT; [parity] save-synthetic-fixture`, Excel could not create/save the synthetic fixture (check Excel opens, no dialog/modal, COM automation allowed); this is a runtime prerequisite, not feature 003.
- **T308 live source journey**: use a synthetic folder (CSV with number/date/leading-zero columns + one broken CSV), browse two levels, select, Import, then read `numberFormat` and `typeof values` back from Excel and compare with the T304 oracle. Record it as `Passed` only with the actual read-back; otherwise `Not run` with the exact reason. Never use a user workbook as the fixture.

### T307 follow-up 2 2026-11-20 — served asset route

During the user-run UI check the served `taskpane.html` already contained the new markup, but `/assets/assistant_browser.js` returned `404 NOT_FOUND`: the coordinator static map in `pbip_assistant/coordinator/server.py` did not list the new script, so the real task pane could not start even though every node test passed (node tests read files from disk, not over HTTP). The route is now served, and `tests/contracts/test_taskpane_asset_routes.py` asserts that every `/assets/*.js|css` referenced by `taskpane.html` has a route in the server.

Verified against the running coordinator: `GET https://localhost:3079/assets/assistant_browser.js` → 200 with the served source; `GET /taskpane.html` contains `#assistant-browser` and `2. Đề bài` and no `#assistant-step-clean`. The coordinator rewrote `tools/excel_addin/manifest.xml` and `C:\AddinManifests\manifest.xml` with the same SHA-256 and a fresh `channel` query; Excel must be reloaded (and the Office cache cleared if the old pane persists).

### T307 follow-up 3 2026-11-20 — attach before browse

The first real task-pane run showed `Cannot read properties of null (reading 'preparationId')`: the browser called `browse` before any preparation attachment existed, so `send()` dereferenced a null state. The old entry flow attached inside its inventory wrapper; the T305 browser path did not. `browse` and `inventorySelection` now `await attach()` first, and `tests/taskpane/taskpane_preparation_bridge.js` asserts `attach` precedes `browse` and that the request carries the attached `preparationId`.

Served-asset verification after the fix: `GET /assets/preparation_bridge.js` matches `async function browse(...){ ... await attach(); ... }` for both `browse` and `inventorySelection`. The user-selected folder is `C:\Users\COLAIG\Downloads\VietLogix_SupplyChain_eDA2026_Dataset`, which contains only a same-named subfolder; the eight CSV files live in that inner folder, so the browser must be entered one level down (or that inner folder picked directly).

### T307 follow-up 4 2026-11-20 — business handoff hash

The first live import succeeded (3 files → 3 sheets), but `2. Đề bài` then showed `DP_SOURCE_STALE`. Cause: `businessSourcesFromScan().validate()` returned `sources`/`sourceLabels` but omitted `observedHash`, while `flowPreparedWorkbookSources` compares `fresh.observedHash !== review.observedHash`; `undefined` can never equal the reviewed digest. The validator now returns the same reviewed hash, and `tests/taskpane/taskpane_preparation_bridge.js` asserts `(await handoff.validate()).observedHash === handoff.observedHash`.

Served-asset verification after restart: `/assets/preparation_bridge.js` contains both `await attach()` before `browse` and the `observedHash` return in `validate`.

### T307 follow-up 5 2026-11-20 — fewer clicks in the source tab

Approved: a picked folder that contains no `.csv`/`.xlsx` but exactly one child folder now opens that child automatically (up to three wrapper levels; breadcrumb and `↑ Lên cấp trên` still work). This covers the common unzip layout where `Dataset/Dataset/` holds the files.

Approved: after a successful re-read the panel advances to `2. Đề bài` automatically; `1. Nguồn` stays clickable to review the report or add files. A failed re-read stays on `1. Nguồn`, disables `Đề bài` and offers `Đọc lại nguồn`; a failed business handoff stays on `1. Nguồn` with the error and keeps `Đề bài` enabled for retry.

Evidence: `taskpane_assistant_browser` 13 cases (includes the wrapper-folder case), `taskpane_assistant_entry` 9 cases (auto-advance), `taskpane_assistant_journey` 6 cases, taskpane module 15 tests OK.
