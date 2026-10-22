# Project guidance

## Sources of truth and structure

- Product contracts and FR/AC IDs: `docs/current/SPEC.md`, `EXCEL_MCP_SPEC.md`, `PQ_CODE_M_SPEC.md`, `PROBLEM_CHAIN_SPEC.md` and `TYPED_STEP_DIAGNOSTICS_SPEC.md`. `BPMN_MODEL.md` owns process/task IDs. Draft requirements do not imply completed capabilities.
- `docs/current/CURRENT_STATUS.md` owns current verification/release status; `ARCHITECTURE.md` owns module boundaries. Historical reports belong in Git history, not duplicate folders in the current tree.
- Canonical product modules: `core`, `sources`, `powerbi`, `coordinator`, `excel`, `powerquery/{typed,history,advanced,diagnostics}` and `adapters/codex`. Implement behavior in these modules; flat compatibility facades preserve current imports/entrypoints.
- Use `core.resources` for schemas/static/helper paths. Five flat JSON schema aliases support existing coordinators; keep their bytes equal to canonical schemas and retain parity tests. Do not terminate the user's coordinator to remove compatibility support.
- Python runtime uses standard library. The pinned .NET 8 `tools/tmdl_bridge` wraps Microsoft's `TmdlSerializer`; NuGet restore is setup-only and runtime stays offline. Preserve required bridge binaries, certificates and third-party licenses.

## Product boundaries

- Source Excel/PBIP is read-only by default. Patches/restore may target only an explicitly chosen PBIP copy. Preserve unsupported PBIP metadata; do not edit outside supported PBIR definition areas or use free-form TMDL replacement as a production patcher.
- Source-only web UI stays local: temporary copies, bounded opt-in preview, no cloud/Codex/PBIP. CSV ambiguity or inconsistent row widths block dependent mapping.
- Excel Analyze may send only the submitted prompt and bounded workbook sample through Codex after the user's action. Show the disclosure; never send the whole workbook, local path or separate source-only UI data.
- AI advice does not grant approval. Feedback creates a new proposal revision; approval binds the exact revision. A user may acknowledge advice-only risk, but deterministic schema/security/dependency hard blockers cannot be overridden. Proposed charts require field/type/page/placement review before PBIR creation.
- Static checks/Preview are not Power BI Desktop verification. Do not mark unsupported patch/runtime capabilities complete.
- Typed has a closed 15-operation/10-expression catalog. Preserve immutable history, canonical hashes, CAS, HEAD/source/version binding, staging, explicit approval and bounded cache authority. Keep locks/state transitions in their owner.
- Annotation editing, semantic/runtime diff and persisted runtime summaries are cancelled. Reserved `name`, `note`, `annotationUpdatedAt` and `runtimeSummary` stay required-null; reject non-null values as unsupported. Do not migrate old workbook history implicitly.
- Advanced M verification is deferred at the user's request. Its existing exception remains: temporary exported workbook Preview creates/reuses a marked values-only result sheet; separate explicit Apply may replace only the exact previewed Table/usedRange values. Block Table expansion into occupied cells, clear old tails and recheck workbook/source/M before Apply. No backup, Save, persisted M/query/connection or rollback/Ctrl+Z promise. Possible write/read-back failure is partial/unknown. External M is not a sandbox and may use file/web/database/Excel credentials; it does not enable arbitrary formula Apply in the main assistant.
- Session defaults remain 30-minute idle/8-hour absolute TTL, independent fail-fast Codex/Excel slots and marked temporary workspaces. Do not weaken guards for tests.

## Development and verification

- Build small representative slices with synthetic fixtures. Do not log raw cells, credentials, complete workbook binaries or private paths. Do not use an open user workbook as a test fixture.
- CLI: `py -m pbip_assistant`. Source UI: `py -m pbip_assistant.webapp --port 8765`. Coordinator: `py -m pbip_assistant.excel_addin_server`. See README for full sample commands and bridge setup.
- Fast gate: `py tools/run_checks.py fast`; runtime: `py tools/run_checks.py runtime`; opt-in live Codex: set `PQPC_LIVE_CODEX=1` then `py tools/run_checks.py codex`. Full discovery: `py -m unittest discover -s tests -v` (Python 3.13).
- Tests are organized by capability under support/fixtures/unit/contracts/integration/journeys/taskpane/runtime/live. Keep reusable fakes/oracles in `tests/support`; preserve the required-case discovery guard. Removing a case requires a retained behavioral replacement.
- Small isolated changes use focused checks; cross-cutting changes and release qualification require full regression. All 12 task-pane JS scripts remain in the automated gate.
- An Excel add-in defect needs the complete affected journey: workbook/session load, persisted revision/HEAD, action, relevant Preview/staging/Confirm/cache/checkout/reopen, task-pane state and coordinator/runtime read-back. Exercise success and recovery; assert prior revisions/source preservation where required.
- Use the synthetic live harness for repeatable UI/runtime checks. Report exact command/revision, layer, pass/fail/skip, elapsed time, error codes, revision/step changes, result dimensions and source fingerprints. Unit/HTTP/Office.js simulation is not live Excel end-to-end evidence. Missing Excel/Codex/auth/UI gates are `Blocked` or `Not run`; do not hand implementer verification to the user.
- Target release: application/npm/HTTP 1.2.0, Office manifest 1.2.0.0. Change metadata only after required exact-current automated/live gates pass. API/schema/spec versions are independent.
- If `tools/excel_addin/manifest.xml` changes, synchronize that exact file to `C:\AddinManifests\manifest.xml` and verify matching SHA-256. Preserve unrelated catalog files and `.certs`; HTML/JS is served from this repository.
