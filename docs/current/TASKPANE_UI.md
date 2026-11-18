# Current task-pane UI contract

## Preparation source import (feature 003 contract)

The source journey has two steps, `1. Nguồn → 2. Đề bài`. The entry screen shows compact workbook context and keeps workbook details collapsed. `Đề bài` becomes available after a successful read-back of imported sheets or validation of existing workbook data. See [CURRENT_STATUS.md](CURRENT_STATUS.md) for verification status.

Import uses the existing review, one-use write permit and read-back checks. With `preparationBackups: false`, these checks use transient semantic and native sheet identity evidence. A partial or unknown write requires explicit fresh attachment and review before another attempt. Preparation cleanup, journal and recovery modules serve legacy callers.

The tab bar has exactly two tabs: `Trợ lý` and `PQ_Code-M`. The main assistant uses the eight cards below. Formula advice, copyable code cards and the old formula Apply controls have been removed from that tab. The backend compatibility endpoint `/api/excel/analyze` remains available; it is separate from this UI.

| Card | DOM section | Behavior |
|---|---|---|
| 01 Workbook | `flow-workbook-section` | Connection metadata, active sheet, ExcelApi and read-again action. |
| 02 Sources | `flow-source-section` | Receives verified sources from `1. Nguồn`. Discover samples deterministically and compute reads the selected full sources. |
| 03 Request | `flow-prompt-section` | 20,000-character request, measured questions and answers. Explicit disclosure is required before Codex receives the request, descriptive metadata and at most 20 sample rows across sources. No complete workbook or local paths are sent to Codex. |
| 04 Understanding | `flow-understand-section` | Measured table/relationship counts and assumptions; details start collapsed. Before understanding, selected workbook sources are read again. Discover compares only its bound sample and dimensions; compute compares all bound rows. Failed reads or mismatches clear stale snapshot/plan authority and preserve consumed-write warnings. File-only understanding does not invoke Office.js. |
| 05 A/B plans | `flow-branches-section` | Two validated Typed plans on the same compute snapshot, bounded previews, elapsed time, individual reconciliation and optional comparable delta. A hard blocker cannot be acknowledged away. Missing control-total evidence requires a separate explicit acknowledgement and keeps an unverified label. |
| 06 Frozen Spec | `flow-spec-section` | Exact branch, immutable revision hashes, steps, target and labels. Approval binds that reviewed revision. |
| 07 Write | `flow-apply-section` | An explicit checkbox is required both by the handler and button. A restored approved Spec must be reticked. ExcelApi 1.9 preflight precedes consumption. Write only a new named result sheet, set Text format before literal values, then verify every result cell, absence of formulas and marker. Decimal numbers are written as text to preserve precision. No Save or automatic retry after consumed/unknown writes. |
| 08 Result and Record | `flow-result-section` | Measured delta, labels, full JSON download and separate metadata persistence. Custom XML stores a bounded metadata node with its own hash and CAS; `recordHash` refers to the full record and is not reverified from metadata alone. Reopen is metadata-only and freshness stays unknown until full sources are reloaded. XML write/read-back does not Save the workbook. |

Every card exposes `data-state` and a status chip with an icon, text and color. Ctrl+Enter in `#prompt` invokes only an enabled `flow-analyze-button`; composition, repeat and extra modifier events are ignored. All user data is rendered as text. Coordinator/session/workbook changes invalidate dependent authority; automatic read failures do not erase a consumed-write warning.

Bounds are 100,000 rows per source, 200 input columns for planning, 256 output columns, 20 plan steps, a 400,000-cell write limit and a 200-row on-screen result preview. Six catalog join kinds use Typed nested-join semantics and require expansion before a scalar final result. `parityChecked: none` displays an explicit warning; local arithmetic and fake Office hosts are not live Power Query or Office.js verification.

The following Typed/Problem Chain contract continues within `PQ_Code-M`.

The UI invokes existing guarded use cases; visual presentation never grants approval or changes persisted history semantics.

| ID | Current requirement |
|---|---|
| UI-001 | Use an allowlisted local Lucide SVG subset with its license. Icon buttons require Vietnamese accessible labels, tooltips/titles, visible focus and disabled state. No CDN/icon runtime or user-supplied SVG. |
| UI-002 | History starts collapsed, shows HEAD/revision count and expands into the deterministic parent/child tree. Expansion state is UI-only. Opening a sibling branch collapses the previously open sibling. |
| UI-003 | A revision label invokes checkout: persist HEAD, validate cache and restore a valid complete cached result or stage a fresh Preview on cache miss/stale. Busy state blocks duplicate clicks; nested action buttons stop propagation. |
| UI-004 | Branch/edit use one compact composer. Leaf deletion preserves its existing no-confirm behavior; deleting a subtree requires explicit confirmation of its size. Root/dependency restrictions remain authoritative. |
| UI-005 | The new-problem/branch/edit controls open the appropriate composer mode, with context, one prompt, Cancel and Submit. Preserve the 4,000-character limit, busy state, errors and exact server mode. |
| UI-006 | Revision header shows step count and owner/HEAD. Put summary/IDs/questions/assumptions/warnings behind an info control with an amber indication when relevant; hard blockers stay visible. |
| UI-007 | Step cards start collapsed with at most one expanded. Show compact number/name/operation/final marker/description; full schema stays in expanded details. Keep diagnostic Run separate from edit/overflow actions. Intermediate diagnostics remain staging and never write the result sheet. |
| UI-008 | Each revision node exposes a labelled `Quay về` button, disabled on the working HEAD. The confirmation dialog stays binary by default and offers a second, explicitly labelled action only when the caller supplies one, so reverting never deletes descendants implicitly (PC-FR-021/PC-FR-028). Reverting and keeping later revisions issues one checkout and zero deletes; the delete action removes only the direct-child subtrees and leaves HEAD on the revert target. |
| UI-009 | The step list is followed by one correction prompt. Submitting re-analyses instead of requiring manual operation edits: with an active chain it opens the existing composer mode (`editProblem` for a non-root problem head, otherwise `continue`) and creates exactly one revision; standalone it appends the instruction to the request and re-plans. The textarea clears only after a committed revision, and correcting steps never runs Excel Preview by itself. |

Keep history/revision sections usable at narrow task-pane widths without horizontal overflow. Preserve keyboard access, practical hit targets, typed editing restrictions and runtime/cache/approval invalidation. Preview, Confirm, cancel, stale-cache recovery and session recovery must be tested through the actual handlers and runtime boundaries.
## Assistant source entry

`Chọn thư mục` opens the authenticated native folder dialog once to choose the root. The task pane lists subfolders and supported CSV and XLSX files with a breadcrumb and an up control. Selections stay checked across folders. `Chọn tất cả thư mục này` selects files in the current folder only. The browser reads metadata and opens selected files when the user chooses `Nhập vào workbook`.

Each CSV creates a new sheet with automatically inferred column types and Excel number formats. Each XLSX adds its sheets as a group. The source flow omits data and cleanup previews, per-column format questions and the workbook date-system selector. Excel supplies the date system automatically.

The import report shows file and sheet totals, which sheets were created, the automatic exceptions by column, and reasons for skipped files. Each exception shows the reason and affected cell count, with up to two samples of 40 characters each. The panel displays up to 200 exception rows and includes the rest in the total.

`Dùng dữ liệu trong workbook` checks for a header and data rows, warns about empty or non-tabular sheets, and reads the valid sources again. This branch leaves workbook data intact. If validation finds no usable source, `Đề bài` stays disabled.
