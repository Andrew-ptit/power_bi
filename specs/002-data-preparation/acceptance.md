# Acceptance matrix / next unfinished batch

## Current no-backup change - 2026-11-16

Approved scope: remove backup from the complete import/cleaning journey. This supersedes prior US4/S12-S18/DP09 recovery acceptance, while keeping their IDs and old evidence below for traceability. Current batches are NBR01-NBR03 in [backup-removal-plan.md](backup-removal-plan.md).

| Batch / evidence | Status |
| --- | --- |
| NBR01 closed direct routes, exact approval/permit/read-back, source/native-ID staleness, no journal/images, rejected legacy HTTP recovery | Pass: backend 53 cases, 10.108s; delayed ready/completion and explicit fresh-session retirement covered |
| NBR02 native runtime/bridge/taskpane simulated boundary | Pass: 13 JS wrapper cases, including direct no-backup script; no target export/recovery session/XML, native-ID replacement before permit, import-to-scan transition, fresh-session unblock |
| Combined focused checks | Pass: 66 cases, 13.374s; prior to final lost-begin-response change |
| Lost begin reply regression | Red: original bridge exposed raw TypeError and failed; green after fix. Timeout/malformed replies are also classified as uncertainty before native writes; deterministic rejections retain their code |
| Independent code review | Prior lifecycle findings and final lost-begin-response blocker fixed; narrow rereview found no remaining blocker |
| NBR03 exact-current `py tools/run_checks.py fast` | Pass: 1,219 run, 0 failures/errors, 3 skipped, 174.562s, process exit 0; `.artifacts/preparation-no-backup-fast.log` |
| Native Excel complete import -> scan -> Apply -> business | Not run for this change, user-owned acceptance; no new sample workbooks or writes against user data |
| Release metadata | Unchanged; manual acceptance does not establish native qualification |

The previous user import created eight sheets before the old backup verification stopped. A fresh session treats these as existing personal data and can scan them through Use workbook data; it must not reimport automatically or claim prior ownership. UI instructions and direct verification do not promise rollback/Excel Ctrl+Z. The active destination validation covers values/formulas/number formats/native IDs, not a complete style/structure package comparison.

Exact code: HEAD `bf26fda82faec2f980aaf2e15b94040a637c0c95` plus dirty code fingerprint `sha256:3b50c71cf18e729206260095e4ecf6c4c726c8fddc651d55a354173e1edace5e`; per-file hashes in `.artifacts/preparation-no-backup-evidence.json`. The first full run had only the missing three direct routes in the contract route fixture (1 failure, 0 errors, 191.786s); the fixture was corrected and the complete run above passed. Skips: unavailable symlink privilege, optional private source and retained unit parity scaffold. All 13 taskpane wrapper tests ran, including the retained scripts and new no-backup regressions.

Deployment: verified prior coordinator idle, restarted as PID 19968 on HTTPS3079. Health OK; real bootstrap reports `preparationBackups:false`, `preparationV1:true`, native qualification `user_pending`. All five served changed JavaScript assets match repository bytes. Repository/catalog manifests match SHA256 `6b2b9437b5f257d2438e73e9233f52db78f9264864eaeec3427491b097358174`. Verification bootstrap was explicitly closed; no workbook was read or written during the HTTP probe. Close/reopen taskpane to use the new runtime. Next unfinished item: user hands-on acceptance of the actual import/cleaning/business journey, not another sample fixture.

## Superseded implementation evidence

The following checkpoints predate the no-backup decision. They are not the current active protocol or completion claim.

## Gates

T002 checkpoint: `py -m unittest tests.integration.test_preparation_gate tests.contracts.test_preparation_fixtures -v` → 3 pass, 5.047s; native driver `node --check` passes. Synthetic scenario is additive; CLI default unchanged. Isolated server/fixture/unique catalog manifest prepared; original manifest untouched. Actual Office.js driver has not executed: CUA reports accessibility unavailable for the synthetic Excel window and its capture returned a different foreground app. Live preservation/restore remains Blocked (environment), not pass; no worksheet mutations by preparation driver have been observed. Continue independent local primitives.

T003 checkpoint: byte-integrity journal implemented independently of Excel image semantics. `py -m unittest tests.unit.test_preparation_journal tests.contracts.test_preparation_contracts tests.contracts.test_coordinator_dispatch -v` → 27 pass, 9.754s (journal 16, contract 7, existing dispatch 4). Tests cover real managed snapshot files, FIFO, pending/after budget, default 10-point retention, Undo/Redo/new edits, manual fingerprints/CAS, corruption, pre-write cancel, idle/absolute expiry and in-flight write pins. This proves journal transitions, not native Excel undo/restore. Runtime rows remain unqualified; no preparation write endpoint enabled.

