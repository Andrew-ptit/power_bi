# Current Typed task-pane UI contract

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

Keep history/revision sections usable at narrow task-pane widths without horizontal overflow. Preserve keyboard access, practical hit targets, typed editing restrictions and runtime/cache/approval invalidation. Preview, Confirm, cancel, stale-cache recovery and session recovery must be tested through the actual handlers and runtime boundaries.
