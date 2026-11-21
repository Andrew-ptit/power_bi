# Remove preparation backup across the complete journey

Approved decision: the user requested removal for the entire flow on 2026-11-16. This supersedes preparation US4 restoration, backup TTL/quota and mandatory before-image requirements. It does not alter Typed/Advanced M history policies.

## Design

Preparation uses transient semantic reads of values, formulas, cell number formats and native sheet identity to validate a reviewed operation. The current-target compressed OOXML export, persisted before/after images, restore journal, recovery custom XML and preparation Undo/Redo are removed from the active application flow. Original source-file validation and native whole-XLSX insertion remain. Personal sheets still receive separate result copies. Completion requires a read-back matching the server's expected semantic result. Failure after write authorization reports partial/unknown and stops replay. It never silently retries a write. No backup is offered after applying cleanup.

Direct write protocol: `direct-begin` consumes exact approval with a transient `beforeImage`; server computes expected result and discards full before/expected images after calculation. `direct-write-ready` consumes a one-use permit bound to `currentFingerprint`. `direct-complete` receives `afterImage` plus the existing receipt shape and validates the expected hash and native identity. Success retains only current claim/ownership metadata. Failure retains operation identifiers and status, never a recoverable snapshot. All routes remain authenticated and schema closed.

Existing in-memory recovery sessions are not converted into new no-backup sessions. The panel starts a fresh preparation attachment against current workbook sheets. Legacy recovery endpoints explicitly reject requests in the active no-backup mode. Historical module compatibility may remain for existing isolated contracts, but the composed application cannot create a journal or evidence snapshots for preparation.

## Functional batches

- [x] NBR01 Backend direct approval/write/read-back protocol, closed schema, active composition, legacy route rejection. Check success, changed target, one-use permits, partial failure and absence of retained images/journal.
- [x] NBR02 Runtime/bridge/session entry uses semantic capture and direct protocol. Remove recovery metadata persistence and UI controls/copy. Show read-back after final file then scan all sheets and open cleaning. Check import-to-cleaning and failure without duplicate writes.
- [x] NBR03 Integrate, update current contracts/status, run focused checks and fast gate. Report existing eight-sheet state separately from native acceptance. User owns final hands-on workbook testing and requested no new sample workbooks.

Stack: existing Python standard library, Office.js and taskpane JavaScript. Preserve current dirty workspace and unrelated staged changes. Retain source-file read-only and explicit Apply review. No recovery capability is promised through Excel Ctrl+Z.
