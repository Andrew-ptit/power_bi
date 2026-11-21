# Excel add-in runbook

The task pane has two tabs: Assistant and PQ_Code-M. Use synthetic copies for verification. Do not test against an open user workbook. Unit/API/fake-host evidence does not replace a live Excel journey.

## Setup

Windows, Excel Desktop and Python are required for the add-in. Assistant values-only writing requires ExcelApi 1.9 (checked before consuming approval). Codex CLI authentication is needed only for an actual planning request. Python runtime remains standard-library and offline except for explicitly requested Codex work.

From the repository root:

```powershell
.\tools\excel_addin\setup-dev.ps1 -Trust
py -m pbip_assistant.excel_addin_server
```

Review the certificate source before trusting it. Keep private keys in `tools/excel_addin/.certs/` private. The coordinator prints its selected localhost port (3079 down to 3072) and synchronizes the manifest catalog with SHA-256 verification. Follow the existing Office tenant sideload/catalog policy using `tools/excel_addin/manifest.xml`; preserve unrelated catalog files and certificates. Open the printed task-pane URL once if a trusted local certificate is needed, then reopen the pane.

## Three separate execution paths

| Path | Current scope and approval boundary |
|---|---|
| Codex advice compatibility API | `/api/excel/analyze` remains a bounded prompt/sample API for existing callers. The old formula advice/copy/apply cards are absent from the Assistant tab. An AI suggestion does not authorize writing. |
| Typed / Problem Chain in PQ_Code-M | Closed 15-operation/10-expression catalog, immutable revisions, HEAD/CAS, temporary runtime Preview, explicit approval/Confirm, cache and checkout guards. Advanced M remains a separate trusted mode; its verification is deferred. Preview may create a marked values-only sheet; separate explicit Apply may replace only the exact previewed source values. No Save, backup or rollback promise. |
| Assistant v2 | Eight cards: workbook, sources, request, understanding, A/B plans, frozen Spec, write, result/Record. Codex authors validated plans from bounded samples; the local engine computes both branches from the same full snapshot. Approval binds the exact Spec/preview/digest and is consumed once. Only a new result sheet is written, followed by full values/marker/formula read-back. No automatic retry after a consumed or unknown write. |

## Assistant v2 synthetic journey

1. Use the committed synthetic source fixtures under `tests/fixtures/assistant/tp-fin/source` or `tp-sales/source`. Create a disposable workbook copy for actual UI testing; never open private data as a fixture.
2. Bind the source root, add sources and select actual Tables/usedRanges in the navigator. Resolve CSV delimiter/encoding/header ambiguity and duplicate names before proceeding.
3. Load deterministic samples to understand, enter the request and answer measured questions. Before understanding, selected workbook sources are read again. Discover compares only its previously bound sample and dimensions; compute compares every bound row. A failed read or changed hash clears stale authority.
4. Review the disclosure and explicitly agree before creating two Codex plans. At most 20 sample rows across sources plus the request/descriptive schema are sent; no full workbook or local path is sent to Codex.
5. Read all selected source data, compute A/B, and inspect each preview, timing, reconciliation and available comparable delta. A hard schema/security/dependency/reconciliation blocker cannot be overridden. If only the independent control total is unavailable, acknowledge that separately; labels remain unverified.
6. Choose a branch, freeze the exact Spec and tick the write approval. A restored approval must be reticked. Write the new server-named sheet and verify the complete result and marker. Decimal numbers are deliberately written as Text to preserve every digit. Source sheets stay unchanged; no Save is issued.
7. Create/download the full Decision Record. Read the workbook metadata before saving it, so the observed metadata-node hash pins CAS. The Custom XML node has its own integrity hash; its `recordHash` is a separate reference to the full JSON record. A metadata-only reopen cannot reverify the full record or source freshness. Reload all sources to compare the current full snapshot. Metadata persistence and read-back still do not Save the workbook.

Input bounds: 100,000 rows per source; planning accepts 200 input columns; results/intermediates accept 256 columns; at most 20 plan steps. The values writer accepts at most 400,000 cells. The UI shows at most 200 result rows; reconciliation uses the full private result. A/B result caching is bounded and policy checks are recomputed. Six catalog join kinds preserve Typed nested joins until expansion. CSV/folder/range plans use logical table aliases; directly exporting their compiled M into an unrelated workbook does not automatically create those aliases.

## Semantic limits

`parityChecked: none` means local results have not been verified against Power Query on this machine. It is not a runtime or business-logic verification label.

| Topic | Local executor contract |
|---|---|
| Numbers | Fixed Decimal context, retained as decimal strings through writing; no silent float conversion. Numeric expressions require actual numeric values; explicit changeTypes handles text conversion. |
| Null aggregates | Sum/average/min/max ignore null inputs; empty/all-null inputs produce null. Division by zero follows the explicitly declared error/null/zero policy. |
| Text | Ordinal, case-sensitive comparisons; locale-dependent collation can differ from Power Query. |
| Types and dates | Invalid date conversion becomes null with a warning. Conversion cultures are bounded to invariant, en-US, en-GB, vi-VN, de-DE and fr-FR. Temporal sort keys are chronological. |
| Distinct and sort | Distinct preserves the first row; sort is stable. Power Query does not generally promise those row choices/orderings. |
| Joins | Six kinds, deterministic input ordering and nested tables before expansion. Every join's fan-out is checked against declared policy, including empty-left joins. An unresolved nested final output is rejected. |
| Control total / A-B delta | Independent supported source/filter lineage is required. Ambiguous complex join/append measure lineage is reported unavailable. A delta is shown only when both branches prove a comparable source basis; absence is not a zero. |

## Automated checks and evidence

```powershell
py tools/run_checks.py fast
py tools/run_checks.py runtime
$env:PQPC_LIVE_CODEX='1'
py tools/run_checks.py codex
```

For isolated backend smoke, use a dedicated coordinator with an injected synthetic planner, or explicitly authorize actual Codex planning. Do not run reset-based smoke against a coordinator serving a working pane.

```powershell
powershell.exe -NoProfile -File tools/assistant_flow_smoke.ps1 -BaseUrl http://127.0.0.1:<PORT> -Scenario tp-fin
powershell.exe -NoProfile -File tools/assistant_flow_smoke.ps1 -BaseUrl http://127.0.0.1:<PORT> -Scenario tp-sales
```

The default stop is Record. `-StopAfter understand` avoids planning; later stages invoke the configured planner. Full backend smoke uses 13 POSTs for 11 logical routes: compute re-ingest and verified receipt reuse existing routes. `SYNTHETICRECEIPT` is intentional: the script does not open/write/save Excel and cannot prove Office.js writing. Repeat fixture runs must retain identical hashes and unchanged source bytes. An empty root must exit 1.

Actual slice evidence: real Codex planning passed once in 19.560 s (A=12, B=15, each 1x1). Runtime parity was attempted but blocked after 60.319 s by `PARITY_FIXTURE_TIMEOUT` at `Workbooks.Add(-4167)`; owned Excel processes were cleaned. No dimensions/fingerprints were obtained. Assistant v2 live Office.js writing and six-join runtime parity are not run. See `docs/current/CURRENT_STATUS.md` for exact gate/revision evidence and current qualification limits.

Stop only the coordinator started for this run using Ctrl+C, remove only this run's sideload registration and disposable fixtures, and preserve unrelated add-ins/certificates. Do not use broad certificate cleanup commands.
