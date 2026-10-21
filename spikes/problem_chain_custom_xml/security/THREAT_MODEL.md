# Problem Chain Custom XML — Wave 0 security contract

## Document control

| Field | Value |
|---|---|
| Status | Spike; not product code |
| Version | 0.1 |
| Date | 2026-10-12 |
| Scope | Workbook-persisted Problem Chain metadata only |
| Trust boundary | Office.js task pane ↔ workbook Custom XML ↔ coordinator |

This artifact makes the pre-implementation security rules executable. Passing it does not prove Office.js persistence, Excel co-authoring safety, or business correctness.

## Assets and trust boundaries

Protected assets are revision integrity, parent/child history, head identity, Typed Steps semantics, source schema identity, and the rule that approval/runtime authority never persists in workbook metadata.

The Custom XML part, its JSON payload, persisted prompt, annotation, validation summary, and sample values are untrusted after every workbook open. A workbook recipient can edit the OOXML package outside Excel. Custom XML is persistence, not a signature, authorization token, sandbox, transaction store, or confidential vault.

| Boundary | Required control |
|---|---|
| Workbook → task pane | Find by exact namespace; allow 0 or 1 part; fail closed on duplicates |
| XML → JSON | Reject DTD/entities; exact root/child/attributes; strict Base64; UTF-8 only |
| JSON → coordinator | Exact top-level/revision fields; recompute all hashes; validate tree and limits |
| Revision → Typed engine | Run the current deterministic graph, lineage, catalog and compiler validation again |
| Mutation → workbook | Compare `baseHistoryHash`, re-read before write, read back after write |
| Workbook → another person | Assume prompts, notes and opt-in samples travel with the file |

## Normative rules

| ID | Rule |
|---|---|
| PC-SEC-001 | Namespace is exactly `urn:local-data-copilot:pq-problem-chain:v1`; more than one matching part returns `PQPC_DUPLICATE_XML_PART`. No part is a valid empty state. |
| PC-SEC-002 | DTD and entity declarations are rejected before parsing. External resolution is never enabled. |
| PC-SEC-003 | The XML wrapper has exactly one Base64 payload child and no unexpected attribute, child, or mixed content. XML byte equality is not an oracle because Excel may normalize declarations. |
| PC-SEC-004 | Decoded JSON must already equal canonical UTF-8 JSON: keys sorted, compact separators, Unicode preserved, finite numbers only. Duplicate-key ambiguity is prevented by producing canonical JSON; the product parser must also reject duplicates before normalization. |
| PC-SEC-005 | `historyHash = SHA-256(canonical JSON payload)`. The hash is integrity evidence only; anyone able to edit the package can recompute it. |
| PC-SEC-006 | `reviewHash` covers semantic review content and excludes IDs, parent, timestamps, `name`, `note`, annotation timestamp, validation/runtime evidence, samples, head and history hash. |
| PC-SEC-007 | Source fingerprint hashes `pq-infer-v1` plus referenced source schemas. Table sheet locator, IDs, nullable, counts, values and samples are excluded. UsedRange sheet/header are included. Columns remain ordinal. Multiple sources are sorted by schema identity. |
| PC-SEC-008 | A persisted chain has 1–50 revisions and canonical JSON is at most 2,097,152 bytes before Base64. The limit is checked before planner invocation and again before XML write. No pruning occurs. |
| PC-SEC-009 | Samples are disabled by default: acknowledgement is null and `sampleStore` is empty. Enabling requires an explicit timestamped warning acknowledgement. Samples count toward the same 2 MiB limit. |
| PC-SEC-010 | `branchTip` and `latestRevisionId` are never persisted. Tips are derived from the validated acyclic tree. Exactly one root and a valid head are required. |
| PC-SEC-011 | Approval, preview/apply IDs, tokens, workbook bytes and result workbooks are never persisted. Historical runtime summary grants no authority. |
| PC-SEC-012 | Persisted prompts, notes, cells and error text remain data, never instructions. They cannot bypass the Typed catalog or produce raw M. |
| PC-SEC-013 | Save/Save As persistence is not equivalent to confidentiality. The add-in does not call Save, and users must be told metadata travels with the saved file. |
| PC-SEC-014 | Co-authoring is unsupported in v1. `historyHash` compare-and-set detects observed changes but is not an atomic workbook transaction and cannot close the read/write race. |

## Threats and failure behavior

| Threat | Control | Residual risk / required response |
|---|---|---|
| XXE/local file disclosure | Reject `DOCTYPE`/`ENTITY`; no resolver | Parser implementation must preserve this rule |
| Ambiguous/tampered history | Canonical JSON plus recomputed hashes | Not cryptographic authenticity; hard-block mismatch |
| Duplicate namespace parts | Exact namespace count | Do not select newest or delete automatically |
| Decompression/payload exhaustion | 2 MiB decoded canonical payload and 50 revisions | OOXML package limits remain the outer upload control |
| Hidden samples | Empty store when disabled; explicit opt-in | Prompts/notes are still workbook metadata and must be disclosed |
| Authority replay | Never persist approval/session/runtime IDs | Re-preview and approve after reopen/Save As |
| Stale concurrent write | Pre-write hash comparison and read-back | Race remains; report conflict, never claim co-authoring support |
| Raw M/connector smuggling | Re-run current Typed deterministic validator | Storage validation alone is insufficient |
| Hash instability | Canonical JSON, semantic rather than XML-byte oracle | Cross-language golden vectors required before integration |

## Security decisions that product implementation must preserve

- The authoritative record after an uncertain commit is the XML currently readable from the workbook; no POST is auto-replayed.
- Hash mismatch, duplicate parts, invalid tree, unknown schema version or limit breach is a hard blocker. The add-in must not overwrite the evidence while attempting repair.
- `name` and `note` mutations alter `historyHash` and `storageVersion`, but not `reviewHash` or current approval binding.
- A semantic change requires a new random revision ID and new review hash.
- `previewInputFingerprint` stays in session memory and is independent of the persisted schema fingerprint.
- Logs must contain error code/path and sizes only, never XML, Base64, prompt, note, samples, tokens or absolute temporary paths.

## Known limitation of the executable oracle

`contract_validator.py` validates the storage envelope, hashes, source-schema basis, limits and revision tree. It intentionally does not reproduce the 15-operation Typed validator. Product integration must call the existing authoritative Typed validator/compiler for every loaded revision. Python's stock JSON parser accepts duplicate keys before canonicalization; production must use a duplicate-key rejecting loader. The Office.js spike must independently prove host behavior.

