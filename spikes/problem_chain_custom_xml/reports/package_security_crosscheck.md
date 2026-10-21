# Problem Chain Wave 0 — package/security cross-check

## Control

| Field | Value |
|---|---|
| Reviewer | Independent cross-check agent |
| Run window | 2026-10-13 20:59–21:15 +07:00 |
| Repository | `C:\Users\COLAIG\Downloads\power_bi` |
| Python | 3.13.5 |
| Excel | 16.0 build 20430 |
| Scope | Existing `package_oracle/` and `security/` spike artifacts only |
| Product code changed | No |
| Overall status | **Automated cross-check passed after fixes**; Office.js/manual gate remains **Blocked / Not run** |

This review used independent adversarial inputs in addition to the implementers' tests. A COM/package pass is not Office.js sideload evidence.

## Results

| Area | Result | Evidence |
|---|---|---|
| Focused automated suite | **19 pass, 1 fail** | 20 tests completed in 12.594 s; wrapper wall time 13.611 s. The only failure was the workbook semantic snapshot oracle. |
| Source containment | **Pass** | Fixture SHA-256 remained `6e8ee702d1fab67cad03d180bfbae32396f189ff35bbc5c32437fbb5d44dfb96` across all COM cases. |
| Small Custom XML round trip | **Pass with oracle caveat** | History hash matched after Save/reopen and Save As; one namespace part remained; helper Excel process exited normally. File grew from 8,905 to about 13,582–13,584 bytes. |
| Duplicate namespace | **Pass** | Excel retained two distinct Custom XML part IDs in both working and Save As copies. Package oracle returned `PQPC_DUPLICATE_XML_PART`; source stayed unchanged; helper PID exited normally. |
| Near-2-MiB repeated payload | **Pass with cleanup warning** | Canonical hash round-tripped. On one run Excel did not exit within the helper's 5-second wait and was force-terminated; no residual PID remained. The repeated `x` payload compressed unrealistically to about 26.9 KiB. |
| Near-2-MiB high-entropy payload | **Pass** | 2,031,584 canonical bytes / 2,709,023 XML chars; COM Save/reopen/Save As took 19.831 s. Result workbook was 1,931,645 bytes, a 1,922,740-byte increase. Hash matched, source stayed unchanged, and PID exited without forced cleanup. |
| Full COM performance sample | **Observed** | Full small + duplicate + near-limit run took 43.166 s. Four helper-created Excel PIDs were observed serially, with peak working sets 208.4–229.5 MiB. Baseline Excel PIDs were excluded. No helper-created PID remained afterward. |
| Temp containment | **Pass** | No `pqpc-*` operation directory remained under system temp after completed runs. No Excel PID remained. |
| OOXML relationship graph | **Generated package pass** | Both working and Save As packages contained the workbook `customXml` relationship, `customXml/item1.xml`, its `customXmlProps` relationship, `itemProps1.xml`, and the required content type. |
| Semantic workbook content | **Values appear preserved; current oracle fails** | Independent resolved-cell diff found only `0.07` versus `7.0000000000000007E-2`; Excel also converted inline strings to shared strings. Formulas and Tables were unchanged. These are serialization differences, not value changes. |
| 50/2-MiB boundaries | **Pass** | 50 revisions accepted; 51 rejected with `PQPC_HISTORY_LIMIT`. Exactly 2,097,152 canonical bytes accepted; 2,097,153 rejected. |
| Malformed/DTD/hash/canonical JSON | **Pass** | DTD/entity, malformed wrapper/Base64, noncanonical JSON, duplicate JSON key representation, and history-hash tamper were rejected. |
| Samples disabled by default | **Pass** | Disabled policy requires null acknowledgement and empty `sampleStore`. |
| Enabled sample constraints | **Fail** | Validator accepted 21 rows, invalid content-hash keys, and duplicate identical sample content under different keys. The required 20×200 bound and content-hash deduplication are not implemented. |

## Findings requiring correction

### F1 — Semantic snapshot produces a false failure (high, release-gate reliability)

`semantic_workbook_snapshot()` compares OOXML storage representation. Excel legitimately rewrites `inlineStr` cells to shared-string indexes and may rewrite an equivalent number lexically. This caused the real COM smoke to fail even though an independent resolved-value comparison found no logical data change.

Required correction:

- Resolve shared-string indexes to text before comparison.
- Compare numeric cells numerically, not by raw `<v>` text.
- Continue comparing formulas, Table definitions and defined names structurally.

The assigned fixer is addressing shared-string/numeric normalization. The failed test must be rerun after that change.

### F2 — Enabled `sampleStore` is effectively unvalidated (high, privacy/size contract)

The validator checks only that `sampleStore` is an object. It does not enforce hash-key syntax/content, 20-row × 200-column limits, record shape, or deduplication by canonical content hash.

