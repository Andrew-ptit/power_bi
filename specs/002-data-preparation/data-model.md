# Data model and ownership

All new document types have closed keys, `schemaVersion: 1`, canonical hashes from core conventions, bounded strings/arrays and explicit error mapping. Existing schema/hash inputs unchanged.

| Entity | Fields / binding | Owner |
| --- | --- | --- |
| WorkbookBinding | recoveryId, lineageId, host identity evidence, semanticFingerprint, claimVersion; marker is hint, not credential | recovery owner + verified runtime claim |
| PreparationSession | preparationId, issuedAt, idleExpiresAt, absoluteExpiresAt, attached transport session, binding, activeJobs | coordinator; TTL 1.800/28.800 seconds |
| SourceInventory | inventoryHash, immutable file IDs/hashes/size/stamps, source sheet IDs/names, mapping, parser findings | inventory/store; paths private server only |
| ImportedSheetOwnership | preparationId, importAttemptId, actual sheet IDs, workbook binding, committed fingerprint | preparation store; never client flag/name alone |
| ScanFinding | findingId, source/column, kind, measured count, bounded example, severity, required question IDs | pure cleaning engine |
| Question/AnswerRevision | stable question ID, group, dependency IDs, source scope, answer revision/hash, explicit format/locale choice | store; CAS expectedAnswerRevision |
| CleanupPreview | proposalId, revision, source/answer/mapping hashes, target strategy, exact value/type/format changes, reviewHash | store; immutable revision |
| MutationAttempt | attemptId, kind, exact reviewHash, single-use grant, expected fingerprints, reserved bytes, receipt, status | store + Excel slot |
| RestorePoint | pointId, lineageId, operation order, affected scope, before/after snapshot IDs+hashes, semantic fingerprints, retained bytes | journal, no path in public projection |
| Evidence | command, git revision, layer, status, duration, errors, dimension/count changes, source fingerprints | feature acceptance artifacts; no raw cells |

Auxiliary contract types also live in model.py: `WorkbookClaim` (marker hint, target confirmation, source semantic evidence, expectedClaimVersion); `SourceSnapshot` (sourceId, shape, typed literal cells, immutable formula and semantic format maps, fingerprint); `ScanResult` (sourceRevision, findings, question dependencies); `SheetMapping` (fileId/sourceSheetId/proposedName); `ImportPreview` (inventoryHash/mappingHash/target/reviewHash); `MutationGrant` (single-use ID, action/source/answer/target binding, expiry); `Reservation` (attempt-owned byte budget/image IDs); `OperationScope` (kind/sheet IDs/affected ranges/created structures); `RuntimeReceipt` (phase/actual affected IDs/shape and verified semantic evidence/partial markers); `PreparationState` and `JournalState` (bounded public projections with revision/cursor/expiry, no snapshots/paths/tokens).

## State machines

Workflow: `unbound → bound → inventory/scanned → questions_pending → preview_ready → approved → prepared → writing → verified`.

Any source/answer/mapping/binding revision change invalidates dependent preview/approval. Exceptions: `blocked` (pre-write) or `partial_unknown` (write may have begun). Unknown requires explicit reconcile; no automatic replay.

Journal: `reserved → before_verified → write_started → after_verified → committed`. Failure before write releases reservation safely; after write retains unknown receipt/images until reconciliation/expiry. Undo and redo are new attempts, not reuse of initial grant; cursor updates only after verification. New committed edit after Undo removes unreachable redo. Eviction only complete dependency-safe points; no point can reference an evicted image.

Preparation detach retires its transport token and all executable authority as today. Committed recovery metadata/images remain until original logical preparation TTL; pinned valid jobs finish per current semantics. Explicit session close clears its attached recovery too. Reopen creates fresh transport and claims verified binding; no expired preparation can be revived. Cleanup waits pin release and never deletes workbook data. Coordinator restart/crash durability excluded.

## Integrity and data minimization

Use semantic source/formula/format/shape fingerprints for affected scope; workbook export serialization hash alone is not identity. Preserve original package and worksheet evidence separately. Markers/identities may be copied, so rebind requires source evidence and safe ownership decision; ambiguous clone forks/no automatic in-place write. Snapshot files stay marked owner temp with bounded archive validation. No private paths, raw cells or recovery secrets in events/logs/Custom XML; public point IDs are not bearer permissions.
