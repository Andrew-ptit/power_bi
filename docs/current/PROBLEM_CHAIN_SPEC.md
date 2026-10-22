# Problem Chain v1 — Functional and Technical Specification

## 1. Document control

| Field | Value |
|---|---|
| Version | 1.7 |
| Date | 2026-10-21 |
| Status | Current contract; see [verification status](CURRENT_STATUS.md) |
| Owner | Local Data Copilot |
| Scope | Excel task pane — Typed Steps only |
| Related specifications | `PQ_CODE_M_SPEC.md`, `IMPLEMENTATION_PLAN.md`, `TYPED_STEP_DIAGNOSTICS_SPEC.md` |

## 2. Objective

Problem Chain lets a user solve a data problem through successive prompts without losing prior pipeline states. Each accepted problem or manual semantic edit creates an immutable revision. The workbook stores the history so it can be restored after Excel closes. Preview, approval and Apply remain bound to the exact current semantic revision.

Problem Chain never treats an AI answer as approval, never uses Advanced M to bypass Typed Steps, never silently changes downstream logic and never writes source cells while persisting history.

## 3. Current behavior

Verification status is maintained in [CURRENT_STATUS.md](CURRENT_STATUS.md).

### Display and full-result caches

- A successful Excel runtime Preview creates **staging** with `runVersion = dataVersion` captured before execution. It does not replace either cache. Staging displays at most 20 rows × 200 columns before and after. Only after explicit confirmation, successful values-only write and read-back does the result replace the revision's cache entry. Cancel discards staging and keeps the previous cache entry.
- Cache key includes workbook runtime identity, chain ID, revision ID and review hash; every entry also records its `dataVersion`. The display cache truncates text cells over 256 characters. Only the latest confirmed result per revision is kept. Updating a revision moves it to the FIFO tail; a sixth distinct result evicts the oldest entry.
- `Xem` displays the old step cards and bounded sample immediately, without Excel or coordinator calls. It does not change HEAD or grant write authority.
- A second cache in the coordinator retains up to five **complete values-only result packages**, additionally capped at 64 MiB of encoded data in aggregate. FIFO eviction may leave fewer than five large results. Neither cache is written to Custom XML; neither retains an approval token.
- The global checkbox `Dữ liệu nguồn đã thay đổi` is a one-shot signal that increments session `dataVersion`. It does **not** delete older cached results; these remain visible with an old-version label for comparison. Active unconfirmed staging/approval becomes invalid. Revisions are recomputed lazily when selected.
- On `Quay lại bản này`, the committed checkout changes HEAD first. A cached write is permitted only if cache `dataVersion` matches current `dataVersion` **and** chain/HEAD/history/review hash, workbook identity and the current source-data fingerprint match. The fingerprint is recomputed from the workbook export while excluding only an unreferenced Typed result sheet. `dataVersion` is a user signal, never a substitute for the fingerprint: forgotten checkbox changes must still block cached writes. The server then issues a single-use apply attempt. It never writes source cells or calls Save.
- Version mismatch, missing/evicted/oversized cache or fingerprint mismatch triggers a new staging Preview with separate confirmation before writing. No truncated result or old-version cache is written.
- An old preview/approval cannot authorize restore. The explicit checkout click is a new write decision, and the cache-restore endpoint performs its own deterministic pre-write checks. If a write might have begun and read-back fails, the UI reports partial/unknown state and does not retry automatically.
- Panel/session reset, workbook identity change or chain change clears the cache. Reloading the same chain in the same panel retains only entries whose revision review hashes still match. Closing the panel loses the cache.

## 4. Scope

### 4.1 In scope

- Create a root revision from the first Typed problem.
- Continue from the current leaf head.
- Preserve every previous semantic revision unchanged.
- View any revision and checkout an existing revision as head.
- Store and rehydrate history through one Custom XML Part.
- Runtime feature gate at ExcelApi 1.5 while retaining the existing manifest requirement set.
- Optimistic concurrency using `historyHash`.
- Bind preview/approval/apply to `chainId`, current head, revision and review hash.
- Invalidate runtime authority on checkout, semantic edit, workbook/source change or session reset.
- Preserve existing Advanced M and Typed Steps v2 behavior when Problem Chain is unsupported or unused.

