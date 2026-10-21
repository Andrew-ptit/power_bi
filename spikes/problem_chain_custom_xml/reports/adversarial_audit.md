# Problem Chain Wave 0 — adversarial audit

## Control

| Field | Value |
|---|---|
| Date/time | 2026-10-13 21:11 +07:00 |
| Role | Independent adversarial QA |
| Scope | Wave 0 Custom XML storage/package spike only |
| Excel observed | 16.0 build 20430 |
| Fixture SHA-256 | `6E8EE702D1FAB67CAD03D180BFBAE32396F189FF35BBC5C32437FBB5D44DFB96` |
| Overall status | **Failed — two contract blockers; Office.js manual gate not run** |

Passing this audit would not prove Office.js persistence or co-authoring safety. No product implementation was inspected as complete.

## Independent results

Command:

```powershell
py -m unittest tests.test_problem_chain_wave0_adversarial -v
```

Measured result: **6 run, 4 pass, 2 fail, 0 skip in 20.476 s**.

| Area | Result | Independent observation |
|---|---|---|
| Canonical JSON size | Pass | Exactly 2,097,152 bytes accepted; 2,097,153 bytes rejected with `PQPC_HISTORY_LIMIT`. |
| Forbidden derived fields | Pass | Nested `branchTip` and `latestRevisionId` rejected at arbitrary depth. |
| DTD/entity | Pass | Mixed-case and newline-obfuscated `DOCTYPE`/`ENTITY` variants rejected before parse. |
| OOXML wiring | Pass | COM-created part has matching `itemProps`, `customXmlProps` relationship and `[Content_Types].xml` override in working and Save As files. |
| Source fixture preservation | Pass | Original fixture SHA-256 unchanged after copy/save/reopen/Save As test. |
| Default sample privacy | **Fail** | `sources[].sampleRows` is accepted while sample persistence is disabled. The sentinel is present in decoded canonical JSON even though it is hidden by Base64 in raw XML. |
| Opt-in sample validation | **Fail** | `sampleStore` accepts a non-SHA key and 21 rows; content-hash shape, dedup contract and 20×200 bounds are not enforced. |

The regression tests for both failed cases intentionally remain red until the validator owner fixes the contract. They must not be converted to tests that merely document acceptance.

## Cross-check of existing evidence

The existing combined Wave 0 tests initially reported **20 run, 19 pass, 1 fail in 19.466 s**. The failure was `excelPidExited == false`. Later runs left no new Excel process, so this is an intermittent cleanup/timing defect rather than proof of a permanent orphan; it still prevents a reliable green gate.

Two subsequent isolated COM runs failed the semantic preservation assertion in 10.817 s and 14.407 s. Excel rewrote inline strings to shared-string references. `semantic_workbook_snapshot` currently compares the storage representation (`inlineStr` versus `s` + index) rather than resolving both to the same cell value. This is an oracle false negative: it cannot currently distinguish harmless serialization churn from a real value change. It must be fixed before its “source semantics preserved” claim is trusted.

Raw XML byte equality was not used. The independent test validates decoded canonical JSON and `historyHash`, so Excel's XML declaration/whitespace normalization does not create a false failure.

## Remaining false-green risks

| Risk | Status | Required closure |
|---|---|---|
| Office.js `customXmlParts` add/get/set/delete | **Not run** | Manual task-pane sideload on ExcelApi 1.5+ remains mandatory. COM is not substitute evidence. |
| Payload near 2 MiB through Office.js | **Not run** | Measure sync/read-back latency and memory in the manual spike. |
| Save/reopen and Save As through Office.js | **Not run** | Verify canonical payload after real Excel save cycles. |
| Co-authoring race | **Unsupported by design** | Do not promote exploratory two-client behavior to supported status. |
| Symlink/reparse containment | **Not established** | The COM spike checks `.xlsx` extension and adjacent lexical paths but does not resolve final reparse targets. Keep it restricted to disposable trusted temp copies; production temp manager needs its existing containment oracle. |
| Duplicate namespace package validity | Partial | Direct duplicate detection passes, but the synthetic duplicate fixture lacks full Excel-generated relationships; Office.js must prove the real 0/1/>1 namespace behavior. |
| Process cleanup | **Flaky** | Run repeated COM/Office.js cycles; require zero newly created Excel PIDs and record forced cleanup separately. |

## Release decision

Wave 0 is **Failed/Blocked**, not Complete. Minimum recheck sequence:

1. Make source descriptors strict so values/sample rows cannot enter persisted schema metadata.
2. Define and validate the `sampleStore` hash/value schema, 20×200 limit and dedup rule.
3. Resolve shared strings and normalize equivalent cell representations in the package semantic oracle.
4. Stabilize PID cleanup and run at least five sequential cycles with zero residual newly created Excel processes.
5. Re-run this adversarial suite unchanged, then complete the manual Office.js sideload gate.