T005/T008 core checkpoint: `py -m unittest tests.unit.test_preparation_cleaning tests.unit.test_preparation_inventory tests.unit.test_preparation_journal -v` → 33 pass, 13.176s. Inventory 7 and cleaning 10 are new pure-function evidence; store/UI integration still pending, tasks not complete. Current baseline fast snapshot: 1111 run/0 failures/0 errors/3 skipped, 230.197s; new pure cases were added after that discovery and ran separately. No native preservation/Apply/Undo claim follows.

- Native formula/format/dependency-preserving import and recovery: Blocked by failed actual Excel feasibility (see below); blocks writable implementation enablement.
- Correct session reattach to unsaved/clone workbook: Not run; ambiguous identity blocks automatic ownership/restore.
- Pure scan/wizard can progress with synthetic bindings while those gates remain unresolved.
- Whole feature cannot be complete with any mandatory supported-path gate missing. Existing Advanced verification remains Deferred; no live Codex gate introduced by local feature.

## Current execution evidence

- Approved entry-screen batch: replaced the stacked source form with the user's two-choice entry. New local native picker, closed schema/HTTP route, harmless cancellation and stale-server capability check; existing header facts are collapsed and technical ingestion badges hidden. Existing selected-range cleanup is only revealed after selecting workbook data. Empty sources and directory-only inventory cannot advance; production import/Apply/recovery stay disabled. Folder handling still uses the existing read-only inventory, not CSV-to-sheet conversion.
- RED: three picker tests and the entry JS failed before their implementations; the picker HTTP case failed before route registration. The retained legacy UI case exposed its old badge-presentation assertion, which was updated for the approved compact context while keeping the original case and all state/authority assertions. GREEN: focused Python/HTTP/contracts/all retained JS scripts **33 pass, 4.365s**; full `py tools/run_checks.py fast` **1150 run, 0 failures, 0 errors, 3 skips, 156.648s**. Native empty/header-only/data range guards and first-screen/back navigation are tested. No duplicate DOM IDs. Interactive Excel checks were not run, per user's handoff instruction.
- Updated official coordinator: HTTPS 3077. Bootstrap advertises the picker, both JS assets returned 200 with matching disk hashes, and manifest/catalog SHA parity passed. An older cached coordinator is handled with a Vietnamese update message rather than submitting unsupported/empty source requests. User should reopen the official Reqwise pane; if Office retains the older URL, refresh the shared catalog entry. No new manual samples or demo services were created.

- Latest completed fast run on `b9fc4e9`: `gate=fast run=1144 failed=0 errors=0 skipped=3 elapsed=3215.892s`. This predates the three review fixes; no exact-current full release pass is claimed.
- Real Excel run `prep_read_20261114c`: `preparation_readonly_wizard` passed in 954ms using a 1×2 source and one trim preview; source/formula/style read-back matched. The taskpane was visually inspected at approximately 350px width. This is a read-only product journey, not native Apply evidence.
- In that same disposable run, operation-specific delta feasibility passed: name-conflict preflight 101.8ms, setup 292.2ms (4×4 Orders scope plus dependent Rates), Apply 352.1ms, Undo/Redo 574.9ms, manual conflict 324ms. Before fingerprint `sha256:8ba0e26dbcf5ab30ac7cc0eaa1f67bf38989df69b4be4cf775d371e522532138`; after fingerprint `sha256:784da85491ed158b6168e7a3891f8005796a544f339aa975a91395e028e8c580`. Undo matched before and Redo matched after. Constant text `00123`, literal `=1+1`, date format and dependent formula were preserved. This standalone experiment is not the production journal/session implementation.
- T002 constant-name import alternative has code but no execution evidence: `preparation_scoped_constant_import` and `preparation_import_undo_redo_probe` remain Not run. External links, protected structure, partial writes, merge geometry and complete pane-reopen recovery also remain Not run. The original staging restore remains a failed approach.
- Independent read-only review found three Important issues. Each had a failing reproducer before the fix: valid package-root worksheet relationships, missing source/column/cell locations in exception UI, and pending reservations not counting against the journal point limit. Focused journal/inventory/cleaning suite: 37 passed in 23.829s; mounted wizard check passed. Review fixes are included in the direct integration.
- User handoff overrides the previous default of agent-owned whole-flow manual qualification. Manual results must be recorded as user-reported, tied to the tested revision, and must not silently check T002/T012 complete. No sample-only manual service or separate demo UI is included in the main application.