### 4.2 Out of scope

- Branch merge, multi-user collaboration or conflict auto-merge.
- Editing annotations, runtime comparison UI and persisted runtime summaries are excluded permanently from this release scope. Reserved schema fields remain null for compatibility.
- Persisting preview rows, approval tokens, workbook bytes or sample rows **in workbook history** by default. Cached full-result bytes remain session-only.
- Advanced M Problem Chain.
- Automatic Save, Save As, source-cell write or query/connection persistence.

## 5. Terms

| Term | Definition |
|---|---|
| Problem | One user prompt and the semantic pipeline state it creates. |
| Revision | Immutable snapshot of the complete Typed pipeline after a problem or semantic edit. |
| Head | Revision currently used for continuation and runtime actions. |
| View revision | Revision displayed by the UI; held only in task-pane memory. |
| Candidate mutation | Server-validated history document not yet persisted to Custom XML. |
| Commit | Confirmation that task pane wrote and read back the exact candidate history hash. |
| Source schema fingerprint | Hash of referenced Table/usedRange names, ordered columns and inferred normalized types under a versioned policy. |
| Preview input fingerprint | Runtime-only data fingerprint used to detect data changes after preview. |

## 6. Business rules

| ID | Rule |
|---|---|
| PC-BR-001 | Every semantic mutation shall create a new random `revisionId`; no existing semantic revision may be edited in place. |
| PC-BR-002 | A chain shall contain exactly one root and may contain multiple children per revision; tips are derived and `branchTip` is never persisted. |
| PC-BR-003 | Ordinary continuation may be created only from the current leaf HEAD. A non-linear child requires explicit `branch` intent. |
| PC-BR-004 | Checkout changes only `headRevisionId`; it shall not delete or alter revisions. |
| PC-BR-005 | `name`, `note` and runtime evidence shall not participate in `reviewHash`. |
| PC-BR-006 | Custom XML persistence shall never call Save and shall never write cells, Tables, formulas, queries or connections. |
| PC-BR-007 | Preview/approval/apply shall be permitted only when the viewed revision equals the persisted head revision. |
| PC-BR-008 | Any head or semantic change shall invalidate preview and approval from the previous head. |
| PC-BR-009 | Duplicate Problem Chain namespace parts shall hard-block load and mutation; the system shall not choose or delete one. |
| PC-BR-010 | No history mutation shall use last-writer-wins; `historyHash` mismatch shall fail closed. |
| PC-BR-011 | History shall be limited to 50 revisions or 2 MiB canonical JSON, whichever is reached first, before a planner call. |
| PC-BR-012 | Sample rows shall not be persisted unless a future explicit opt-in flow records acknowledgement. |
| PC-BR-013 | Session expiry shall allow rehydration from workbook XML but shall not restore preview, approval or apply authority. |
| PC-BR-014 | Save As copies history but invalidates runtime authority because workbook runtime identity changes. |
| PC-BR-015 | Co-authoring is unsupported in v1; detected history conflicts shall require reload. |
| PC-BR-016 | The task pane may retain only bounded confirmed-result display rows in task-pane memory: one latest entry per revision, at most five entries, evicting the oldest on a sixth distinct confirmation. |
| PC-BR-017 | A cached display shall never be treated as a current runtime Preview or grant Approve/Apply authority. An explicit checkout click may restore a separately stored full result only after server HEAD/history/review/source checks. |
| PC-BR-018 | Caches shall be cleared on panel/session reset or workbook/chain change and shall not be persisted to Custom XML. Cached display must be marked historical. |
| PC-BR-019 | Full-result cache shall keep at most five results and at most 64 MiB encoded data; eviction or stale input shall trigger a fresh Preview rather than a partial write. |
| PC-BR-020 | The global changed-source checkbox shall increment session `dataVersion` and invalidate unconfirmed staging/approval, while retaining old-version cache entries for comparison. An old-version cache shall never be written directly. |
| PC-BR-021 | A new Preview shall remain staging. Only successful explicit confirmation, values write and read-back may promote it to the bounded caches; cancel or failed write shall preserve the previous cache entry. |
| PC-BR-022 | Even when `dataVersion` matches, a cached write shall recheck source-data fingerprint, workbook identity, committed HEAD/history and review hash. |
| PC-BR-023 | Editing a non-root problem shall create a sibling from the original parent; the old problem and all descendants remain byte-for-byte unchanged. |
| PC-BR-024 | Impact analysis is advisory and conservative. It may mark old descendants for review but shall never replay, delete, patch or re-parent them. |
| PC-BR-025 | Editing the root is unavailable because the persisted chain permits exactly one root. |
| PC-BR-026 | `Làm tiếp từ đây` creates a child of the selected revision; `Làm lại vấn đề` creates a sibling from the selected problem's parent. |
| PC-BR-027 | Explicit history deletion removes the selected revision and its entire subtree. A leaf deletes immediately; a node with descendants requires confirmation; the root cannot be deleted. Surviving revisions remain byte-for-byte unchanged. |
| PC-BR-028 | A planner question that needs user input shall return clarification, not a candidate. It shall not create a revision, change HEAD, persist Custom XML, grant Preview/Apply authority or alter caches. |

