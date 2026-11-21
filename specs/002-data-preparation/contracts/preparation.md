# Preparation interfaces - contract v1 (partial implementation, native writes unqualified)

## Active no-backup contract - 2026-11-16

This section supersedes the recovery/journal/backup protocol below for the composed application. `preparationBackups: false`; store has no journal or target evidence store. Legacy preservation/image/restore routes reject authenticated calls. The remaining old descriptions cover isolated compatibility modules only.

`direct-begin` accepts exact grant and transient `beforeImage`, validates semantic fingerprint plus native IDs, computes expected semantics and returns attempt/one-use permit, `beforeSheetIds`, exact packages/deltas and personal copy mappings. Before requesting write authority, Office.js rechecks semantic data and sheet IDs; it rechecks again after the HTTP roundtrip. `direct-write-ready` consumes the permit once. `direct-complete` accepts transient `afterImage` and a receipt with null imageId, independently computes expected hash equality and verifies unchanged pre-existing native IDs plus exact new IDs. Full images are discarded; completion retains current ownership and binding metadata only. Approved cleanup cannot replace formula cells. Source files remain read-only.

Partial/unknown cannot automatically retry. An explicit marker:null, targetConfirmed:true, native-identity-bound fresh attachment atomically retires an unresolved attempt, including at the session cap, revokes its old binding and rejects delayed ready/completion messages. No imported ownership or review transfers. Same-marker/background attachment cannot retire writing. Lost begin response is exposed as uncertainty before native writing; a new explicit review is required. Active preparation has no recovery XML persistence or Undo/Redo, and no full target-package style/structure comparison. Original-source XLSX safety/preservation checks and native whole-group insertion remain.

## Authority and compatibility

Feature routes under `/api/preparation/`, additive capability `preparationV1`. Existing host/origin→authenticated transport session→fail-fast Excel slot→owner state lock order retained. Required workbook/lineage/answer/source/review hashes in every dependent action. Unknown keys, stale CAS or unsupported host fail closed. No legacy assistant/typed/advanced route gets broader write permission.

Separate executable authority from retained recovery state. A point ID/marker/path does not authorize writes. Close retires old transport authority; attach requires new authentication and verified binding. Original recovery TTL fixed at issue; idle refreshed only by authenticated feature activity. Background polling/reattach cannot extend absolute time. No writes from navigation/read-only state.

Add `detach` for preparation pane teardown: preserve already-committed recovery under original TTL, retire the transport through existing close logic and clear all legacy stores/approvals. Explicit `/api/session/close` remains full close and also closes the attached recovery lineage (after pinned jobs); legacy panes still use current close behavior. Never export/snapshot during pagehide. Teardown loss is tolerated by bounded idle cleanup, not an infinite lease.

For an unsaved or otherwise ambiguous workbook, attach returns `needs_target_confirmation`. User explicitly chooses the current target and sees prior snapshot time/scope, then a fresh claim rotates the marker and revokes the prior active attachment, only after semantic evidence matches. This is new target authorization, not proof a copied marker was unique. Conflicting active claims or changed source are not overridable; clone uses a fork without inherited imported-write ownership. Do not silently grant a cloned/ambiguous workbook the original mutable cursor.

## Bounds

Journal: 10 retained complete points, 256 MiB process-wide physical bytes (images + indexes + pending reservations), max 64 MiB compressed image, at most one mutation per workbook lineage. Full package validation counts expanded sizes/cells; parser safety limits not relaxed. Folder sources use existing 64 MiB/file, 128 MiB/ingest-session bounds. Snapshot subset or chunking must respect current HTTP envelopes; no >64 MiB base64 upload into an 8 MiB JSON endpoint.

Public state bounded metadata; UI examples max 20 affected rows across selected sources, display text max 256 characters; examples stay local. Full checks use full affected data, not preview. Detection count identifies whether full scan or sample and sample counts, never extrapolates silently. Default trim removes ASCII space at cell edges; nonbreaking/invisible characters are separately flagged for explicit rule. Date choices explicit DMY/MDY/YMD + format set, no locale guess; numeric decimal/group separators explicit. ID columns are text unless explicitly converted after warning; formulas immutable for cleanup.

## Domain Python interfaces

Implementation checkpoint 2026-11-15: attach/detach/state/inventory/source-snapshot/source-set/scan/answer/preview/review-import/pick-folder/packages are implemented local reads/reviews. Planned mutation handlers are implemented behind a default-false owner gate: approve/begin/write-ready/undo/redo reject production calls until native preservation/recovery qualification exists. Upload/complete do not independently grant writes. All store actions bind the authenticated transport. Source snapshots use actual zero-based row/column origins, a native formula mask, number formats and verified or explicitly chosen 1900/1904 date system. Atomic source-set uses expectedSourceRevision, replaces departed sources and retains unaffected answers. Metadata markers alone do not grant native identity/write authority.

