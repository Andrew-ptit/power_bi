# Current implementation status

Updated: 2026-11-20 (Asia/Saigon). This page is a current status summary; historical reports are available through Git.

## Source-import tab (feature 003) - automated pass, live Excel Not run

Approved 2026-11-20: the assistant source journey is two steps, `1. Nguồn → 2. Đề bài`. `1. Nguồn` browses an authenticated local folder (breadcrumb, up control, multi-folder selection), reads selected CSV/XLSX only on `Nhập vào workbook`, writes each CSV as a typed sheet (number/date/text with `General`/`yyyy-mm-dd`/`@`), leaves empty CSV cells blank with `General`, probes the workbook date system once (1900/1904) and blocks the import when the probe fails, then reports `Đã nhập N file → M sheet`, the automatic exceptions by column and skipped files with reasons. `2. Đề bài` is enabled only after a verified re-read of the workbook; the business handoff uses that scan, not a cleaning Apply. Cleaning previews, per-column format questions, the workbook date-system selector and the cleaning wizard are removed from the assistant tab; `sources/preparation/cleaning.py`, the journal/evidence modules and the native `applyCleanup` adapter remain unmounted compatibility code.

Automated evidence: `py tools/run_checks.py fast` passed 1,288 cases (0 failure/error, 3 skips, 215.501 s, exit 0). `py -m unittest discover -s tests` ran 1,304 cases with 1 failure and 7 skips; `py tools/run_checks.py runtime` ran 13 with 2 failures - all three failures are the pre-existing `tests.runtime.test_typed_local_parity` `PARITY_FIXTURE_TIMEOUT` (no usable Excel COM fixture), not feature 003. Task-pane: 15 tests green, including the new source-browser and two-step journey scripts. Exact per-ID matrix: [feature 003 acceptance](../../specs/003-source-import-redesign/acceptance.md).

Live Excel end-to-end import/read-back is **Not run**: no Excel Desktop or live harness was used in this environment. Native qualification remains `user_pending`. No application, npm, HTTP or Office manifest version changed (application/npm/HTTP 1.2.0, manifest 1.2.0.0).

## Preparation phase 1 - no-backup flow, manual acceptance pending

Approved change 2026-11-16: backup is removed from the complete preparation journey (import and cleaning). Active composition advertises `preparationBackups: false`, allocates neither recovery journal nor package-evidence store, and rejects legacy backup/restore HTTP actions. It does not export the target workbook package, upload before/after recovery images, persist preparation recovery XML or show preparation Undo/Redo. Typed, Problem Chain, PBIP and Advanced boundaries remain unchanged.

The direct protocol binds exact approval to a transient semantic before-read and native sheet IDs, consumes one write permit, then validates the observed result. Full before/expected/after images are not retained as restoration history. Original CSV/XLSX source checks and native whole-XLSX insertion remain. Verified session imports can be cleaned in place; existing personal sheets receive separate result copies. Personal copies with Tables, scoped names or formulas requiring unsupported native retargeting are blocked before writing. Semantic bounds remain 400,000 cells and 8 MiB per capture; removing backup does not remove scan limits or constitute a full style/structure comparison of the destination.

After verified import the panel immediately opens Cleaning while it scans workbook sheets with progress. Applying cleaning still requires answers and exact preview approval. Uncertain native writes block replay. Lost begin/permit/completion responses expose explicit New session: a fresh native read retires the old attempt and its authority, and delayed old requests cannot affect the fresh claim. It does not inherit imported-sheet ownership, approvals or answers. No automatic rollback or Excel Ctrl+Z guarantee is offered.

Focused automated evidence: `py -m unittest tests.taskpane.test_taskpane_js tests.integration.test_preparation_direct tests.integration.test_preparation_sessions tests.integration.test_preparation_mutation tests.integration.test_preparation_api tests.contracts.test_preparation_contracts -q` passed 66 cases in 13.374s before the final lost-begin-response regression. That regression was observed failing with a raw TypeError before the fix and passing afterward. Exact-current full gate is recorded in `specs/002-data-preparation/acceptance.md`; log `.artifacts/preparation-no-backup-fast.log`.

