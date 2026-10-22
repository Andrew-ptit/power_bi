# Verification and historical evidence

Current release results are in [1.2.0 release report](../releases/1.2.0.md). Historical success is scoped to its measured revision and does not close current sideload/runtime gates.

- [Refactor review](REFACTOR_REVIEW.md): function responsibilities, side effects, invariants, differential checks and performance limits.
- [Function inventory](function-review-inventory.json): 372 baseline functions, destination/caller/test-reference candidates; static matches are navigation aids.
- [Complete test migration](../../tests/case_migration.json): 354 retained baseline cases, 19 promoted oracle cases, 12 additional checks; no blanket deletion of safety coverage.
- [Phase 1 independent report](PHASE1_CROSSCHECK.md): historical automated/UAT evidence and its limits.
- [Storage spike closure](history-storage/WAVE0_SUMMARY.md), [actual Office.js evidence](history-storage/MANUAL_EVIDENCE.md), [independent storage cross-check](history-storage/PHASE1_CROSSCHECK.md): historical storage-primitive acceptance.
- `history-storage/` retains earlier failure/remediation/security reports with their original command paths. Those paths are historical; promoted runnable helpers live under tests/support.
- `design/` preserves approved UI requirements, wireframes and handoff provenance. These files are design evidence, not app entrypoints.

Recovery: `baseline/pre-1.2.0-byte-exact` (4bdc2de) preserves synthetic fixture bytes; `baseline/pre-1.2.0` (d9b6038) is the original code snapshot. The first checkout test run exposed Git line-ending conversion and missing private CSV dependency; it is not passing release evidence.