## 7. Persistence model

### 7.1 XML envelope

Namespace:

`urn:local-data-copilot:pq-problem-chain:v1`

```xml
<ldc:problemChain
  xmlns:ldc="urn:local-data-copilot:pq-problem-chain:v1"
  schemaVersion="1.0"
  historyHash="sha256:...">
  <ldc:payload encoding="base64">...</ldc:payload>
</ldc:problemChain>
```

The payload is canonical JSON encoded as UTF-8 and Base64. Raw XML byte equality is not authoritative because Excel may normalize XML declarations.

### 7.2 History document

```json
{
  "schemaVersion": "1.0",
  "chainId": "chain_<24hex>",
  "planId": "plan_<24hex>",
  "storageVersion": 2,
  "headRevisionId": "rev_<24hex>",
  "samplePersistence": {
    "enabled": false,
    "warningAcceptedAt": null,
    "maxRows": 20,
    "maxColumns": 200
  },
  "sampleStore": {},
  "revisions": []
}
```

The persisted document shall not contain `branchTip`, `latestRevisionId`, session tokens, preview IDs, approvals, workbook bytes or result values.

### 7.3 Revision record

Required fields:

- `revisionId`, `parentRevisionId`, `originKind`, `createdAt`.
- `problemPrompt`, `changeReason`, `name`, `note`, `annotationUpdatedAt`.
- `sourceSchemaFingerprint`, `snapshotId`.
- `summary`, `questions`, `assumptions`, `warnings`.
- `sources`, `steps`, `finalOutputStepId`, `changeSet`.
- `validationAtCreation`, `runtimeSummary`, `reviewHash`.

`originKind` is one of `problem`, `manualEdit` or `repairPatch`. The current history exposes problem continuation and existing Typed manual edits; repair patches remain governed by Typed v2.

### 7.4 IDs and hashes

- Authoritative IDs are generated by the coordinator using cryptographically secure randomness.
- `revisionId` format is `rev_<24 lowercase hex>`.
- `reviewHash` covers the prompt, source schema fingerprint, user-visible semantic descriptions, assumptions/warnings, referenced sources, complete ordered steps and final output.
- `reviewHash` excludes IDs, parents, timestamps, annotations, validation/runtime evidence, sample rows and authority tokens.
- `historyHash` covers the entire canonical history document except any hash field representing itself.

## 8. Source fingerprints

`sourceSchemaFingerprint` is SHA-256 over canonical JSON containing `pq-infer-v1` and only referenced sources.

- Excel Table identity uses workbook-unique `objectName`; `sheetName` is display-only and excluded from the Table hash.
- usedRange identity includes `sheetName` and `headerRow`.
- Ordered columns contain only ordinal, name and normalized type.
- Workbook path/name, row count, values, active sheet, source IDs and column IDs are excluded.
- Normalized types are `any`, `text`, `integer`, `number`, `logical`, `date` and `datetime`, inferred from at most 20 current rows.

Runtime data changes are tracked separately by `previewInputFingerprint`, which is session-only and remains part of preview/approval/apply validation.

## 9. API contract

