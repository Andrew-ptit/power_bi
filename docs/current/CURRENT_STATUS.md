# Current implementation status

Updated: 2026-10-22 (Asia/Saigon). This page is a current status summary; historical reports are available through Git.

## Code and architecture

Canonical modules are grouped by source processing, Power BI, Excel, Typed Power Query, history and diagnostics. HTTP endpoint adapters, a closed operation registry, injected runner protocols, shared subprocess transport and compatibility facades are implemented. See [architecture](ARCHITECTURE.md) for ownership and remaining boundaries.

Source fingerprints now resolve referenced styles by content so importing a result sheet does not invalidate unchanged source data. Changes to referenced source cell/row/column formatting still invalidate the fingerprint. Canonical persisted history/schema/hash fields are unchanged.

This is a maintainable modular foundation, not a claim that every function or end-to-end path is fully optimized. Large Typed/history stores and task-pane orchestration remain candidates for smaller internal services. Compiler lookup uses maps; runtime Excel/Codex latency has no demonstrated overall improvement.

## Verification

| Check | Current result |
|---|---|
| `py tools/run_checks.py fast`, current cleanup with product base `8820cfc` | 375 run, 373 pass, 0 failure/error, 2 skip; 60.591 s |
| Fingerprint/cache/Typed/diagnostics/history focused checks | 64 pass, 0 failure/skip; 4.446 s |
| Real Office.js root and child commit/Preview/Confirm before the fingerprint fix | Completed on a synthetic workbook; root 4 rows x 10 columns, child 2 rows x 10 columns; source preserved |
| Real cache-hit/recovery journey after the fingerprint fix | Not completed; computer control was stopped with Escape before the fresh run |
| Advanced M | Deferred at the user's request; its current implementation remains present |
| Exact-current full regression/live Codex/release qualification | Pending |

The two fast skips are unavailable symlink privilege and an absent optional private CSV. Simulation/unit checks are not a completed live UI journey.

## Version and scope

Application/npm metadata remains 0.1.0 and Office manifest 1.1.0.0. The target application release is 1.2.0 with manifest 1.2.0.0; it has not been issued. Version changes wait for the required exact-current gates. API/schema/spec versions are independent.

Annotation editing, semantic/runtime diff and persisted runtime summaries are outside the product scope. Reserved persisted metadata fields accept only null, preserving workbook history compatibility. MCP/pilot backlog and unsupported PBIP patching are not completed capabilities.
