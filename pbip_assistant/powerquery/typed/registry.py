"""Closed Typed v1 operation registry pairing validation with compilation.

The registry contains only built-in functions. It is not an extension/plugin
mechanism: unsupported operations must remain rejected at the trust boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import compiler, validation
from .model import OPERATION_ARITY, PARAMETER_KEYS, EXPRESSION_KEYS


@dataclass(frozen=True)
class OperationSpec:
    normalize: Callable[..., tuple[dict[str, Any], list[dict[str, Any]], list[str]]]
    compile: Callable[..., str]


OPERATION_REGISTRY: Mapping[str, OperationSpec] = MappingProxyType({
    'source.workbookTable': OperationSpec(validation._normalize_source_workbook_table, compiler._compile_source_workbook_table),
    'source.usedRange': OperationSpec(validation._normalize_source_workbook_table, compiler._compile_source_workbook_table),
    'table.filterRows': OperationSpec(validation._normalize_table_filter_rows, compiler._compile_table_filter_rows),
    'table.selectColumns': OperationSpec(validation._normalize_table_select_columns, compiler._compile_table_select_columns),
    'table.removeColumns': OperationSpec(validation._normalize_table_remove_columns, compiler._compile_table_remove_columns),
    'table.renameColumns': OperationSpec(validation._normalize_table_rename_columns, compiler._compile_table_rename_columns),
    'table.changeTypes': OperationSpec(validation._normalize_table_change_types, compiler._compile_table_change_types),
    'table.addColumn': OperationSpec(validation._normalize_table_add_column, compiler._compile_table_add_column),
    'table.sortRows': OperationSpec(validation._normalize_table_sort_rows, compiler._compile_table_sort_rows),
    'table.distinctRows': OperationSpec(validation._normalize_table_distinct_rows, compiler._compile_table_distinct_rows),
    'table.groupRows': OperationSpec(validation._normalize_table_group_rows, compiler._compile_table_group_rows),
    'table.aggregateRows': OperationSpec(validation._normalize_table_group_rows, compiler._compile_table_group_rows),
    'table.appendTables': OperationSpec(validation._normalize_table_append_tables, compiler._compile_table_append_tables),
    'table.mergeTables': OperationSpec(validation._normalize_table_merge_tables, compiler._compile_table_merge_tables),
    'table.expandTableColumn': OperationSpec(validation._normalize_table_expand_table_column, compiler._compile_table_expand_table_column),
})

# Explicit catalogs make accidental additions/removals fail before execution.
EXPRESSION_KINDS = frozenset({
    "literal", "columnRef", "compare", "arithmetic", "boolean", "not",
    "ifThenElse", "coalesce", "functionCall", "safeDivide",
})
if len(OPERATION_REGISTRY) != 15 or set(OPERATION_REGISTRY) != set(OPERATION_ARITY) or set(OPERATION_REGISTRY) != set(PARAMETER_KEYS):
    raise RuntimeError("Typed operation registry differs from the closed operation catalog")
if len(EXPRESSION_KINDS) != 10 or EXPRESSION_KINDS != set(EXPRESSION_KEYS):
    raise RuntimeError("Typed expression registry differs from the closed expression catalog")
