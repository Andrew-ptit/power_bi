# Implementation Handoff — Problem Chain + Revision UI

## 1. Document control

| Field | Value |
|---|---|
| Status | Approved UI handoff; ready for implementation |
| Date | 2026-10-18 |
| Scope | Excel task pane, Typed Steps Problem Chain Phase 2 |
| Approved interactive reference | `spikes/problem-chain-revision-combined-wireframe.html` |
| Reference SHA-256 | `124FE026719513F1B4B5036FC2E000A0F294BD50BDA51C14D7083D17F9EF7BCD` |
| Icon policy | Local Lucide SVG subset; no Unicode glyphs and no CDN |
| Product files expected to change | `pbip_assistant/excel_addin/taskpane.html`, `taskpane.css`, `taskpane.js`, focused JS tests |
| Product files not expected to change | Server endpoints, Problem Chain domain model, manifest |

## 2. Objective

Replace the current long Problem Chain timeline and verbose Typed Step cards with the approved compact interaction model, without changing Problem Chain persistence, checkout/cache behavior, revision semantics, validation, preview, approval or apply contracts.

The wireframe is the visual and interaction source of truth. It is not product code to copy wholesale. Reuse the existing product state and functions.

## 3. Non-negotiable UX decisions

### UI-001 — Local professional icons

- Use a small local subset of Lucide SVG icons.
- Do not use characters such as `V`, `⌄`, `✎`, `⑂`, `⋯`, `×` or emoji as icons.
- Do not use a CDN or an icon runtime that can fail in the Office task pane.
- Every icon-only button must have an accessible Vietnamese `aria-label`, native `title` or the existing tooltip mechanism, keyboard focus state and disabled state.
- Preserve the Lucide license. A copy already exists at `spikes/vendor/LUCIDE_LICENSE.txt`.

Required icon meanings:

| Action | Suggested Lucide icon |
|---|---|
| Expand/collapse | `chevron-right` / rotation |
| Create a new problem | `square-pen` |
| Create branch | `git-fork` |
| Edit problem/step | `square-pen` |
| Delete | `trash-2` |
| Revision information | `circle-info` |
| Add step | `plus` |
| More actions | `ellipsis` |
| Run to step | `play` |

### UI-002 — Problem Chain header and accordion

- Keep the heading `01 · Problem Chain / Lịch sử vấn đề`.
- Show the current HEAD and revision count in the header.
- Provide two header icon buttons: collapse/expand history and create a new problem.
- History starts collapsed when the task pane is first rendered so the Revision section is immediately visible.
- Expanding history shows the revision tree.
- Clicking a parent expands its children. Expanding a different parent at the same level collapses the previously expanded sibling branch.
- Tree indentation and connector lines must show parent/child relationships clearly.
- Do not persist expanded/collapsed UI state into the Problem Chain document.

### UI-003 — Clicking a revision means checkout

- Remove the separate `Xem` button.
- Clicking a revision row invokes the existing checkout flow and makes that revision HEAD.
- Product implementation must call `checkoutProblemRevision(revisionId)`, not merely `selectProblemChainRevision(revisionId)`.
- Existing checkout behavior remains authoritative: persist the new head, validate cache, write a valid cached result to `PQ_Typed_Result`, or run a fresh preview when the cache is missing/stale.
- Show busy/disabled feedback while checkout is running. A second click must not start a duplicate job.
- Clicking an action icon inside a row must stop propagation and must not also checkout the row.

### UI-004 — Revision row actions

- Replace text action buttons with icons.
- `Create branch` opens one compact prompt composer for that revision.
- `Edit problem` opens the same compact composer in edit mode.
- `Delete` keeps the current business behavior:
  - deleting a leaf revision does not require confirmation;
  - deleting a revision with descendants requires confirmation and clearly states the subtree size;
  - existing root deletion restriction remains unchanged unless separately approved.
- Disabled edit/delete conditions and their explanations remain unchanged.

### UI-005 — Problem prompt composer

- Remove the permanently visible `Vấn đề tiếp theo` textarea from the normal history layout.
- The header `square-pen` icon opens the compact composer for a new continuation from HEAD.
- Branch/edit icons open the same composer with the appropriate mode, title and submit label.
- Composer contains only the mode context, one prompt textarea, `Hủy`, and the relevant submit button.
- Preserve the current 4,000-character limit, busy state, server calls and error handling.
- Reuse existing DOM IDs where practical so event bindings and tests are not needlessly broken.

### UI-006 — Compact Revision section

- Keep the heading `02 · Revision / Các bước xử lý`.
- Header shows step count and owner revision/HEAD state.
- Move the long plan summary, revision ID/change reason, questions, assumptions and warnings behind the `circle-info` control.
- Show a small amber dot on the info icon when questions, assumptions or warnings exist.
- Keep blockers visible and blocking; do not hide hard blockers only to make the UI cleaner.
- Use the `plus` icon for adding a step.

### UI-007 — Step cards

- Cards are collapsed by default; at most one card is expanded at a time.
- Collapsed card shows: step number, variable name, friendly Vietnamese operation label, final badge when applicable, and a one-line description.
- Do not print the complete output-column list in the collapsed card. Show only a compact count/summary; full structure remains available through `Xem cấu trúc` in the expanded area.
- Expanded card shows dependency/output facts, cache state and run estimate only when relevant.
- Use icon buttons for edit and overflow actions. Move delete, move up/down and set-final into the overflow menu.
- Keep `Chạy toàn bộ đến bước này` visually separate on the right with a `play` icon.
- Running an intermediate step remains diagnostic/staging only. It must not write `PQ_Typed_Result`.
- Preserve all current `manualEditBlocked`, diagnostic capability, validation and staging guards.

## 4. Mapping to existing code

### HTML