All endpoints require a valid coordinator session. Expired sessions return `401 TOKEN_EXPIRED`; the task pane may bootstrap once but shall not replay the failed POST.

### 9.1 Load

`POST /api/pq/v2/problem-chains/load`

Request:

```json
{"document": null}
```

or a decoded history document read from Custom XML. The server validates schema, graph, hashes, limits and Typed operations before returning a normalized copy. Persisted validation is historical evidence only.

### 9.2 Create problem

`POST /api/pq/v2/problem-chains/problems`

```json
{
  "document": {},
  "baseHistoryHash": "sha256:...",
  "baseRevisionId": "rev_...",
  "creationMode": "continue",
  "editRevisionId": null,
  "prompt": "Normalize Region",
  "workbook": {},
  "source": {}
}
```

Explicit creation modes:

- `continue`: extend only the current leaf HEAD; `editRevisionId` must be null.
- `branch`: explicitly create a child of any existing `baseRevisionId`.
- `editProblem`: create a sibling replacement. `editRevisionId` identifies the non-root problem being replaced and `baseRevisionId` must equal its original parent.

Omitting `creationMode` remains backward-compatible with `continue`. A branch/edit candidate changes neither committed HEAD nor runtime authority until Custom XML read-back and commit succeed.

For a root problem, `document`, `baseHistoryHash` and `baseRevisionId` are null. The coordinator creates the authoritative validated Typed plan from `prompt`, `workbook` and `source`; a client-supplied `typedPlan` has no authority. For continuation, the planner receives the base pipeline and returns strict Typed `changes[]` only. The coordinator applies these changes, retaining stable step IDs and rejecting full-pipeline replacement or raw M. The `source` field identifies the initial source; continuation rechecks the current workbook source catalog.

Response is an uncommitted candidate:

```json
{
  "mutationId": "mut_...",
  "baseHistoryHash": "sha256:... or null",
  "document": {},
  "historyHash": "sha256:...",
  "revision": {},
  "creationMode": "editProblem",
  "impactReport": {
    "affectedRevisionIds": [],
    "affectedStepIds": [],
    "affectedColumnIds": [],
    "issues": []
  }
}
```

`impactReport` is returned for `editProblem`. It lists preserved descendants requiring review; it is not a repair patch and never changes those descendants.

If analysis needs a business rule, the same endpoint instead returns HTTP 200 with no candidate or `mutationId`:

```json
{"status":"needsClarification","questions":["Which column should be used?"],"assumptions":[],"warnings":[]}
```

The composer keeps the original request and base action in memory. It collects an answer for each question, then resubmits the original request with a bounded `Làm rõ yêu cầu` question/answer section. If analysis still needs clarification, it asks again without persisting anything. A changed original request or Cancel discards the pending answers. The normal candidate/CAS/commit path runs only after no mandatory question remains. Every resubmission rechecks the current workbook, source and history; answers never bypass these checks.
If the planner proposes a column that deterministic Typed validation cannot resolve, the endpoint also requests clarification before persisting. Source-not-found, policy and unrelated structural failures remain hard blockers, not user questions.

### 9.3 Checkout

`POST /api/pq/v2/problem-chains/checkout`

```json
{
  "document": {},
  "baseHistoryHash": "sha256:...",
  "revisionId": "rev_..."
}
```

Checkout returns a candidate document with only `headRevisionId` and storage metadata changed. It invalidates runtime authority after commit.

### 9.4 Commit

`POST /api/pq/v2/problem-chains/mutations/commit`

```json
{
  "mutationId": "mut_...",
  "observedHistoryHash": "sha256:..."
}
```

The coordinator accepts commit only when the observed hash equals the pending candidate. Pending mutations are in-memory, session-bound and single-use.

### 9.5 Session result restore

`POST /api/pq/v2/problem-chains/cached-results/prepare` receives the committed `revisionId`, `baseHistoryHash`, current `workbook`/`workbookBase64`, `sourceDataChanged: false` and the Typed destination marker. It returns a values-only workbook and a one-time `applyId` only if the full result cache exists and the current workbook fingerprint still matches. The task pane writes only to the marked result sheet and calls existing `/api/pq/v2/applies/complete` with read-back dimensions.

