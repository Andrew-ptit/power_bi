# Office.js autorun independent audit

## Status

**Audit complete; runtime gate passed after manual sideload.** This review is independent of the autorun implementer. A Node fake host, COM automation, package inspection, or a server-only test is not counted as real Excel Office.js runtime evidence.

## Evidence acceptance criteria

The real-runtime artifact must establish all of the following without containing Custom XML, Base64 payloads, prompts, notes, sample/cell values, workbook bytes, tokens, credentials, or absolute local paths:

- Excel hosted the task pane, `Office.HostType.Excel` was observed, and the `ExcelApi 1.5` runtime gate passed.
- Operations occurred in order: clean/inspect, add, get/parse, set Unicode, set near-limit, create duplicate, observe fail-closed duplicate state, cleanup, and final zero matching parts.
- Duplicate handling does not select, overwrite, or delete one arbitrary part before the explicit cleanup phase.
- Near-limit evidence reports canonical bytes from 2,093,056 through 2,097,152 inclusive and records sync/read-back duration.
- A read-only source sentinel is equal before and after every operation. Only the equality result/hash belongs in evidence; the sentinel value does not.
- The spike contains no call to `workbook.save`, `save()`, Save As automation, worksheet writes, or query/connection mutation.
- Cleanup is bounded to the spike namespace and the disposable Excel process/server/certificate or sideload state is accounted for.
- Fake-host tests and real Excel evidence use distinct status/artifact paths and cannot silently substitute for one another.

## Baseline findings — 2026-10-13 (Asia/Saigon)

| Check | Status | Evidence |
|---|---|---|
| Static no-auto-Save/source-sentinel contract | Pass | `npm test` reached the static and fake-host checks; `taskpane.js` contains no Save call and snapshots active-sheet A1 around operations. |
| Fake-host add/get/set/duplicate/cleanup | Pass, non-runtime only | The fake Office context exercised task-pane functions. This is explicitly not Excel runtime evidence. |
| Cross-oracle suite | **Fail** | `test_near_limit_javascript_document_passes_python_limits` was rejected because `sampleStore.syntheticTransportPadding` is not a SHA-256 content-hash key under the security contract. |
| Actual Excel Office.js autorun | Not yet available for audit | No runtime artifact had been produced at baseline. |
| Persistence through Save/reopen or Save As | Not run | Must remain manual/blocked because the add-in is forbidden to call Save. |

The baseline `npm test` result is therefore **Fail**, not a green Wave 0 signal. The implementer was notified to generate a schema-valid near-limit document before producing autorun evidence.

## Independent rerun — 2026-10-14 (Asia/Saigon)

### Defects found and disposition

1. **Pre-existing-history deletion — fixed before runtime use.** The first autorun implementation always called namespace-wide cleanup in `finally`. If `inspect-zero` failed because a workbook already contained Problem Chain history, that cleanup deleted the pre-existing part. The implementation now records the IDs created by the current autorun and deletes only those IDs. `test_autorun_existing_fake.js` independently starts with one valid pre-existing part, proves no add/delete occurred, and proves the posted run is `Fail` with `AUTORUN_INITIAL_STATE_NOT_EMPTY`.
2. **False privacy-test failure — fixed.** A string regex treated the legitimate code `PQPC_DUPLICATE_XML_PART` as leaked XML. The server test now walks JSON keys structurally and separately scans for secret sentinel content.
3. **Weak Pass evidence validation — fixed.** The evidence validator now requires the exact 8-step sequence, exact part-count transitions `0,1,1,1,1,2,2,0`, a 2 MiB-near payload in the accepted range, both duplicate block codes, exactly two autorun-created parts deleted, final zero parts, unchanged sentinel and every step passing.
4. **Normal manifest did not request autorun — fixed without modifying the manifest.** The isolated server can be started with `PQPC_SPIKE_AUTORUN=1`; only then it redirects `/taskpane.html` to `?autorun=1`. The normal/manual server path remains non-autorun.

### Measured automated evidence

| Command/check | Result | Measured duration / size |
|---|---|---|
| `npm test` in `officejs` | **Pass** | 0 failures; 6.822 s wall time |
| Fake-host autorun | Pass, non-runtime only | 8 steps, 39 fake `context.sync()` boundaries, 2,955-byte redacted evidence |
| Existing-history adversarial fake host | Pass, non-runtime only | Existing part retained byte-for-byte; autorun stops after inspect and owned cleanup |
| JavaScript/Python cross-oracle | **3/3 pass** | 1.190 s; near-limit validation 441.3 ms |
| Security + adversarial Python tests | **22/22 pass** | 11.056 s test time; 11.343 s wall time |
| Package-oracle unit tests without Excel COM | **5/5 pass** | 35 ms test time; 387.6 ms wall time |
| Near-limit codec microbenchmark, 5 runs | Pass | 2,093,056 canonical bytes; 2,790,987 XML bytes; build 25.7–29.2 ms (mean 27.0 ms); parse 54.1–102.2 ms (mean 73.9 ms) |
| Excel COM round-trip rerun in this audit | **Timed out / failed** | Hung at the COM Excel smoke for about 33 minutes. The one helper Excel PID and only the test-owned Python/PowerShell processes were terminated. This run is not counted as Pass. |

The 2.79 MiB XML transport is about 33.3% larger than its 2.09 MiB canonical JSON because of Base64. Codec CPU time is small in Node; the unresolved performance risk is real Office.js `context.sync()` latency and Excel persistence, which cannot be inferred from the fake host.

### Privacy and credibility review

- The POST body is allowlisted and capped at 32 KiB. It contains timings, booleans, counts, bounded error codes and canonical byte size; it rejects XML, Base64 payloads, prompts, notes, cells, formulas, history hashes, workbook bytes, tokens and unknown fields.
- Server request logs contain only HTTP method, route, status and elapsed milliseconds; task-pane POST errors do not include raw exception messages.
- `noSaveCalled` is a client assertion, so it is accepted only together with the independent static no-Save check. Similarly, the local evidence endpoint is not cryptographic attestation: another local process could forge a valid POST. Runtime evidence is credible only when correlated with the controlled sideload process, timestamps/PIDs and the disposable workbook.
- The A1 sentinel is a narrow mutation alarm, not proof that every cell, Table, query and connection is unchanged. Package semantic hashes and the manual disposable-workbook inspection remain required.

## Final status

| Gate | Status |
|---|---|
| Isolated JavaScript/schema/security/package-unit automation | **Pass** |
| Actual Excel Office.js add/get/set/delete autorun | **Pass — manually observed with strict redacted evidence** |
| Save, close/reopen, and Save As persistence | **Pass — package and hash read-back verified** |
| Co-authoring | **Unsupported by design in v1** |
| Product implementation gate | **Pass — user accepted Wave 0 closure on 2026-10-14** |

No fake-host result, COM package result, or self-posted evidence should be relabelled as an actual Excel Office.js runtime pass.

## Post-audit runtime evidence — 2026-10-14

The user manually opened the isolated sideloaded task pane in Excel 16.0.20430.20146. The strict evidence receiver accepted all eight runtime steps with ExcelApi 1.5, unchanged A1, the 2,093,056-byte canonical payload, duplicate fail-closed behavior and cleanup of exactly two run-owned parts. Save/reopen and Save As each retained one 1,230-byte canonical payload with history hash `sha256:7b70c3a09d9e7659f7d5a6be0344344867562bf6367d637925d93d2bc59021ff`. Package inspection found exactly one linked Custom XML part in each file, empty `sampleStore`, and the same workbook semantic hash as the original fixture.
