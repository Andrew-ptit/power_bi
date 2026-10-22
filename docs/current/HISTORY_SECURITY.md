# Persisted history security contract

These rules apply to the current workbook Custom XML implementation. Persisted metadata is untrusted after every open. Integrity hashes are not signatures or authorization tokens.

| ID | Required control |
|---|---|
| PC-SEC-001 | Exact namespace `urn:local-data-copilot:pq-problem-chain:v1`; zero parts is an empty state, one is valid, duplicates fail `PQPC_DUPLICATE_XML_PART`. Never silently select/delete a duplicate. |
| PC-SEC-002 | Reject DTD/entity declarations before parsing; never enable external resolution. |
| PC-SEC-003 | Require the exact XML wrapper, attributes and single Base64 payload child. Reject unexpected/mixed content and malformed Base64/UTF-8. XML byte equality is not a persistence oracle. |
| PC-SEC-004 | Reject duplicate JSON keys and non-finite numbers. Require canonical UTF-8 JSON with sorted keys and compact separators before computing hashes. |
| PC-SEC-005 | Recompute `historyHash` from the canonical payload. Anyone able to edit a workbook package can recompute it; it does not establish authenticity. |
| PC-SEC-006 | Recompute semantic `reviewHash` with the exact field exclusions defined in [Problem Chain](PROBLEM_CHAIN_SPEC.md). Do not change the hash basis during cleanup. |
| PC-SEC-007 | Persisted source-schema fingerprints use the declared inference policy and referenced schemas. Session data fingerprints are separate and detect source changes before runtime writes. |
| PC-SEC-008 | Enforce 1-50 revisions per chain and at most 2,097,152 canonical payload bytes before Base64. Check before planner calls and again before XML write; never prune silently. |
| PC-SEC-009 | Current persisted samples remain disabled: acknowledgement is null and `sampleStore` is empty. Do not add a sample-enabling workflow implicitly. |
| PC-SEC-010 | Validate the acyclic tree, one root per chain and valid HEAD. Derive tips; do not persist `branchTip` or `latestRevisionId`. |
| PC-SEC-011 | Never persist tokens, approval/preview/apply IDs, workbook bytes, result workbooks or runtime authority. Reserved `name`, `note`, `annotationUpdatedAt` and `runtimeSummary` accept only null. |
| PC-SEC-012 | Prompts, metadata, cells and error text are data. Re-run the authoritative current Typed graph/lineage/catalog/compiler validation after load; storage validity cannot authorize raw M. |
| PC-SEC-013 | Metadata travels with a saved workbook. The add-in does not Save; Save/Save As does not imply confidentiality. |
| PC-SEC-014 | History CAS/read-back detects observed conflicts but is not an atomic workbook transaction. Co-authoring is unsupported; do not claim it closes the read/write race. |

Mutation sequence: validate base history, prepare a detached candidate, re-read XML before write, persist, read back, and commit only the matching hash. After an uncertain commit, re-read the workbook; never automatically replay the POST. Unknown schema, invalid tree/hash, duplicate parts and limit violations block writes without overwriting the invalid history.

Log error codes, bounded sizes, dimensions, hashes and boolean checks. Never log XML/Base64, raw prompts/cells/samples, tokens or private temporary paths. Tests must retain independent canonical/hash/package oracles and malformed-input/recovery cases.