The implemented operation image is bounded JSON, not a lossless workbook backup. It retains native IDs, names, offsets, values, full Range.formulas, formula masks and number formats. Its comparison projection excludes native IDs (validated separately), ignores formula cached results and encodes numeric values as tagged IEEE-754 bytes identically across Python/JavaScript. Full font/fill/border/geometry/dependency preservation and conflict qualification remain missing; no production write capability follows from this image. Maximum JSON semantic image is 8 MiB inside existing broader journal caps. Unsupported package structures fail before mutation. No generic staging-copy-delete restoration is permitted.

New modules under `pbip_assistant/sources/preparation/`, use typed dict/dataclass models defined in model.py and stdlib only:

```python
inventory_folder(root: Path, relative_path: str) -> SourceInventory
scan_sources(binding: WorkbookBinding, sources: list[SourceSnapshot]) -> ScanResult
build_cleanup_preview(scan: ScanResult, answers: AnswerRevision) -> CleanupPreview

class PreparationStore:
    def attach(self, transport_session_id: str, claim: WorkbookClaim) -> PreparationState: ...
    def answer_question(self, preparation_id: str, question_id: str,
                        answer: dict, expected_answer_revision: int) -> PreparationState: ...
    def review_import(self, preparation_id: str, inventory_hash: str,
                      mappings: list[SheetMapping]) -> ImportPreview: ...
    def approve_preview(self, preparation_id: str, review_hash: str) -> MutationGrant: ...
    def begin_mutation(self, preparation_id: str, grant_id: str,
                       expected_fingerprint: str) -> MutationAttempt: ...
    def complete_attempt(self, attempt_id: str, receipt: RuntimeReceipt) -> PreparationState: ...

class RestoreJournal:
    def reserve_restore_point(self, lineage_id: str, operation: OperationScope,
                              required_bytes: int) -> Reservation: ...
    def checkout_restore(self, lineage_id: str, point_id: str, direction: str,
                         expected_cursor: int, expected_fingerprint: str) -> RestoreAttempt: ...
    def finish_restore(self, attempt_id: str, receipt: RuntimeReceipt) -> JournalState: ...
    def expire(self, now: float) -> None: ...
```

All named model types belong to model.py, not new generic framework; `Path` imported from pathlib. Store owns locking/CAS; pure functions no state/filesystem writes except bounded inventory reads. Journal consumes coordinator-owned temp manager and injected clock. `RuntimeReceipt` includes observed full-scope values/formulas/formats/shape fingerprints and phase, not client's unchecked `passed=true`.

Journal byte-integrity primitives now distinguish `checkout_restore` (prepared, no write pin) from `mark_restore_started` (after source/image recheck, pins active recovery until completion). An expired unstarted restore cannot pin or read backup indefinitely. `abort_attempt` releases only pre-write reservations/images; after a write may have started it freezes the attempt as partial_unknown. These internal APIs do not authorize Office writes; the owning service must validate image semantics and host capability separately. Native worksheet IDs allow bounded non-control strings including braces; grant/upload/lineage IDs retain the opaque ASCII identifier rule.

## HTTP actions

Each action is POST JSON, existing error envelope. `state` and `attach` authenticated too. Snapshot/upload transfer bound to attempt+session, bounded chunks if needed; no arbitrary server filesystem path parameter for restore.

| Action | Input payload (plus transport auth) | Output |
| --- | --- | --- |
| `attach` | non-authorizing claim, workbook metadata/fingerprints | fresh preparation/binding state or needs-rebind/fork |
| `detach` | preparation/binding identity, no write data | transport retired; committed journal retained within original TTL |
| `inventory` | chosen root/relative folder | source IDs, mapping proposal, blocked files |
| `scan` | verified binding, selected source IDs/fingerprints | findings, questions, source revision |
| `answer` | preparationId/questionId/answer/expectedAnswerRevision | new revision and invalidated dependents |
| `preview` | source/answer/mapping revisions | immutable import or cleanup preview/reviewHash |
| `approve` | reviewed hash, exact targets and action kind | single-use grant, no immediate write |
| `begin` | grant and current fingerprints, backup evidence | one attempt; write only after before-image verified |
| `write-ready` | attemptId, beforeImageId, current source fingerprint | single-use write permit only after verified before-image; begin alone cannot write |
| `complete` | attemptId + runtime evidence | verified state/unknown receipt, journal cursor |
| `undo`, `redo` | point, cursor, fresh source/binding evidence | restore attempt, not unconditional success |
| `restore-complete` | attempt + read-back | committed cursor or partial_unknown |
| `state` | preparation/binding identity | bounded points, answer index, expiry and warnings |