`POST /api/pq/v2/problem-chains/data-version/increment` receives the committed HEAD, history hash and workbook identity. It increments the session version, invalidates unconfirmed staging/approval and retains older full results for comparison. The former `/cached-results/invalidate` path is a compatibility alias with the same version-increment semantics; it no longer deletes cache entries. `/api/pq/v2/previews` returns `runVersion` and creates staging only. `/api/pq/v2/problem-chains/previews/cancel` discards active staging without replacing the prior cache. Successful `/api/pq/v2/applies/complete` promotes the staged result to cache after read-back.

## 10. Custom XML mutation protocol

1. Read matching parts with `getByNamespace`.
2. Hard-block when count is greater than one.
3. Decode and load the current document.
4. Send the current `historyHash` as compare-and-swap base.
5. Receive a server-validated candidate and `mutationId`.
6. Re-read the current part immediately before writing.
7. Abort with `PQPC_HISTORY_CONFLICT` when the base changed.
8. Use `add` for zero parts or `setXml` for one part; call `context.sync()`.
9. Read back and validate the exact candidate hash.
10. Commit using `mutationId` and observed hash.

If XML write succeeds but commit/network fails, the task pane shall not roll back or replay automatically. On the next bootstrap, workbook XML is the source of truth.

## 11. Functional requirements

| ID | Requirement |
|---|---|
| PC-FR-001 | The system shall runtime-gate Problem Chain at ExcelApi 1.5. |
| PC-FR-002 | The system shall create a root revision from the first validated Typed Plan. |
| PC-FR-003 | The system shall create a child revision from the current leaf head using Typed continuation changes. |
| PC-FR-004 | The system shall preserve all previous revision records unchanged. |
| PC-FR-005 | The system shall load and validate one namespaced Custom XML Part. |
| PC-FR-006 | The system shall reject duplicate namespaced parts without modifying either part. |
| PC-FR-007 | The system shall implement the ten-step optimistic mutation protocol. |
| PC-FR-008 | The system shall allow viewing any revision without changing head. |
| PC-FR-009 | The system shall checkout an existing revision through a committed history mutation. |
| PC-FR-010 | The system shall reject `continue` from a non-leaf revision; creating a child from that revision requires explicit `branch` mode. |
| PC-FR-011 | The system shall disable Preview and Approve when view revision is not head. |
| PC-FR-012 | The system shall invalidate preview/approval after checkout or semantic continuation. |
| PC-FR-013 | The system shall rehydrate history after coordinator session renewal without restoring authority tokens. |
| PC-FR-014 | The system shall show that Save or Save As is required for persistence after XML mutation. |
| PC-FR-015 | The system shall block mutation before planner invocation at the history count or byte limit. |
| PC-FR-016 | The system shall not call Save or write workbook cells while persisting history. |
| PC-FR-017 | Add, edit, delete, reorder and set-final in an active Problem Chain shall create a `manualEdit` candidate revision from the committed leaf head; the previous revision remains unchanged. |
| PC-FR-018 | A manual-edit candidate shall gain no preview, approval or Apply authority until Custom XML CAS, read-back and commit succeed. The standalone Typed revision endpoint shall not bypass this protocol. |
| PC-FR-019 | A manual edit with broken dependencies shall remain visible as a blocked revision, without implicit downstream deletion; preview, approval and Apply shall fail with a deterministic blocker before Excel runs. |
| PC-FR-020 | The task pane shall retain up to five bounded confirmed-result display snapshots by revision in session memory and apply FIFO eviction. |
| PC-FR-021 | `Xem` shall display cached cards/sample without changing HEAD or contacting Excel/coordinator. `Quay lại bản này` shall commit HEAD and attempt a complete cached-result write only when the changed-source checkbox is clear and server validation passes. |
| PC-FR-022 | Cache shall be isolated by workbook/chain/review hash, cleared at session reset, and excluded from workbook history and prior approval authority. |
| PC-FR-023 | Changed-source version, cache miss, size eviction or stale input shall run a new staging Preview and require review/approval before writing. |
| PC-FR-024 | The task pane shall show current session `dataVersion` and label older cache entries as historical/comparison-only. |
| PC-FR-025 | The task pane shall expose explicit `Tạo nhánh từ đây` and shall never infer branch intent from View or Checkout. |
| PC-FR-026 | The server shall permit a validated branch tree while retaining exactly one root and deriving tips from parent links. |
| PC-FR-027 | `Sửa vấn đề` on a non-root revision shall create a sibling candidate from its parent and return conservative descendant impact metadata. |
| PC-FR-028 | The system shall preserve old siblings and descendants without automatic replay, deletion, re-parenting or repair. |
| PC-FR-029 | `POST /api/pq/v2/problem-chains/problems/delete` shall prepare a CAS-bound subtree-deletion candidate without invoking the planner. If HEAD is deleted, HEAD moves to the deleted node's parent. |
| PC-FR-030 | Root, continuation, branch and edit analysis shall display mandatory planner questions in the active composer and collect answers before creating a revision. Duplicate non-blocking notes shall be collapsed. |