Exact-current full gate passed: `py tools/run_checks.py fast`, 1,219 run, 0 failures/errors, 3 skips, 174.562s, exit 0. The preceding route-fixture mismatch was corrected before this complete rerun. Evidence uses HEAD `bf26fda` plus dirty code fingerprint `sha256:3b50c71cf18e729206260095e4ecf6c4c726c8fddc651d55a354173e1edace5e`. Deployed coordinator PID 19968 returns backups false, writes true and user-pending native qualification; all five changed served JS files equal source. Repository/catalog manifests match SHA256 `6b2b9437b5f257d2438e73e9233f52db78f9264864eaeec3427491b097358174`. Close/reopen the pane after the restart.

The user's earlier attempt created eight CSV sheets before old backup verification stopped. These sheets are existing workbook data after a fresh no-backup session; choose Use workbook data to scan them without importing duplicates. No new sample workbook or import/cleanup against that user workbook was performed for this change. The user owns final hands-on acceptance and requested no additional native test fixtures. Native full-journey acceptance remains Not run, `preparationNativeQualification: user_pending`; no release version is changed.

## Assistant v2

The main assistant now connects source ingestion, measured understanding, Codex-authored A/B Typed plans, local Decimal execution, independent reconciliation, exact-revision freeze/approval, one-shot values-only handoff/read-back and Decision Record metadata persistence. Its eight-card UI replaces formula advice. Six Typed join kinds remain supported. No application, npm, HTTP or manifest version was changed for this work.

| Evidence | Result and limit |
|---|---|
| Wave E exact common retry | `gate=fast run=1041 failed=0 errors=0 skipped=3 elapsed=153.056s`. The first run had two transport errors under slowdown; both exact cases passed a focused rerun before the complete retry. |
| Wave F common gate | `gate=fast run=1060 failed=0 errors=0 skipped=3 elapsed=178.196s`. |
| Wave G exact-current common gate | `gate=fast run=1057 failed=0 errors=0 skipped=3 elapsed=268.885s`. All 12 retained task-pane JS scripts ran. Required registry equals discovery: 1077 IDs (+230, -3 mapped legacy IDs), no missing, unregistered or duplicate IDs; fast 1057, runtime 17, Codex 3. The preceding in-progress final run was stopped for the reviewed UI copy/freshness-warning correction, not counted as a completed result. |
| Exact-current real Codex | `PQPC_LIVE_CODEX=1 py tools/run_checks.py codex`: `gate=codex run=3 failed=0 errors=0 skipped=0 elapsed=50.317s`. Synthetic Assistant v2 planning passed in 28.458 s, two validated actual plans; independent expected A=12/B=15, each 1×1. Problem Chain left merge (5 steps) and structured planning (3 steps) also passed. |
| Exact-current isolated backend smoke | Windows PowerShell 5.1, `tools/assistant_flow_smoke.ps1 -StopAfter record`, owned injected plan-only synthetic coordinator: FIN 127 assertions/5.227 s, Sales 75/4.451 s, repeated FIN 127/4.222 s; all passed. Ten snapshot/understanding/planning/plan/preview/Spec/Record/node hashes matched across FIN repeats. Empty root exited 1; each planner sample had 20 rows. Synthetic input package stayed byte-identical. Receipt is simulated; no Excel was opened or written. |
| Typed-local versus M runtime parity | Blocked: `py -m unittest tests.runtime.test_typed_local_parity -v` failed after 60.319 s with `PARITY_FIXTURE_TIMEOUT` at `Workbooks.Add(-4167)`. Owned Excel processes were cleaned; no workbook, output dimensions or fingerprints were obtained. Six-join live parity was not run. |
| Assistant v2 Office.js end-to-end | Not run: no usable Excel workbook/runtime fixture could be created. Unit, HTTP, fake Office.js and synthetic-receipt smoke do not establish a live write journey. Product metadata remains `parityChecked: none`. |

The fast skips are unavailable symlink privilege, an absent optional private CSV and the retained unit parity scaffold. The implemented runtime parity test is separately blocked, not silently skipped. Full smoke uses 13 POSTs for 11 logical routes (including compute re-ingest and the `/apply` receipt); its receipt is synthetic and its source package stays unchanged.

Custom XML contains only metadata. Its node hash is separate from the full Decision Record hash; reopening that node cannot verify the full record or current sources. Decimal values are written as Text to preserve precision, and the add-in never calls Save. Retained consumed-write outcomes identify the workbook bound to the Spec, including after a workbook switch; refreshing cannot mask the warning with a progress message. General input, privacy and lifecycle limits are described in [the UI contract](TASKPANE_UI.md) and [the add-in runbook](../../tools/excel_addin/README.md).