Snapshot transfer endpoints `image-begin`, `image-chunk`, `image-finish` are attempt/session/lineage scoped. `image-begin` declares purpose (`before`/`after`/`restore-readback`), compressed bytes and SHA-256; it reserves all declared bytes before accepting chunks. Chunks are at most 1 MiB decoded, sequential numbered with exact offset and chunk hash, idempotent only for identical bytes at the same index; fail closed on overlap/conflicting duplicate. `image-finish` verifies declared length/hash and expanded-package bounds and returns opaque imageId. All pending bytes count; expire/fail releases only owned unreferenced files. No path-taking endpoint. Do not begin workbook mutation until the before image is fully verified; after-image exhaustion/failure after write is partial_unknown.

Handshake clarification: approve→begin (consume grant, create non-writing attempt/reservation)→upload and verify before-image→write-ready (recheck fingerprint, consume fresh write permit)→Office mutation→after-image/read-back→complete. The first begin is not authority to mutate; this removes a circular dependency between attempt-scoped uploads and mandatory backup-before-write. No write-ready route is enabled until runtime preservation/recovery gate passes.

Exact closed JSON schemas are T001 deliverable before handler implementation. Model and schema names above are planned signatures, not current callable APIs. The handler must reject approval source replacement and stale upload/image IDs. Grants consumed once and never retained for reopen.

## Excel adapter / controller separation

`preparation_runtime.js` exports `captureAffectedScope(binding, scope)`, `importReviewedSources(attempt, packages)`, `copyPersonalResult(attempt, sourceIds)`, `applyCleanup(attempt, diff)`, `restoreAffectedScope(attempt, image)`, `verifyAffectedScope(binding, expected)`. Each resolves bounded evidence/receipts; no arbitrary formula apply. Capture/export alone is insufficient proof of restore.

`preparation_controller.js` exports `createPreparationController(deps)` for rendered question groups/answers/review and toolbar. It delegates all IO to injected runtime/API; owns no write approval. Mount on assistant tab; ordinary Back/Next never invoke undo. Responsive answer index below/expandable at 360px. User text uses textContent, not HTML.

## Failures and source strategy

Planned stable error codes: `DP_UNSUPPORTED_PRESERVATION`, `DP_SOURCE_STALE`, `DP_REVIEW_STALE`, `DP_AMBIGUOUS_FORMAT`, `DP_BACKUP_LIMIT`, `DP_BACKUP_FAILED`, `DP_BINDING_REQUIRED`, `DP_RESTORE_CONFLICT`, `DP_PARTIAL_UNKNOWN`, `DP_POINT_EXPIRED`. Reuse existing session/security errors instead of replacing them. Unsupported/schema/dependency errors are hard blockers, not acknowledgable advice.

Imported in-place ownership only from verified successful native import receipt in the live preparation lineage. Personal sources always native-copy to unique result. Dependency formulas in result follow native copy semantics and are disclosed; no guessed source-to-copy retargeting. Hand-edited source/target before write/restore triggers conflict and fresh review; user confirmation alone cannot waive failed identity/security validation. Cannot prove safe restore → block rather than discard source sheet IDs and recreate guessed equivalents.


## Connected manual-acceptance protocol

New authenticated read-only preservation-begin/chunk/finish actions inspect complete compressed native packages. They grant no write authority. Opaque evidence IDs bind the exact native semantic image to the parsed package and original transport; completed volatile captures have bounded FIFO eviction. Client images contain only evidence metadata/fullFingerprint. The server embeds verified canonical package evidence privately in journal images and independently validates approved deltas/new groups/deletions and unchanged survivors.

begin/write-ready/undo/redo require expectedPreservationFingerprint in addition to semantic/source/native-ID bindings. Actual after preservation fingerprints are committed only after independent native comparison; they are not guessed before import. Own preparation-session custom XML is excluded precisely from package conflict fingerprints; other custom XML remains protected. Recovery metadata contains no executable approval or raw data. First target selection/new-session reset is explicit; page teardown uses detach, while legacy panes without preparation retain full-close semantics.

Application manual mode enables supported actions with nativeQualification user_pending at the user's instruction. Store-only legacy claims still cannot write. Full native acceptance and release qualification remain pending; Technical hard blockers are unchanged.