## 12. UI requirements

- Typed Steps remains the default Power Query mode.
- Problem Chain appears only when ExcelApi 1.5 is supported.
- A vertical timeline shows prompt excerpt, timestamp, step count, validation status and output dimensions when known.
- The UI renders the timeline as a deterministic tree ordered by `createdAt`, then `revisionId`, with indentation derived from parent links.
- The current head has a visible `HEAD` badge.
- `Xem` changes only in-memory `viewRevisionId`.
- One changed-source checkbox appears above the timeline, not on every revision; checking it increments `dataVersion` once and does not delete old cache.
- `Quay lại bản này` commits checkout, then restores a valid same-version full cached result to the marked result sheet or runs a new staging Preview on changed/missing cache.
- Staging exposes Confirm and Cancel. Confirm writes the result and promotes cache only after read-back; Cancel restores the prior cached display without changing its bytes.
- The problem composer always states which head it will extend.
- Clarification appears inside that composer after analysis, with one answer field per question and a `Gửi câu trả lời và phân tích tiếp` action. HEAD, history and cache remain unchanged while questions are open. Notes are collapsed separately from mandatory questions.
- When view differs from head, Preview/Approve/Apply controls are disabled with an actionable explanation.
- Every committed mutation shows: “Lịch sử đã được nhúng vào workbook đang mở. Hãy Save hoặc Save As để giữ lịch sử sau khi đóng file.”
- Duplicate XML, stale hash, unsupported API and storage-limit conditions render as blockers, not generic errors.
- Every revision exposes `Tạo nhánh từ đây`; non-root problem revisions expose `Sửa vấn đề`. Root edit is disabled with an explanation.
- An edit impact panel states that old descendants were preserved and lists affected revision, step and column identifiers.

## 13. Error catalogue

| Code | Meaning and required behavior |
|---|---|
| `PQPC_EXCEL_API_UNSUPPORTED` | Hide/disable Problem Chain; retain session-only Typed Steps. |
| `PQPC_DUPLICATE_XML_PART` | Hard block; do not select, overwrite or delete a part. |
| `PQPC_DOCUMENT_INVALID` | Do not hydrate or overwrite XML. |
| `PQPC_HASH_MISMATCH` | Hard block tampered/noncanonical document. |
| `PQPC_HISTORY_CONFLICT` | Reload; do not overwrite or auto-merge. |
| `PQPC_HISTORY_LIMIT` | Do not call planner or create candidate. |
| `PQPC_REVISION_NOT_FOUND` | Do not change head. |
| `PQPC_HEAD_MISMATCH` | Block runtime action or continuation. |
| `PQPC_RESULT_CACHE_MISS` | Full result was evicted/unavailable; run a new Preview without writing. |
| `PQPC_RESULT_CACHE_STALE` | Workbook/source/revision changed or changed-source mode was selected; do not write old result. |
| `PQPC_BRANCH_INTENT_REQUIRED` | Ordinary continuation targeted a non-leaf revision; require the explicit branch action. |
| `PQPC_EDIT_BASE_MISMATCH` | Edited problem was not based on its original parent; reject before planner execution. |
| `PQPC_EDIT_ROOT_UNSUPPORTED` | Root editing would create a second root; use a branch instead. |
| `PQPC_EDIT_TARGET_INVALID` | `editProblem` targeted a manual-edit/repair revision rather than a user problem revision. |
| `PQPC_SOURCE_SCHEMA_CHANGED` | Permit history viewing but block preview until source is reconciled. |
| `PQPC_MUTATION_NOT_COMMITTED` | Candidate has no runtime authority. |
| `PQPC_FILE_FORMAT_UNSUPPORTED` | Warn that history persistence is not promised. |