- T004 HTTP RED: new capability/routes absent; GREEN authenticated attach/snapshot/scan/answer/preview, detach/explicit close, schema rejection and retained route oracle: 7 tests, 2.106s. Existing missing-token policy stays 403; expired token stays 401. Every store operation binds the authenticated transport, never a client-supplied transport ID. Unknown write endpoints return 404.
- T004/T008 GREEN: preparation contracts, cleaning, sessions and all task-pane scripts: 42 tests, 7.951s. Later closed-store and complete snapshot-byte-budget tests failed first, then passed (8 session tests, 0.442s). Number formats and headers count against the 8 MiB local document budget.
- Focused combined checkpoint: `py -m unittest tests.unit.test_preparation_inventory tests.unit.test_preparation_cleaning tests.unit.test_preparation_journal tests.integration.test_preparation_api tests.integration.test_preparation_sessions tests.contracts.test_preparation_contracts tests.taskpane.test_taskpane_js -v`: 68 tests, 44.404s, no failures/errors. Pure model and fake Office/DOM evidence only. Mounted navigation, answer index, literal header text, stale response rejection and disabled writes are exercised; original 12 task-pane scripts remain.
- Integration fast checkpoint: `py tools/run_checks.py fast`: 1141 run/0 failures/0 errors/3 skipped, 366.024s. Later bounded-state/name-inventory additions are covered by focused checks; this earlier run is not exact-current release qualification.
- T002 actual Excel `prep_20261114a`, disposable generated target, isolated HTTPS port 3091. The original committed native driver was `172ce89`; follow-up driver changed only blocked-stage continuation and relative dependency oracle so independent tests could proceed. Group insertion imported two sheets (4×4 Orders used range and 2×2 Rates); collision read-back failed expected 11 / observed 110. Native personal copy passed with formula `=1+1` and unchanged original. Captured-image dependency edit passed; staging-copy-delete restore failed `RESTORE_DEPENDENCY_REFERENCES_NOT_PRESERVED`, visibly `#REF!`. Neither failed fixture was saved. These are feasibility diagnostics, not exact-current product journeys. Event evidence is local under `.artifacts/gate-prep-20261114a/events.jsonl`.
- Earlier CUA access issue was resolved after the user restored the minimized synthetic Excel window. Sideload path on this Office build: Home → Add-ins → Advanced → SHARED FOLDER. The unique gate manifests were added without replacing the production manifest. The blocker is now native semantic preservation, not missing UI access.
- Folder metadata now exposes bounded defined-name scopes and table names for a future collision preflight. Names/formula expressions are not rewritten and no unsupported collision is silently accepted as safe.

## Baseline reconciliation

## Direct main-workspace handoff

The feature-only patch from baseline snapshot `7e8c5b5` was checked and applied to the main working directory without resetting/stashing user work or changing the pre-existing staged renames. This is working-tree integration, not a release/merge commit of the user's unrelated changes. Main-workspace focused check: preparation API/sessions/cleaning/inventory/journal/contracts, existing dispatcher and all task-pane scripts — 74 passed, 30.359s. Complete main-workspace `py tools/run_checks.py fast`: **1146 run, 0 failures, 0 errors, 3 skips, 211.629s**. Tested main HEAD is `bf26fda` plus retained user changes and the feature content of `7b43253`; all 41 feature files matched the worktree after newline normalization. Later edits are evidence documentation only. Runtime/live writing qualification is not established by this fast gate.

The real main coordinator was started from `C:\Users\COLAIG\Downloads\power_bi` on HTTPS port 3079. Both preparation JS assets returned 200 and their served SHA-256 values matched the main files. Bootstrap reports `preparationReadV1=true`, `preparationV1=false`. Repository and `C:\AddinManifests\manifest.xml` match SHA-256 `61b443a8ae076b4bb46ba3997614c8c16c95e94628a1d72ab24302bf7a48e56e`; only runtime port/channel metadata was synchronized, no version bump.

To inspect the integrated UI: close the old pane, open **Reqwise-excel-mcp** (not an **Excel Gate** ribbon entry), read the workbook, then expand **02 · Nguồn dữ liệu → Chuẩn bị dữ liệu · quét và xem trước**. Folder listing and selected-range scan/answer/preview are available. Import, Apply and native recovery are still unavailable; the integrated code must not be described as a complete writable end-to-end preparation flow. Full manual testing belongs to the user by explicit instruction; report revision, action, expected/actual result and error code for each finding.

Feature 001 remains intact: US2 verification and US8 questions may provide reusable checks. Reuse only when code/deps/fixture/environment unchanged and criterion actually covered; imported writes/undo/personal copies are new capability. No task here checks off baseline 001 or changes its explicit no-backup scope.


## Resumed implementation - 2026-11-15

This batch implements guarded production modules rather than a separate manual demonstration: file selection/progress, all-sheet reading, atomic source-set, bounded import packages, exact mutation handshakes, operation-specific recovery, and a workbook-only Assistant session. Native write capability remains default false and owner-enforced. Simulated tests opt in explicitly; no production environment switch is introduced.

