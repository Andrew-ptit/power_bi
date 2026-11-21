"""In-memory execution of the closed Typed catalog; no Excel or external IO."""

from .executor import MAX_COLUMNS, MAX_ROWS, execute_plan

__all__ = ["execute_plan", "MAX_ROWS", "MAX_COLUMNS"]