## 14. Non-functional and security requirements

| ID | Requirement |
|---|---|
| PC-NFR-001 | Canonical history validation shall complete before any planner call. |
| PC-NFR-002 | Logs shall not contain prompts, raw cells, XML payload, workbook bytes, tokens or absolute temporary paths. |
| PC-NFR-003 | The task pane shall make no cell write and no Save call during history persistence. |
| PC-NFR-004 | Unknown fields, non-finite numbers, DTD/entities, raw M, URL, path and credential fields shall fail closed. |
| PC-NFR-005 | Candidate mutations and commits shall be atomic within one coordinator session. |
| PC-NFR-006 | Existing Advanced M and Typed v2 API contracts shall remain backward compatible. |
| PC-NFR-007 | History read/write shall be bounded at 2 MiB canonical JSON and 50 revisions. |

## 15. Acceptance criteria

| ID | Acceptance criterion |
|---|---|
| PC-AC-001 | Problem 1 followed by Problem 2 yields two revisions; revision 1 remains deep-equal to its original record. |
| PC-AC-002 | Continuation may insert a step in the middle while producing a valid topological graph. |
| PC-AC-003 | Viewing a revision does not alter head or history. |
| PC-AC-004 | Checkout revision 1 restores its pipeline/final output and keeps later revisions. |
| PC-AC-005 | Submitting a problem from checked-out revision 1 when it has a child returns `PQPC_BRANCHING_NOT_AVAILABLE`. |
| PC-AC-006 | Preview/approval for revision B becomes unusable after checkout to A. |
| PC-AC-007 | Save/reopen and Save As rehydrate identical history while runtime approvals remain absent. |
| PC-AC-008 | Default persisted XML contains no sample/cell sentinel. |
| PC-AC-009 | Data-only change preserves schema hash but invalidates preview input fingerprint. |
| PC-AC-010 | Inferred type change changes source schema fingerprint. |
| PC-AC-011 | Revision 51 or canonical payload over 2 MiB is rejected before planner invocation. |
| PC-AC-012 | ExcelApi 1.4 never calls Custom XML APIs. |
| PC-AC-013 | Duplicate namespace parts and stale history hashes leave workbook metadata unchanged. |
| PC-AC-014 | Existing Advanced M and Typed v2 focused/full regression remains green. |
| PC-AC-015 | Each manual add/edit/delete/reorder/set-final creates a new immutable `manualEdit` revision only after XML commit; cancel, stale CAS or ambiguous commit leaves runtime controls disabled until reload. |
| PC-AC-016 | Deleting a producer or invalidly reordering steps preserves the blocked revision and returns a controlled dependency error on preview with zero Excel runner calls. |
| PC-AC-017 | Six distinct confirmed results leave exactly the newest five; confirming an existing revision replaces its old entry and moves it to the FIFO tail. Unconfirmed staging leaves the FIFO unchanged. |
| PC-AC-018 | `Xem` a cached revision renders before/after sample rows immediately with a historical label, zero Excel/coordinator calls, no active `previewId`, and disabled Approve/Apply. |
| PC-AC-019 | Session/workbook/chain changes clear or reconcile cache; no cached rows or runtime authority are serialized to Custom XML. |
| PC-AC-020 | An unchecked checkout of a revision with a valid full-result cache writes all cached values to the marked result sheet, with no M runner call, and read-back completes the one-time apply attempt. |
| PC-AC-021 | Checking changed-source increments `dataVersion`, preserves old cache for comparison, invalidates staging/approval and forces a new staging Preview before a write from an older result. |
| PC-AC-022 | Source value/identity/history/review mismatch, cache eviction or size limit never yields a cached write payload; the UI falls back to Preview. |
| PC-AC-023 | A Typed result-sheet rewrite does not falsely stale source fingerprints when the sheet is not a pipeline source; edits to actual sources still do. |
| PC-AC-024 | Cancel or failed read-back never promotes staging; the previous cache remains. Matching `dataVersion` with changed actual source data still blocks a cached write by fingerprint. |