Independent review reproduced and corrected numeric encoding differences, formula cached-result comparisons, non-A1 source origins and native-ID checks on recovery. The initial full fast gate ran 1163 cases: 1159 passed, 3 skipped, 1 failed (the static HTTP route oracle lacked twelve deliberate new preparation paths), 199.457s. The oracle retained every existing route and added exactly those twelve; focused dispatcher/API checks then passed8/2.444s. This initial run is not a clean final regression.

Root focused checks before final handoff corrections: preparation/backend/contracts68 passed/19.682s; Assistant API/workbook session/all retained taskpane runners34 passed/18.615s. Backend's final lifecycle/source-set run69 passed/21.668s. A consolidated review fix remains in progress for explicit date fallback, async Problem transition, exact reviewed-source identity/content, and preservation of whole-range scope when Tables exist. Final integration evidence must follow those edits.

Native qualification remains Not run for the new guarded adapter. Required remaining work includes full font/fill/border/geometry/dependency evidence, supported XLSX collision/name preservation, native session reopen/recovery, and the complete import/Apply/Undo/Redo success/recovery journey. Existing failed generic strategies stay blocked. User-owned whole-flow manual testing does not convert simulations into native evidence, and no release metadata is bumped.


### Final guarded integration evidence

All four handoff findings were corrected and independently marked addressed. A subsequent stale-answer restoration regression was reproduced, corrected and independently checked: failure reopens the controller without replacing its current answers/revision/preview. Taskpane wrapper13 passed after that fix. The native write gate remains default false.

Feature files were copied to the main working directory after checking every prior main file against f79fb76 and rejecting conflicts. All36 integrated files matched byte-for-byte; the user's two staged renames were unchanged. Final main command `py tools/run_checks.py fast`: **1163 run, 0 failures, 0 errors, 3 skips, 148.593s; process exit0**. Log `.artifacts/preparation-main-final-fast.log`. This is automated/HTTP/Office simulation evidence only. No native workbook was opened; full style preservation, imported native write/recovery and reopen qualification remain incomplete. The user should not be told that the complete writable preparation journey is ready.

Official main coordinator now serves HTTPS3079. Five JS assets matched main files byte-for-byte; bootstrap native write capability remained false. Repository/catalog manifest SHA256 match: e1774c41a5fcb61fd8d919b0df334233dd9e4b496a467716f73110b4b0149c00. Runtime metadata only; no version bump.


## Connected manual-acceptance handoff - 2026-11-15

Latest user instruction: finish the complete code flow; hands-on Excel testing belongs to the user. No further Excel UI/COM qualification was run after that instruction. Application availability is manual mode with preparationNativeQualification=user_pending; no release/live pass is asserted and no version metadata is bumped.

Implemented and integrated: folder browser/per-file selection/Select all; current-workbook collision mapping; literal CSV and normalized complete XLSX groups; real per-file insertion and per-sheet scan progress; exact cleanup questions/review/Apply for owned sheets and personal result copies; mixed target cleanup; complete package evidence; guarded before/write/read-back journal; Undo/Redo; native-ID and full-preservation conflict checks; bounded FIFO/TTL/shared physical budget; eager metadata/pane detach/reopen; explicit new-session reset; exact reviewed business-source handoff. Native namespace source proof from the earlier isolated run retained result11 and original source bytes; this is not target-Office live acceptance.

Independent native evidence is resolved only through authenticated opaque IDs, matched to semantic image content and native IDs, then privately retained in journal snapshots. Source helper writes/SaveCopyAs only owned temporary copies. Precise session metadata exclusion and robust customXML decoding preserve unrelated XML. Known protected/external/macro/pivot/chart/cross-1904 source imports, special/retargeting personal copies and ambiguous/oversized data remain technical prewrite blockers.

Automated evidence: focused preparation/API/contracts/retained taskpane suite102passed38.323s. Worktree fast1201run/0failed/0errors/3skips232.148s, followed by focused formula/date/XML/lifecycle guard checks. Exact-current integrated MAIN fast **1201run,0failures,0errors,3skips,250.107s; processExit0**, log .artifacts/preparation-complete-main-fast.log. All feature files were copied before that test log was created; each matched the worktree bytes and pre-existing main staged renames remained untouched. Required registry1222 retains every prior case;21 runtime cases are separately classified, not claimed run.

User test steps and limits: quickstart.md. Full target import/Apply/recovery/reopen native acceptance remains user_pending/Not run by implementer.

Official manual-acceptance coordinator: HTTPS3079. Six runtime/controller/session/bridge/entry/taskpane JS assets returned200 and matched main bytes. Bootstrap preparationV1=true; preparationNativeQualification=user_pending. Repository/catalog manifest SHA256 both712f23ddf16028f5db6b905dda006f024df4580f9fecec66ef3d1e068aef1043. Main staged user renames unchanged. Implementation commitd7a59bf; no native pass or release bump.
