# Refactor review ? 2026-10-21

Candidate code commit: 55bd442. Release gate status is maintained separately in ../releases/1.2.0.md.

## Method and limitations

Three implementation/verification agents and the root integrator reviewed separate ownership areas, then cross-reviewed the two code slices. The generated function-review-inventory.json indexes all 372 baseline functions including nested functions; 357 have an exact AST match somewhere in the canonical implementation. Static name matches are candidate callers/test references, not a resolved call graph or measured coverage. Human invariants below and differential/runtime tests provide the behavioral evidence.

## Responsibilities, side effects and retained oracles

| Area | Callers / decision | Side effects and protected invariant | Verification |
|---|---|---|---|
| sources CSV/XLSX | CLI, source UI, diagnostics; relocate existing parsing/profile functions | Local reads only; encoding/header/row-width limits, cached formula disclosure, dates and bounded preview retained | unit CSV/XLSX/advanced, fixture contracts, source workflow journeys |
| schema/fingerprint | Source orchestration and stale-input guards; retain pure comparison and streaming hashes | Fingerprint must reflect source changes while excluding only managed result sheets as allowed; no relaxed hashing | source-schema/fingerprint tests and cache/stale-source journeys |
| powerbi inventory/catalog | CLI and independent fixtures; relocate without behavioral redesign | Symlink/path checks, allowlisted PBIR versions, view-only/blocked status, full-file snapshot; no patch eligibility granted | PBIP/PBIR fixture contracts, TMDL runtime tests |
| powerbi planning | Structured proposal callers; retain dataclasses/pure policy functions | User approval and dependency graph remain explicit; no AI or patch side effects | planning unit tests |
| source web UI | Separate local-only UI; resource resolver change only | Temporary copies, token/host/body limits, private-path replacement; no Codex/PBIP dependency added | HTTP source upload/profile/error/recovery tests |
| coordinator runtime | Every HTTP operation; preserve existing lifecycle classes | Session TTL, independent execution slots, state lock and marked temp cleanup unchanged | runtime/session/HTTP race and expiry contracts |
| grouped endpoints | 31 route paths / 29 handler methods | Shared host/origin ? session ? cooldown/execution slot ? state lock boundary; same body limits, error codes and finalizers | AST equality of all original branch bodies + dispatcher negative and HTTP journey checks |
| Codex adapter/snapshot | Four planner runners | Shared subprocess flags, stdin, UTF8, no-window, timeout and limits retained; bounded metadata snapshot cannot grant runtime authority | schema mutation/preflight/error tests + separate live Codex gate |
| Excel/Advanced M | Fixture connector and PQ preview stores; relocate unchanged methods | Copy/temp isolation, explicit scope, source fingerprint, calculate/read-back; no implicit Save | fixture/Advanced HTTP tests, isolated Excel and real sideload gates |
| Typed model/validation | Store and history semantic checks | 15 operations, 10 recursive expression kinds, stable IDs, strict schema/dependency/type/flat-final-output gates; draft binding only mutates detached draft | 211 differential normalization cases; catalog/schema and blocker tests |
| Typed compiler | Normalized plans and diagnostic closure | Exact escaping/templates, topological order, source-order enforcement and cache key policy retained; indexed producer lookup | Baseline M byte equivalence for two independent synthetic planners, source-order on/off |
| Typed store | HTTP orchestration and history activation | Lock ownership, immutable revisions, preview/staging/approval/apply and bounded cache authority preserved; close differs from runtime invalidation | Typed, diagnostic, cache and HTTP recovery tests |
| history document/mutations | History store and semantic validators | Canonical hash fields, strict persisted schema, immutable detached candidates, IDs/timestamps; no commit/write authority in helpers | Independent XML/hash/security/package oracles and baseline schema bytes |
| history store | HTTP load/candidate/commit/checkout | CAS/generation/HEAD checks and read-back binding stay authoritative; old revisions survive branch/edit/delete as specified | tree/integrity/domain/HTTP stress and real isolated merge journey |

## Independent checks

- All five relocated schema files are byte-identical to the original code baseline.
- 211 valid/malformed operation cases matched baseline result or exception type/code/path/detail.
- Filter/add/sort and full-catalog plans normalized identically and compiled byte-identical M with source-order enforcement on/off.
- Fresh-process registry-first, history-first and legacy-first imports succeeded.
- Coordinator cross-review compared all 31 route branch bodies, guard sequence and exception/finalizer AST to baseline; no behavioral blocker found.
- Legacy module identity aliases retain existing import and subprocess monkeypatch seams. Endpoint-specific patches must target their canonical adapter module or injected runner.
- Direct compiler calls on malformed unvalidated duplicate/missing steps can expose different raw Python exceptions after indexing; production validators reject these inputs before compilation.

## Performance

Interleaved synthetic 50-step filter-chain benchmark (six alternating samples ? 200 compiles): median baseline 1.064776 ms, refactored 0.918552 ms, exact 3,836-character M unchanged. An earlier non-interleaved run was slower under concurrent workload. This is a noisy compiler microbenchmark; no Excel/Codex/end-to-end speedup or SLA claim is made.

## Tests and cleanup

354 original static test IDs are retained and mapped in ../../tests/case_migration.json. 19 independent storage/security/codec cases were promoted from spike support; 12 checks were added. No safety test was deleted without replacement. Advanced XLSX tests temporarily omitted by the migration script were restored before final verification; the earlier 355-case green run is invalid evidence. Required-ID discovery protection now detects missing retained tests before run_checks executes.

The removed spike directory is recoverable from the byte-exact baseline. Its reusable oracles/COM helper/Office.js test harness are retained in tests/support; historical reports moved to history-storage. Design artifacts and license remain available. Product helper binaries, certificates and personal workbooks were not cleaned.

## Cancelled metadata scope

Annotation/name/note editing, semantic/runtime diff and persisted runtime summary are cancelled. Reserved null fields retain their schema positions and hash participation. Non-null reserved metadata still fails closed with unsupported wording; no workbook migration or automatic Save was introduced.
