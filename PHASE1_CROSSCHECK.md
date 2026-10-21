# Problem Chain Phase 1 — Independent Cross-check

Date: 2026-10-15 (Asia/Saigon)  
Scope: domain model, strict continuation, HTTP coordinator bridge, task-pane Custom XML CAS, and Typed preview authority.  
Reviewer ownership: `tests/test_problem_chain_phase1_crosscheck.py` and this report only.

## Result

Automated independent cross-check: **Pass**.

- Focused integration regression: 55 passed, 0 failed, 0 skipped in 8.818 s (9.199 s wall).
- Independent cross-check module: 19 passed, 0 failed.
- Task-pane VM oracle: 11 API calls and 32 Office.js `context.sync()` boundaries.
- Synthetic loopback HTTP oracle: 24 requests; min 1.44 ms, median 8.21 ms, p95 35.47 ms, max 36.63 ms.
- Continuation Structured Outputs schema: 44,011 bytes; SHA-256 `2683C1618A6DA3EDB6DEE1BA9D3B5F80922DB2076FCE9F537F119CE7E91E8BF1`.
- No product manifest change was part of this review.

These are deterministic/fake-runner measurements. They do not measure live Codex latency, real Excel refresh latency, or a new manual sideload of the integrated Phase 1 product UI.

## Independent coverage

- Python/Python-independent canonical UTF-8 JSON hashes agree.
- `reviewHash` includes semantics and excludes identity, annotation, and runtime evidence.
- Root HTTP creation uses the server Typed planner; a client `typedPlan`/raw-M replacement is ignored.
- Continuation invokes only a strict `changes[]` planner and preserves the parent revision byte-for-byte.
- A continuation cannot silently replace the full pipeline or discard stable downstream steps.
- Inserted `clientRef` values resolve only in reference-bearing fields; matching descriptions/literals remain unchanged.
- Every change variant rejects missing and unknown fields.
- Stale CAS and semantically tampered documents fail before planner execution.
- Concurrent candidate commit cannot overwrite newer committed history.
- Checkout preserves descendants and Phase 1 branch creation is blocked.
- Revision 51 and a history that cannot fit another revision are blocked before planner execution.
- Raw M, sample rows, URL/path/credential metadata, and forged runtime authority are rejected.
- A loaded workbook history does not restore preview, approval, apply, or session authority.
- Preview accepts only a committed head; checkout invalidates an approval for the previous head.
- A Table moved to another sheet remains the same workbook-unique source when its name/schema are unchanged.
- A Table schema change blocks preview while history remains loadable.
- UsedRange identity remains sheet-bound.
- Duplicate Custom XML, hash/payload CAS mismatch, and commit response mismatch fail closed.
- Problem Chain persistence calls Custom XML only: no `workbook.save` and no worksheet cell writes.
- ExcelApi below 1.5 does not call the Custom XML API and leaves session-only Typed Steps available.

## Defects found during cross-review and disposition

1. **Continuation UI sent a full `typedPlan`.** This conflicted with the strict delta contract and would make Problem 2 fail. Fixed: continuation sends document/base revision/workbook/source only.
2. **Client reference resolution rewrote arbitrary matching strings.** A description or literal equal to a `clientRef` could silently change to a generated step ID. Fixed: resolution is path-aware and limited to references.
3. **Unknown fields in `changes[]` were accepted.** Fixed: exact required/allowed key sets are enforced per change type.
4. **Custom XML CAS compared only the wrapper hash.** Fixed: task pane compares both the hash and canonical payload against the in-memory base.
5. **Hydration could retain session runtime authority.** Fixed: load/rehydrate explicitly clears preview and approval.
6. **Table matching used a sheet-sensitive locator.** This conflicted with workbook-unique Table identity. Fixed and independently verified by moving the Table between sheets.

## Commands

```text
py -m unittest tests.test_problem_chain_phase1_crosscheck -v
node tests/taskpane_problem_chain.js
py -m unittest tests.test_problem_chain_phase1 tests.test_problem_chain_phase1_crosscheck tests.test_taskpane_js tests.test_excel_addin_server tests.test_pq_typed_api -v
```

## Release evidence update — 2026-10-16

