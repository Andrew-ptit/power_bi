# Problem Chain Phase 1 — independent cross-check

Date: 2026-10-16 (+07:00)  
Reviewer: independent QA agent  
Scope: domain/API/task-pane contract, including the Phase 1 manual-edit completion  
Excluded: Excel COM, live Excel sideload, full repository regression

## Result

Focused independent QA is **Pass** after one release-blocking defect was found and fixed.

| Gate | Result | Independent evidence |
|---|---|---|
| Canonical/review/history hashes | Pass | Independent UTF-8 canonical JSON/SHA-256 oracle agrees with product output; annotations/runtime/identity remain outside `reviewHash` while semantic fields change it. |
| Immutable linear history | Pass | Parent revision remains deep-equal across continuation, checkout and manual edit; random child IDs and single-root/no-cycle/no-second-child rules are enforced. |
| CAS and commit boundary | Pass | Stale history/read-back hashes fail closed; candidate remains non-authoritative before Custom XML commit; failed read-back does not silently consume/replay the mutation. |
| Manual add/edit/delete/reorder route | Pass | Active chains use `/api/pq/v2/problem-chains/revisions`; legacy `/api/pq/v2/revisions` returns `PQPC_HEAD_MISMATCH`. |
| Runtime authority | Pass | Candidate revision cannot preview/approve before commit; commit invalidates old preview/approval; only the committed HEAD can preview. |
| Invalid manual graph | Pass | Delete-producer and dependency-breaking reorder persist as deterministic blocked `manualEdit` revisions, cannot compile/preview/approve/apply, and invoke zero Excel runner calls. |
| Limits/security | Pass | 50 revisions and near-2 MiB reject before planner; raw M, samples, URL/path/credential and unknown fields fail closed. |
| Schema/data separation | Pass | Table locator/runtime counts do not alter schema fingerprint; column/type drift does; independent workbook value mutation alters runtime fingerprint. |
| Session/rehydration | Pass | Rehydrate restores metadata only; approval/preview/session authority is absent and session expiry clears active runtime state. |
| UI fail-closed behavior | Pass | Editor closes only after persistence succeeds; ambiguous commit disables add/preview/approval; repair cannot bypass manual revision workflow. |

## Defect found by cross-review

The first manual-edit build allowed a blocked delete-producer revision to be committed, but preview then called `compile_m` before inspecting `validationAtCreation`. A missing producer caused an uncaught `KeyError`, closed the HTTP connection and could stall the user flow.

The server now checks the committed revision's deterministic validation evidence before activation/compile, returns the first persisted issue (`PQV2_DEPENDENCY_INVALID` in this case), and makes zero Excel calls. The adversarial delete-producer and reorder tests pass after the fix.

## Commands and measurements

Environment: Python 3.13.5; Node v24.13.1.

```text
py -m unittest tests.test_problem_chain_phase1_crosscheck -v
34 tests, 34 pass, 0 fail, 0 error, 7.960 s

node tests/taskpane_problem_chain.js
Pass; 22 mocked API calls; 57 mocked Office context.sync boundaries

py -m unittest tests.test_problem_chain_phase1 tests.test_problem_chain_phase1_crosscheck -q
55 tests, 55 pass, 0 fail, 0 error, 8.395 s
```

Independent HTTP timing run over 91 loopback calls:

| Metric | Value |
|---|---:|
| Minimum | 1.32 ms |
| Median (p50) | 9.37 ms |
| p95 | 30.24 ms |
| Maximum | 39.96 ms |
| Mean | 10.98 ms |
| Complete cross-check wall time | 8,403.3 ms |

These numbers measure coordinator/domain/fake-runner behavior, not real Codex or Excel runtime latency.

## Remaining gates

- This review deliberately did not run Excel COM, live Office.js sideload or the full repository suite.
- Problem Chain repair-patch application remains unavailable in Phase 1 and is explicitly blocked in the UI; users must make a typed manual edit.
- Phase 2 branching and Phase 3 annotation/runtime diff remain outside this review.

