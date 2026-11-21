"""The task pane is served as ordered classic scripts; read them as one source.

A static cross-check has to see the same text the browser sees, otherwise a
function that moved to another file looks deleted. The load order here must match
`tests/support/taskpane_source.js` and `excel_addin/taskpane.html`; a contract test
pins all three together.
"""
from __future__ import annotations

from pathlib import Path

ADDIN_ROOT = Path(__file__).resolve().parents[2] / "pbip_assistant" / "excel_addin"

ORDER = (
    "taskpane_core.js",
    "taskpane_flow.js",
    "taskpane_workspace.js",
    "taskpane_problem_chain.js",
    "taskpane_typed_pq.js",
    "taskpane.js",
)


def taskpane_source() -> str:
    """Concatenate the pane scripts in load order."""
    return "\n".join((ADDIN_ROOT / name).read_text(encoding="utf-8") for name in ORDER)