- Live Codex continuation E2E **passed** on 2026-10-15 at about 22:12 (+07:00): 11,610.3 ms, two revisions, two steps, correct final output and a compiled M hash. A separate strict-output call took 13,191.8 ms. CLI version: `codex-cli 0.145.0-alpha.27`. Schema SHA-256 matches the 44,011-byte schema above. The exact shell command was not retained, so this is measured runtime evidence but not a fully reproducible command transcript.
- A near-2 MiB task-pane fake-host exercise took about **2.3 s CPU time**. This is a local UI/codec cost, not Excel Office.js sync latency or a production throughput benchmark. The 50-revision/2-MiB caps remain enforced.
- The first full Python regression attempt reached 265 tests but did not close the gate: an Excel COM contention timeout and one independent QA test typo occurred. The typo was corrected; a clean full rerun is pending root integration evidence. Neither issue is counted as a passing test.
- A later focused regression after integration fixes passed **73/73** in **20.468 s**. This does not replace the full suite or manual Excel gate.
- Integrated Phase 1 manual Office.js sideload is **Not run/Blocked** because the native computer-control pipe was unavailable in this run. Wave 0 Excel Custom XML evidence covers the storage primitive, not the new end-to-end Phase 1 UI.

## Manual-edit completion and adversarial review — 2026-10-16

- Cross-review found that the approved Phase 1 spec required manual Typed edits in history, while the initial UI blocked them. The new `/api/pq/v2/problem-chains/revisions` path prepares add/edit/delete/reorder/set-final as a `manualEdit` candidate. The task pane uses the same XML CAS, read-back and commit path; the standalone Typed revision API remains blocked while a chain is active.
- Independent QA found that previewing a committed revision with a deleted producer could raise an uncaught `KeyError` and close the HTTP connection. The server now checks the committed head's deterministic blocker before compile or Excel; the adversarial case returns `PQV2_DEPENDENCY_INVALID` with zero Excel runner calls.
- Independent cross-check: **34/34** in **7.960 s**. Combined domain/cross-check: **55/55** in **8.395 s**. Root focused API/UI integration: **75/75** in **16.301 s**. UI fake-host: **22 API calls, 57 mocked Office.js syncs**, pass. Loopback HTTP sample over 91 calls: median **9.37 ms**, p95 **30.24 ms**, max **39.96 ms**. Candidate preparation benchmark: 500 candidates, mean **3.820 ms**; pending mutations capped at 5.
- These measurements exclude live Excel and do not prove integrated sideload performance. The first two full Python suite attempts were not clean: the Excel COM smoke timed out, although that exact smoke passed in isolation in **36.016 s**. A post-fix full suite was started, but its session result was not retained across the interrupted turn; it is **unverified**, not a pass. The integrated manual Office.js gate remains Not run.

## Remaining release evidence

- Integrated Office.js sideload should verify root → continuation → Save/reopen → checkout → preview/head block in real Excel.
- The Wave 0 Custom XML runtime evidence remains relevant to storage, but it is not a manual acceptance run of the integrated Phase 1 UI.
- Co-authoring remains unsupported by design.

## Full regression follow-up — 2026-10-17

- `py -m unittest discover -s tests -v` completed with **282 tests, 0 failures, 1 environmental skip** in **394.047 s** on Python 3.13.5. The previously flaky Excel COM smoke passed in this run. The user subsequently reported that the Phase 1 workbook workflow succeeded; this is user-reported UAT, not a retained screenshot-level independent sideload trace.
- Phase 1.1 adds only session-memory Preview display caching. Focused validation on 2026-10-17: `node --check pbip_assistant/excel_addin/taskpane.js`, `node tests/taskpane_problem_chain.js`, and `py -m unittest tests.test_taskpane_js tests.test_excel_addin_server tests.test_problem_chain_phase1 tests.test_problem_chain_phase1_crosscheck -q` passed (73 tests, 0 failures, 14.576 s). The JS fake-host covered six-entry FIFO eviction, revisit with zero API/Excel calls, disabled approval, workbook/session invalidation and exclusion from persisted history. A manual task-pane cache check remains open; these automated checks do not prove the Excel UI behavior.

2026-10-17 follow-up: the versioned-cache/staging revision changed the behavior covered by the earlier evidence. `dataVersion` now marks old results stale without deleting them, Preview remains staging, and cache promotion waits for successful Confirm/write/read-back. Tests and Excel smoke were **not rerun** for this revision at the user's request. The earlier pass counts must not be used as release evidence for the revised behavior; manual sideload is also pending.