File: `pbip_assistant/excel_addin/taskpane.html`

- Refactor `#pqpc-section` header and content around existing IDs.
- Reuse `#pqpc-timeline`, `#pqpc-branch-editor`, `#pqpc-progress`, `#pqpc-impact-section`, `#pq2-plan-section`, `#pq2-step-list` and editor/preview sections.
- The old permanent `#pqpc-prompt` block may be moved into the compact composer or replaced while preserving equivalent event wiring.
- Do not change the Advanced M mode or manifest.

### CSS

File: `pbip_assistant/excel_addin/taskpane.css`

- Replace the current timeline-dot presentation at approximately the `.problem-chain-*` rules with compact tree rows from the reference.
- Replace verbose `.typed-step-card` presentation with collapsible cards.
- Add scoped reusable styles for icon buttons, SVG icons, tree connectors, accordion rows, expanded card detail, overflow menu and info panel.
- Keep the task pane usable at its narrow Excel width. No horizontal scrollbar for these two sections.
- Preserve visible keyboard focus and minimum practical hit targets.

### JavaScript

File: `pbip_assistant/excel_addin/taskpane.js`

Relevant existing functions:

- `selectProblemChainRevision`
- `problemChainButton`
- `problemRevisionTree`
- `openProblemBranchEditor`
- `renderProblemChain`
- `deleteProblemRevision`
- `checkoutProblemRevision`
- `typedActionButton`
- `renderTypedPlan`

Implementation guidance:

1. Add a local `createIcon(name)` helper that returns SVG DOM nodes from a fixed allowlist of vendored paths. Do not inject arbitrary SVG strings from server/user data.
2. Add an icon-button helper that requires an accessible label and handler.
3. Maintain UI-only sets/IDs for expanded history branches and the currently expanded step. Do not add them to Custom XML.
4. Replace `renderProblemChain()` text action buttons with row click plus icon actions.
5. Route row click to `checkoutProblemRevision()`. Stop propagation inside action buttons.
6. Keep `problemRevisionTree()` and its deterministic ordering; build nested DOM from parent relationships instead of relying only on flat margin depth.
7. Refactor `renderTypedPlan()` so cards toggle detail and only one card stays open.
8. Preserve all backend payloads and state invalidation rules.

## 5. Explicitly out of scope

- No API or server contract change.
- No change to revision graph, Custom XML schema, history hash or review hash.
- No change to cache capacity/version/fingerprint rules.
- No change to preview, approval or apply authorization.
- No new external dependency or CDN.
- No manifest change.
- No Advanced M redesign.

## 6. Acceptance criteria

| ID | Acceptance criterion |
|---|---|
| AC-UI-001 | No Unicode/emoji substitute is visible as an icon; all controls render local SVG icons. |
| AC-UI-002 | With network unavailable, every icon still renders in the Excel task pane. |
| AC-UI-003 | History initially collapses and the Revision section is visible without traversing the entire tree. |
| AC-UI-004 | Expanding one sibling parent collapses the previously expanded sibling parent. |
| AC-UI-005 | Clicking a revision row performs checkout; there is no separate `Xem` button. |
| AC-UI-006 | Clicking branch/edit/delete icons does not accidentally checkout the row. |
| AC-UI-007 | Header create icon opens the new-problem composer; branch/edit icons open the same compact composer in their own modes. |
| AC-UI-008 | Leaf delete has no confirmation; deleting a node with descendants asks for confirmation and displays affected count. |
| AC-UI-009 | Revision metadata/warnings are behind the info control; hard blockers remain visible. |
| AC-UI-010 | Step cards are compact and only one card can be expanded at a time. |
| AC-UI-011 | Full output columns are not printed in every collapsed card; `Xem cấu trúc` still exposes them. |
| AC-UI-012 | Edit/delete/move/set-final/run actions retain their existing guards and effects. |
| AC-UI-013 | Keyboard users can reach every icon control and identify it from its accessible name. |
| AC-UI-014 | Checkout cache hit, cache miss/stale fallback, branch creation, edit problem and delete subtree still pass focused tests. |
| AC-UI-015 | The two sections fit the Excel task pane without horizontal overflow at narrow width. |

## 7. Focused verification required

Update brittle DOM-index assertions in `tests/taskpane_problem_chain.js` to query behavior/attributes rather than old child positions. Add independent assertions for:

- no `Xem` action;
- row click calls checkout once;
- action click stops row checkout;
- accordion sibling collapse;
- single-open step card;
- icon accessible labels;
- subtree confirmation behavior unchanged;
- offline/local SVG rendering source contains no CDN reference and no glyph substitutions.

Run at minimum:

```powershell
node tests/taskpane_problem_chain.js
py -m unittest tests.test_problem_chain_phase1_crosscheck -v
```

Then manually sideload in Excel and verify at narrow task-pane width:

1. Expand/collapse history.
2. Click a revision with valid cache and verify HEAD/result restoration.
3. Open branch and edit composers.
4. Delete a leaf, then attempt deletion of a parent with children.
5. Expand all three sample step cards one after another.
6. Open info and overflow menus.
7. Disconnect network and reload the pane; icons must remain visible.

Do not report completion if manual Excel rendering has not been observed. Report it as `Automated pass; manual sideload not run` instead.

## 8. Claude execution prompt

Implement the approved Problem Chain + Revision UI described in this handoff. Read the interactive reference and the current product code before editing. Preserve all existing backend contracts, checkout/cache behavior, revision semantics, guards and security boundaries. Use a local allowlisted Lucide SVG subset—no CDN and no Unicode icon substitutes. Update focused DOM tests to assert behavior rather than old child indexes. Run the focused commands in section 7 and report exact pass/fail/skip results plus any manual sideload status. Do not claim completion from the wireframe alone.
