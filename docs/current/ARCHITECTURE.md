# Architecture and refactor decisions

Target release: 1.2.0. This is a behavior-preserving reorganization, with no storage migration or new Python runtime dependency.

## Boundaries

| Package | Responsibility | Side effects / protection |
|---|---|---|
| core | Input errors, bounded workbook snapshot contract, resource paths | No session state; resources resolved from one package/repository root |
| sources | CSV/XLSX profile, schema comparison, source fingerprint and import workflows | Reads local inputs; preserves row/encoding ambiguity gates and source hashes |
| powerbi | PBIP inventory, PBIR catalog, TMDL bridge, proposal contracts | Read-only; pinned bridge; static status never grants patch/runtime verification |
| coordinator | Composition, HTTP adapter groups, sessions, slots, temporary workspaces | Guard order remains host/origin ? session ? execution slot ? state lock; fail-closed limits |
| excel | Fixture plan and isolated connector | Explicit copy target, calculate/read-back, source unchanged |
| powerquery/typed | Closed operation catalog, validation, M compiler, runtime store | Pure validation/compiler separated from approval/cache/session authority |
| powerquery/history | Canonical documents/hashes and candidate/commit store | Immutable revision history, CAS, exact HEAD binding; no implicit Save |
| powerquery/advanced | Server-owned trusted-M policy and preview | Runtime on temporary export; separately confirmed values-only Apply |
| powerquery/diagnostics | Local bounded sampling and cache | Source fingerprint/version checks; samples remain bounded |
| adapters/codex | Planner-specific prompts/schemas with shared subprocess transport | Bounded opt-in input; schema preflight, timeout and failure mapping stay explicit |

Static assets remain in excel_addin/web. PowerShell helpers and the .NET bridge remain in tools. No database repository or dynamic plugin framework is introduced.

## Patterns applied

- Explicit HTTP dispatcher with grouped adapter handlers; domain stores remain application services. Transport helpers do not approve changes.
- Existing Protocol runner interfaces support dependency injection and independent fake/runtime implementations.
- Typed operation registry pairs real normalization/compiler handlers for the 15 allowed operations; expression kinds stay a closed 10-kind catalog.
- Pure history/document and Typed contracts remove mutual store dependencies. Stores retain locks and authority; runtime invalidation remains distinct from closing/clearing confirmed caches.
- Identity compatibility facades preserve the original flat imports and module-level monkeypatch boundaries. CLI/server module entrypoints remain supported.
- One resource resolver owns paths to JSON schemas, static assets and offline helper binaries. New canonical modules must not infer repository location using their own parent counts.

## Review decisions for stable modules

All baseline Python functions are indexed in the generated review inventory. Static caller matches are navigation hints, not proof of runtime reachability; behavioral evidence comes from retained tests/journeys.

CSV/XLSX parsing, schema comparison, PBIP/PBIR cataloging, TMDL fingerprint checks and proposal validation already have narrow responsibilities. They are relocated with behavior preserved instead of introducing a strategy class for each pure function. Source-only UI orchestration remains separate from PBIP/Codex orchestration to preserve its local-only boundary. Source fingerprints, defensive copies, immutable history and explicit stale checks are retained.

Compiler producer lookup now uses a per-compile map. Hoisted membership sets avoid repeated construction. Performance evidence is a synthetic compiler microbenchmark only; no Excel/Codex end-to-end speedup is claimed.

## Compatibility and cancelled scope

HTTP URLs, response/error contracts, API versions, schema/policy versions and canonical hash inputs remain stable. The legacy modules are supported adapters; implementation work belongs in canonical packages.

Name/note editing, semantic/runtime diff and persisted runtime summary are cancelled. Persisted name/note/annotationUpdatedAt/runtimeSummary fields remain required-null reserved fields: old workbook histories load without rewriting them. Non-null metadata remains unsupported and fails closed. This cleanup does not enable annotations, remove integrity tests or migrate stored hashes.

## Recovery and verification

Byte-exact recovery baseline: baseline/pre-1.2.0-byte-exact (4bdc2de); initial code inventory baseline: baseline/pre-1.2.0 (d9b6038). The byte-exact tag corrects Git line-ending conversion of fixture files; .gitattributes preserves manifest hashes on future checkouts. Use a separate worktree for inspection/recovery so the current workspace and user inputs remain untouched:

```powershell
git worktree add --detach ..\power_bi_baseline baseline/pre-1.2.0-byte-exact
```

No remote push occurs. Personal files/certificates/generated bridge outputs are outside source cleanup. Per-slice focused checks precede full regression, isolated runtime, live Codex and Office.js sideload gates; see the release report for exact-current results.

Legacy schema resource aliases: five flat-package JSON files are retained byte-identically to canonical schemas. They protect cached SCHEMA_PATH values in an already-running pre-refactor coordinator. New code uses core.resources/schema_path and schemas/; parity contracts prevent drift. This does not authorize restarting or terminating the user coordinator.