Required correction:

- Define and enforce the exact sample record schema.
- Recompute each content hash and reject mismatches.
- Reject more than 20 rows or 200 columns per referenced source.
- Reject identical canonical content stored under multiple keys.
- Retain the global 2-MiB check.

The assigned fixer is addressing this contract gap.

### F3 — Package oracle does not validate attachment relationships (medium, false-pass risk)

`inspect_problem_chain_parts()` scans every `customXml/itemN.xml` containing the namespace, including orphan parts not attached to the workbook. It does not verify the workbook relationship, the item's `customXmlProps` relationship, the datastore namespace declaration, or relationship targets. `package_part_delta()` checks names only, not relationship content.

Required correction:

- Traverse from `xl/_rels/workbook.xml.rels` Custom XML relationships.
- Validate target containment and the paired item properties relationship/content type.
- Reject missing, duplicate, orphaned or mismatched relationships.
- Add a negative oracle with an orphan namespace part and another with a broken relationship.

The real Excel-generated packages inspected in this run had a valid relationship graph; the gap is in the oracle coverage.

### F4 — Repeated-character size fixture understates storage cost (medium, performance evidence)

The existing near-limit case pads with repeated `x`, producing an approximately 26.9-KiB compressed workbook from a roughly 2-MiB canonical payload. It does not represent real prompts/metadata. The high-entropy cross-check produced a 1.93-MiB workbook and took 19.831 s.

Required correction:

- Keep the deterministic repeated case for boundary correctness.
- Add a deterministic high-entropy case for file-growth and latency evidence.
- Record both canonical size and compressed package delta.

### F5 — Excel cleanup needed forced termination intermittently (medium, lifecycle)

One near-limit run exceeded the current five-second exit wait and used the helper's PID-scoped forced cleanup. No residual process remained and other runs exited normally. This is safe containment but signals that large payload cleanup is timing-sensitive.

Required correction:

- Preserve PID-scoped cleanup; never kill unrelated Excel processes.
- Measure normal exit distribution and use a bounded wait/backoff suitable for the 2-MiB case.
- Continue reporting `cleanupForced`; do not hide it as a normal pass.

The assigned fixer is reviewing the cleanup wait.

## Commands and independent oracles

Focused suite:

```powershell
py -m unittest -v tests.test_problem_chain_custom_xml_package spikes.problem_chain_custom_xml.security.test_contract_validator
```

Full package/COM spike:

```powershell
py -m spikes.problem_chain_custom_xml.package_oracle.run_spike --fixture tests/fixtures_excel_mcp/excel_mcp_sales_input.xlsx --full
```

Independent in-memory Python oracles were also executed for:

- exact 50/51 revision and 2,097,152/2,097,153-byte boundaries;
- enabled sample overflow and duplicate-content attacks;
- duplicate JSON key representation;
- resolved shared-string/numeric cell comparison;
- workbook Custom XML relationship traversal;
- high-entropy 2,031,584-byte COM round trip;
- duplicate namespace preservation and rejection.

## Exit assessment

The first run could not close Wave 0 because F1/F2 failed and F3 left an oracle blind spot. The fix-verification section below supersedes those automated failures. Actual Office.js add/get/set/delete, close/reopen, Save As, near-2-MiB sync, unsaved warning and manual sideload evidence were not executed by this cross-check, and co-authoring remains explicitly unsupported. Therefore even the green automated rerun is COM/package evidence only.

## Fix verification — 2026-10-13 21:16–21:18 +07:00

The owners updated the isolated spike artifacts after the first findings. The independent reviewer then reran the original failing path and adversarial inputs:

- Focused suite: **22 pass, 0 fail, 0 skip** in 8.708 s (8.956 s wrapper wall time).
- F1 fixed: COM semantic snapshot now resolves shared strings and normalizes Excel numeric spellings; the formerly failing round-trip test passed.
- F2 fixed: independent 21-row and invalid-hash sample attacks now return `PQPC_DOCUMENT_INVALID`.
- F3 implementation fixed: the inspector now requires the workbook Custom XML relationship, properties relationship, content-type override and matching namespace declaration.
- F5 mitigation applied: PID-scoped cleanup wait increased from 5 to 15 seconds. The focused COM run reported successful cleanup. Excel activity from other concurrent Wave 0 agents prevented using a global process count as attribution; helper cleanup is judged from its captured PID/result only.

F4 remains a measurement-quality recommendation: keep the independently measured high-entropy case in release evidence or add it to the automated spike. This does not invalidate hash/limit correctness, but the repeated-character fixture alone must not be used to estimate real file growth or latency.

Accordingly, package/security automated evidence is now green. Overall Wave 0 remains **Blocked / Not run** until the actual Office.js/manual scenarios required by the acceptance matrix are completed.
