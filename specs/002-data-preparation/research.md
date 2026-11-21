# Research decisions — 2026-11-14

## R1 — Reuse without changing legacy meaning

`sources/assistant_ingest.py:add_folder` concatenates CSV with exact headers; `add_excel` profiles data, not native sheets. Add a new preparation inventory/import path; reuse bounded byte/hash/path checks and CSV ambiguity behavior. Reject replacing old connector semantics. Existing limits 64 MiB/file and 128 MiB/session remain.

## R2 — XLSX native group insertion and preservation gate

`taskpane.js:applyPQValuesToOpenWorkbook` uses ExcelApi 1.13 and `insertWorksheetsFromBase64`, then deliberately writes values-only. Reuse capability/identity guards, not that values-only copy/format clearing. Native all-sheet insertion is proposed adapter. Microsoft documents `sheetNamesToInsert: []` for all sheets, but does not establish fidelity for cross-sheet/name/table/external-reference collisions; runtime synthetic proof required before shipping.

Sources: [Workbook operations](https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-workbooks), [insertion options](https://learn.microsoft.com/en-us/javascript/api/excel/excel.insertworksheetoptions), [Worksheet API](https://learn.microsoft.com/en-us/javascript/api/excel/excel.worksheet). Research is documentation evidence, not host qualification. Web has additional object limitations and iOS unsupported; feature targets Windows first.

## R3 — Backup is a new subsystem

`exportWorkbookBase64` exports compressed bytes and closes file handles, but no proven in-place restore exists. Choose operation journal with complete before/after affected-scope images, snapshots on marked disk temp and semantic fingerprints. A full workbook export may be a capture input, not permission to overwrite unrelated sheets or use serialization hash as physical identity. Native restore preserving stable sheet references must be proved in T002; generic string replacement is rejected.

`excel/connector.py:apply_export_to_copy` and W-21 PowerShell connector enforce a small allowlist on temporary copies in an owned process. Do not convert them into broad user-workbook attach/patch endpoints. Advanced's no-backup exception stays separate.

## R4 — Transport close versus recovery lifetime

`taskpane.js:closeCoordinatorSession` sends close on pagehide. `SessionManager.close` retires tokens and waits pinned jobs; `_session_invalidated/_clear_session_state` clear process-wide stores. Keep these guarantees. New RecoveryOwner holds committed journal only across transport reopen, with its own original 1.800/28.800-second envelope; new authenticated transport must rebind. Do not simply remove cleanup or keep tokens in browser/XML.

Identity `URL + name` / `name + SHA256(URL)` is insufficient for unsaved or cloned workbooks. Use dedicated non-authorizing marker, semantic fingerprint, fresh claim/rebind, and reject ambiguous ownership. Clone must fork lineage; identity ambiguity cannot silently grant import ownership. Normal user may confirm target identity only after validation, never override fingerprint hard failure. Reopening has no automatic write.

## R5 — Budgets are engineering defaults, not user business rules

Initial journal cap: 10 complete restore points, 256 MiB total physical managed journal bytes per coordinator process, max 64 MiB compressed snapshot; before+after plus in-flight reservation all count. Base64 wire expansion accounted separately within existing request ceilings; chunk transfer if envelope requires it, no raising existing route ceilings. Minimize RAM by streamed bounded files where possible. FIFO complete points, never evict live/pending pins or leave redo dependencies broken. Unallocatable point blocks write.

These defaults can be tightened from synthetic measurements; raising them requires review and evidence. They are separate from parser caps and the existing result caches; report aggregate retained resources, not claim 256 MiB bounds all process memory. Archive compression does not waive uncompressed/cell/package limits.

## R6 — Personal sheets and formulas

Use native `Worksheet.copy` for a separate result, retain native formula-reference behavior and disclose dependencies back to originals; do not reinterpret business meaning. Only original import receipts in the live preparation lineage allow in-place cleanup. After ambiguous reopen, source may remain selectable read-only but imported ownership is not inferred from copied metadata.

## R7 — Planning boundaries

No new domain pack, KPI, permanent business-rule storage/export, cloud sync, auto Save or Typed catalog changes. Do not add unrelated pytest/node framework; unittest and existing Node test runner suffice. Worktree and execution-method choice belong to execution handoff. Planning scripts use explicit feature path/no-persist to avoid changing user's pinned baseline context.

All research decisions resolved for planning; runtime fidelity and identity qualifications remain explicit gates, not assumed facts. No live workbook, credentials or source user files were read.
# Native feasibility findings, 2026-11-14

Real synthetic Excel disproved two assumptions in the original generic route: workbook-defined name collisions can silently rebind imported formulas, and inserting a captured workbook as staging then copying contents back can leave formulas referring to staging sheets, producing `#REF!` after staging deletion. The native personal-sheet copy primitive passed its formula/source oracle. These findings block write enablement; neither an AI explanation nor approval can make the failed native semantics safe.

Candidate revision for review (not implemented/approved as the replacement): preflight all incoming defined/table names and dependencies and reject unsupported conflicts before insertion; use operation-specific, exact before/after value-and-number-format deltas for cleanup recovery, keeping formula cells untouched; handle imported-sheet creation/deletion as a separate ownership operation. This needs fresh proofs for manual edits, dependencies on imported sheets, personal-result redo identity, partial writes, metadata and reopen. A full native workbook/package backup is not yet a verified general restoration mechanism. Retain the existing plan/task IDs and acceptance gates until a replacement is reviewed; no competing implementation plan or relaxed success criteria is introduced.