Assistant evidence above was collected on `efe9afef4d57d3ac81a0c264620a23bb3b8cc303` plus the current uncommitted workspace, using synthetic fixtures only. Automated and live Codex qualification passed; release qualification remains incomplete because live Office.js writing/persistence/reopen and runtime M parity are not verified. No user workbook was used as a fixture, and no version or dependency was changed for this work.

## Code and architecture

Canonical modules are grouped by source processing, Power BI, Excel, Typed Power Query, history and diagnostics. HTTP endpoint adapters, a closed operation registry, injected runner protocols, shared subprocess transport and compatibility facades are implemented. See [architecture](ARCHITECTURE.md) for ownership and remaining boundaries.

Source fingerprints now resolve referenced styles by content so importing a result sheet does not invalidate unchanged source data. Changes to referenced source cell/row/column formatting still invalidate the fingerprint. Canonical persisted history/schema/hash fields are unchanged.

This is a maintainable modular foundation, not a claim that every function or end-to-end path is fully optimized. The Codex draft and continuation planners were extracted from the two stores into `adapters/codex/typed.py` (208 lines) and `adapters/codex/problem_chain.py` (209 lines); the stores shrank from 1273 to 1099 lines and from 878 to 703 lines while re-exporting the moved names. The step-diagnostic use cases then moved into `powerquery/typed/diagnostics_service.py` (163 lines), which sequences them against store authority; the store keeps the lock, the single staging slot, the cache and every promotion guard, so it only fell from 1099 to 1055 lines and the combined total grew by about 120 lines. That trade is deliberate: the sequencing is readable in one place while the atomic guards did not move. Large Typed/history stores and task-pane orchestration still remain candidates for smaller internal services. Compiler lookup uses maps; runtime Excel/Codex latency has no demonstrated overall improvement.

## Verification

| Check | Current result |
|---|---|
| `py tools/run_checks.py fast` on `efe9afe` plus the fixture move, import smoke, Codex adapter split and diagnostic extraction | 386 run, 384 pass, 0 failure/error, 2 skip; 50.504 s |
| Step-diagnostic guard characterization (`tests/integration/test_typed_step_diagnostic_guards.py`) | 7 cases written against the pre-extraction code, still passing after it; 17 guard codes/messages before and after with none lost |
| `py tools/run_checks.py runtime`, isolated Excel COM | 16 run, 16 pass, 0 skip; 427.694 s |
| Import smoke over `pbip_assistant`, `tests/support` and `examples` (`tests/unit/test_import_smoke.py`) | 93 modules, 0 failures; 0.250 s. Verified to fail and name the offending module when a stale import is reintroduced |
| Focused checks on the seven modules whose fixture imports moved | 50 pass, 0 failure/skip; 5.278 s |
| Fingerprint/cache/Typed/diagnostics/history focused checks | 64 pass, 0 failure/skip; 4.446 s |
| Real Office.js root and child commit/Preview/Confirm before the fingerprint fix | Completed on a synthetic workbook; root 4 rows x 10 columns, child 2 rows x 10 columns; source preserved |
| Real cache-hit/recovery journey after the fingerprint fix | Blocked, no evidence: the isolated gate add-in loads and the gate server receives its asset request, but that Excel instance exposes no ribbon control to UI Automation, so the task-pane driver never starts |
| Advanced M | Deferred at the user's request; its current implementation remains present |
| Exact-current Assistant regression/live Codex/release qualification | Fast and live Codex passed as recorded above; live Office.js and runtime M parity remain unverified, so release qualification is incomplete. |

The earlier foundation run had two skips: unavailable symlink privilege and an absent optional private CSV. The current Assistant fast run also retains the separate unit parity scaffold, for three skips. Simulation/unit checks are not a completed live UI journey.

## Version and scope

Application/npm metadata remains 0.1.0 and Office manifest 1.1.0.0. The target application release is 1.2.0 with manifest 1.2.0.0; it has not been issued. Version changes wait for the required exact-current gates. API/schema/spec versions are independent.

Annotation editing, semantic/runtime diff and persisted runtime summaries are outside the product scope. Reserved persisted metadata fields accept only null, preserving workbook history compatibility. MCP/pilot backlog and unsupported PBIP patching are not completed capabilities.