### Branch/edit/delete acceptance criteria

| ID | Acceptance criterion |
|---|---|
| PC-AC-025 | Explicitly branching from revision 1 creates a second child while the prior revision 2 and its descendants remain deep-equal. |
| PC-AC-026 | The uncommitted branch candidate grants no HEAD, Preview, approval or Apply authority; after commit only the new child becomes HEAD. |
| PC-AC-027 | Tree display order is deterministic by `createdAt`, then `revisionId`, and no `branchTip`/`latestRevisionId` field is serialized. |
| PC-AC-028 | Editing a non-root problem creates a sibling from its parent; descendants of the old problem are preserved and appear only in the impact report. |
| PC-AC-029 | Editing root, using a mismatched edit base, stale CAS, changed source schema or implicit continuation from a non-leaf fails before planner execution. |
| PC-AC-030 | A 50-node branch tree validates within the normal bounded request path; node 51 is rejected before planner execution. |
| PC-AC-031 | The UI submits explicit mode/base/edit IDs and renders a descendant-impact warning without auto-applying a patch. |
| PC-AC-032 | From Problem 1, `Làm tiếp` on Problem 2 creates a child of Problem 2; `Làm lại Problem 2` creates a sibling of Problem 2 under Problem 1. |
| PC-AC-033 | Deleting a leaf requires no confirmation. Deleting a parent asks once and deletes only that subtree. Root deletion and stale CAS are rejected. |
| PC-AC-034 | A question-only root or branch response has no `mutationId`, creates no revision or Custom XML write, and leaves the prior HEAD/Preview/cache unchanged. Complete answers produce one candidate through the ordinary CAS/commit path. |
| PC-AC-035 | Empty answers cannot submit; follow-up questions remain in the same composer; Cancel or editing the original prompt discards only pending Q&A. A stale workbook/history response still fails closed. |

## 16. Test and release gates

1. Domain/schema/hash tests and negative tests pass.
2. Independent cross-review supplies at least one oracle not copied from implementer tests.
3. Task-pane fake Office.js tests prove feature gate, duplicate blocking, optimistic conflict and no Save/cell write.
4. API integration tests prove load/problem/checkout/commit and stale/single-use mutations.
5. Live Codex continuation smoke passes; mock-only cannot close the planner gate.
6. Full Python and JavaScript regression passes.
7. Manual sideload proves create two revisions, checkout, Save/reopen and head-bound preview behavior.
8. Timeout, skip, auth/network failure or missing manual evidence is reported as Blocked/Not run.



## 17. Traceability

| Requirement group | Primary tests |
|---|---|
| PC-FR-002–004 | Root/continuation immutability and graph tests |
| PC-FR-005–007 | Custom XML codec, duplicate and CAS tests |
| PC-FR-017–019 / PC-AC-015–016 | Manual-edit candidate, CAS/commit, blocked dependency and zero-runner HTTP oracles |
| PC-FR-020–022 / PC-AC-017–019 | Task-pane FIFO/cache hit, approval isolation and workbook/session invalidation tests |
| PC-FR-008–012 | Timeline/head/view and stale runtime tests |
| PC-FR-013–016 | Session rehydrate, warning, limits and no-write tests |
| PC-NFR-001–007 | Adversarial schema/security/performance regression |
| PC-AC-001–019 | History/cache integration, manual-edit, cache and manual exit checklist |

## 18. Ownership

| Owner | Files and responsibility |
|---|---|
| Domain/Server agent | History model, hashes, random IDs, pending mutations and focused domain tests |
| Task Pane agent | Custom XML adapter, timeline/head/view UI and fake Office.js tests |
| Independent QA agent | Adversarial cross-oracles and measured review report |
| Root integrator | API routes, session/runtime binding, documentation, regression, conflict resolution and final evidence |

Cross-review is mandatory: UI reviews API usability, QA reviews storage/UI failure paths, Domain reviews independent hash oracles, and root closes only evidence-backed gates.
