# Problem Chain Custom XML — Wave 0 acceptance matrix

Status vocabulary is `Pass`, `Fail`, `Blocked`, `Not run`. A mock, skip, timeout, auth/network failure or COM-only result cannot close an Office.js gate.

| ID | Scenario and oracle | Expected result | Automation |
|---|---|---|---|
| PC-X-001 | Host capability check `Office.context.requirements.isSetSupported("ExcelApi", "1.5")` | Unsupported host never calls `customXmlParts`; Typed session mode remains available | Office.js manual/integration |
| PC-X-002 | No matching namespace part | Load returns empty chain state | Office.js + Python |
| PC-X-003 | One valid part containing Vietnamese Unicode | Canonical payload and hashes round-trip exactly | Office.js + Python |
| PC-X-004 | Two matching namespace parts | `PQPC_DUPLICATE_XML_PART`; neither part changed/deleted | Office.js + Python |
| PC-X-005 | DTD, internal or external entity | `PQPC_DOCUMENT_INVALID` before entity resolution | Python negative |
| PC-X-006 | Wrong root, namespace, attribute, encoding or extra child | Fail closed; XML is not overwritten | Python negative |
| PC-X-007 | Malformed Base64, invalid UTF-8/JSON, duplicate/noncanonical JSON key representation | `PQPC_DOCUMENT_INVALID` | Python plus JS golden vector |
| PC-X-008 | Alter JSON without updating hashes; alter only wrapper hash | `PQPC_HASH_MISMATCH` | Python negative |
| PC-X-009 | `name`, `note` or runtime summary changes | `historyHash` changes; `reviewHash` is unchanged | Python golden vector |
| PC-X-010 | Prompt/source/steps/final output changes | Old `reviewHash` is rejected | Python negative |
| PC-X-011 | Table sheet locator/IDs/count/sample changes only | Schema fingerprint unchanged | Python golden vector |
| PC-X-012 | Table name, usedRange sheet/header, column name/order/type changes | Schema fingerprint changes | Python golden vector |
| PC-X-013 | Duplicate IDs, missing parent, cycle, multiple roots or missing head | `PQPC_DOCUMENT_INVALID` | Python negative |
| PC-X-014 | 50 revisions and canonical payload exactly ≤2 MiB | Accepted | Python boundary |
| PC-X-015 | 51 revisions or canonical payload >2 MiB | `PQPC_HISTORY_LIMIT`; zero planner/write calls | Python + server integration |
| PC-X-016 | Default sample policy with a cell sentinel | Empty `sampleStore`; sentinel absent unless it was deliberately typed in prompt/note | Python + OOXML inspection |
| PC-X-017 | Enable samples without warning acknowledgement | Reject mutation | Python/UI negative |
| PC-X-018 | Enable samples with acknowledgement, 20×200 bound and deduplication | Accepted; data-sharing warning visible; bytes count toward 2 MiB | UI/server integration |
| PC-X-019 | Persist preview/approval/apply/session token/workbook bytes | Reject document | Python negative |
| PC-X-020 | Add, get, set and delete through actual Excel Office.js | Read-back canonical document matches; source cells/Table/query unchanged | Manual sideload required |
| PC-X-021 | Save, close and reopen `.xlsx` after XML mutation | History returns only if workbook was saved; add-in never calls Save | Manual sideload required |
| PC-X-022 | Save As `.xlsx` | Chain/head copy; runtime approval absent; original/copy later diverge | Manual sideload required |
| PC-X-023 | Save As CSV/non-metadata format | Warning shown; no persistence promise | Manual sideload required |
| PC-X-024 | Payload close to 2 MiB through Office.js | Set/sync/read-back succeeds within measured time or gate is `Blocked` with evidence | Manual sideload required |
| PC-X-025 | OOXML before/after comparison | Only expected Custom XML package relationships/parts change; source semantic hash unchanged | Package oracle |
| PC-X-026 | Mutation sees changed `baseHistoryHash` before write | `PQPC_HISTORY_CONFLICT`; zero writes | JS/server race test |
| PC-X-027 | XML write succeeds but commit/network fails | No rollback/retry; reload hydrates workbook XML as truth | JS/server fault test |
| PC-X-028 | Two OneDrive/SharePoint clients edit from same base | Observed behavior documented; feature remains `Unsupported` regardless of apparent success | Exploratory manual |
| PC-X-029 | Persisted prompt/cell contains planner-injection text or `Web.Contents` | Treated as data; current Typed validator blocks raw M/connector smuggling | Server integration |
| PC-X-030 | Log capture with prompt/cell/token/XML/Base64/temp-path sentinels | Logs contain none of the sentinels | Integration security test |

## Exit rule

Wave 0 may be reported complete only when all Python contract cases pass and PC-X-020 through PC-X-025 have real Office.js/manual evidence. PC-X-028 remains explicitly `Unsupported`; it is an observation, not a release gate to claim co-authoring support. Any unrun manual Office.js case keeps product implementation approval `Blocked`, even if COM and package tests pass.

