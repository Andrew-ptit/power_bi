"""Deterministic Typed source binding, expression and step validation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from ...errors import InputError
from ...core.workbook_snapshot import snapshot_workbook as _snapshot
from .model import (
    MAX_STEPS,
    MAX_SOURCES,
    VARIABLE,
    CLIENT_REF,
    M_RESERVED,
    OPERATION_ARITY,
    TYPE_NAMES,
    AGGREGATIONS,
    JOIN_KINDS,
    FUNCTIONS,
    COMPARE_OPERATORS,
    PARAMETER_KEYS,
    EXPRESSION_KEYS,
    _compatible_types,
    _content_id,
    _digest,
    _infer_type,
    _issue,
    _list_of_strings,
    _random_id,
    _strict_keys,
)


def build_source_catalog(workbook: Any) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    snapshot = _snapshot(workbook)
    if len(snapshot["sources"]) > MAX_SOURCES:
        raise InputError("PQV2_SOURCE_LIMIT", "workbook", "Typed plans support at most 20 sources")
    catalog: list[dict[str, Any]] = []
    for source in snapshot["sources"]:
        kind = "excelTable" if "table" in source else "usedRange"
        identity = (
            {"kind": kind, "objectName": source.get("table")}
            if kind == "excelTable"
            else {"kind": kind, "sheetName": source["sheet"], "headerRow": source.get("headerRow")}
        )
        source_id = _content_id("src", identity)
        columns = []
        declared_types = source.get("inferredTypes")
        for index, name in enumerate(source["headers"]):
            values = [row[index] for row in source["rows"] if index < len(row)]
            columns.append({
                "columnId": _content_id("col", {"sourceId": source_id, "ordinal": index, "name": name}),
                "name": name, "inferredType": declared_types[index] if declared_types is not None else _infer_type(values),
                "nullable": any(value is None or value == "" for value in values), "ordinal": index,
            })
        descriptor: dict[str, Any] = {
            "sourceId": source_id, "kind": kind, "sheetName": source["sheet"],
            "schemaHash": "sha256:" + _digest(columns), "sampleOnly": source["sampleOnly"],
            "columns": columns, "sampleRows": source["rows"],
            "totalRows": source["totalRows"], "totalColumns": source["totalColumns"],
        }
        if kind == "excelTable":
            descriptor["objectName"] = source["table"]
        else:
            descriptor["headerRow"] = source["headerRow"]
            descriptor["runtimeAlias"] = "PQ_Input_" + source_id.removeprefix("src_")[:8]
        catalog.append(descriptor)
    snapshot_id = _content_id("snap", {"workbook": snapshot["name"], "activeSheet": snapshot["activeSheet"], "sources": catalog})
    return snapshot, catalog, snapshot_id


def _column(schema: list[dict[str, Any]], reference: Any, path: str) -> dict[str, Any]:
    if not isinstance(reference, str):
        raise InputError("PQV2_COLUMN_NOT_FOUND", path, "Column reference must be text")
    by_id = [item for item in schema if item["columnId"] == reference]
    if by_id:
        return by_id[0]
    by_name = [item for item in schema if item["name"] == reference]
    if len(by_name) == 1:
        return by_name[0]
    detail = "Column name is ambiguous" if len(by_name) > 1 else "Column does not exist at this step"
    raise InputError("PQV2_COLUMN_NOT_FOUND", path, detail)


def _new_column(step_id: str, name: str, column_type: str, ordinal: int, *, nullable: bool = True, nested_schema: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "columnId": _content_id("col", {"stepId": step_id, "name": name, "ordinal": ordinal}),
        "name": name, "inferredType": column_type, "nullable": nullable, "ordinal": ordinal,
    }
    if nested_schema is not None:
        result["nestedSchema"] = deepcopy(nested_schema)
    return result


def _normalize_expression(value: Any, schema: list[dict[str, Any]], path: str) -> tuple[dict[str, Any], str]:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path, "Expression node requires a kind")
    kind = value["kind"]
    if kind not in EXPRESSION_KEYS:
        raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path, f"Expression kind {kind!r} is not supported")
    unknown = set(value) - EXPRESSION_KEYS[kind]
    if unknown:
        code = "PQV2_POLICY_VIOLATION" if unknown & {"mCode", "rawM", "expressionText"} else "PQV2_JSON_INVALID"
        raise InputError(code, path, f"Expression contains unsupported fields: {sorted(unknown)}")
    if kind == "literal":
        value_type = value.get("valueType")
        if value_type not in {"null", "text", "number", "integer", "logical", "date", "datetime"}:
            raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path, "Literal type is not supported")
        literal = value.get("value")
        if value_type == "null" and literal is not None:
            raise InputError("PQV2_TYPE_MISMATCH", path, "Null literal must contain null")
        if value_type in {"number", "integer"} and (not isinstance(literal, (int, float)) or isinstance(literal, bool)):
            raise InputError("PQV2_TYPE_MISMATCH", path, "Numeric literal requires a number")
        if value_type == "logical" and not isinstance(literal, bool):
            raise InputError("PQV2_TYPE_MISMATCH", path, "Logical literal requires true or false")
        if value_type in {"text", "date", "datetime"} and not isinstance(literal, str):
            raise InputError("PQV2_TYPE_MISMATCH", path, "Text/date literal requires text")
        return {"kind": kind, "valueType": value_type, "value": literal}, "any" if value_type == "null" else value_type
    if kind == "columnRef":
        column = _column(schema, value.get("columnId", value.get("columnName", value.get("column"))), path + ".columnId")
        return {"kind": kind, "columnId": column["columnId"]}, column["inferredType"]
    if kind == "compare":
        operator = value.get("operator")
        if operator not in COMPARE_OPERATORS:
            raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path + ".operator", "Comparison operator is not supported")
        left, left_type = _normalize_expression(value.get("left"), schema, path + ".left")
        result = {"kind": kind, "operator": operator, "left": left}
        if operator not in {"isNull", "isNotNull"}:
            right, right_type = _normalize_expression(value.get("right"), schema, path + ".right")
            if operator not in {"eq", "ne", "contains", "startsWith", "endsWith"} and not _compatible_types(left_type, right_type):
                raise InputError("PQV2_TYPE_MISMATCH", path, f"Comparison types differ: {left_type} and {right_type}")
            result["right"] = right
        return result, "logical"
    if kind == "arithmetic":
        operator = value.get("operator")
        if operator not in {"add", "subtract", "multiply"}:
            raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path + ".operator", "Arithmetic operator is not supported")
        left, left_type = _normalize_expression(value.get("left"), schema, path + ".left")
        right, right_type = _normalize_expression(value.get("right"), schema, path + ".right")
        if left_type not in {"any", "number", "integer"} or right_type not in {"any", "number", "integer"}:
            raise InputError("PQV2_TYPE_MISMATCH", path, "Arithmetic operands must be numeric")
        return {"kind": kind, "operator": operator, "left": left, "right": right}, "number"
    if kind == "boolean":
        operator = value.get("operator")
        operands = value.get("operands")
        if operator not in {"and", "or"} or not isinstance(operands, list) or len(operands) < 2:
            raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path, "Boolean expression requires and/or with at least two operands")
        clean = []
        for index, operand in enumerate(operands):
            node, node_type = _normalize_expression(operand, schema, f"{path}.operands[{index}]")
            if node_type != "logical":
                raise InputError("PQV2_TYPE_MISMATCH", f"{path}.operands[{index}]", "Boolean operand must be logical")
            clean.append(node)
        return {"kind": kind, "operator": operator, "operands": clean}, "logical"
    if kind == "not":
        operand, operand_type = _normalize_expression(value.get("operand"), schema, path + ".operand")
        if operand_type != "logical":
            raise InputError("PQV2_TYPE_MISMATCH", path, "not requires a logical operand")
        return {"kind": kind, "operand": operand}, "logical"
    if kind == "ifThenElse":
        condition, condition_type = _normalize_expression(value.get("condition"), schema, path + ".condition")
        when_true, true_type = _normalize_expression(value.get("then"), schema, path + ".then")
        when_false, false_type = _normalize_expression(value.get("else"), schema, path + ".else")
        if condition_type != "logical":
            raise InputError("PQV2_TYPE_MISMATCH", path + ".condition", "Condition must be logical")
        output_type = true_type if true_type == false_type else "any"
        return {"kind": kind, "condition": condition, "then": when_true, "else": when_false}, output_type
    if kind == "coalesce":
        values = value.get("values")
        if not isinstance(values, list) or not 2 <= len(values) <= 20:
            raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path, "coalesce requires 2-20 values")
        clean, types = [], []
        for index, item in enumerate(values):
            node, node_type = _normalize_expression(item, schema, f"{path}.values[{index}]")
            clean.append(node)
            types.append(node_type)
        return {"kind": kind, "values": clean}, types[0] if len(set(types) - {"any"}) <= 1 else "any"
    if kind == "functionCall":
        function = value.get("function")
        args = value.get("args")
        expected_count = 2 if function == "number.round" and isinstance(args, list) and len(args) == 2 else 1
        if function not in FUNCTIONS or not isinstance(args, list) or len(args) != expected_count:
            raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path, "Function or argument count is not supported")
        normalized_args = [_normalize_expression(item, schema, f"{path}.args[{index}]") for index, item in enumerate(args)]
        clean = [item[0] for item in normalized_args]
        first_type = normalized_args[0][1]
        if function.startswith("text.") and first_type not in {"any", "text"}:
            raise InputError("PQV2_TYPE_MISMATCH", path, f"{function} requires text")
        if function == "number.round" and first_type not in {"any", "number", "integer"}:
            raise InputError("PQV2_TYPE_MISMATCH", path, "number.round requires a numeric value")
        if function == "number.round" and len(normalized_args) == 2 and normalized_args[1][1] not in {"any", "integer"}:
            raise InputError("PQV2_TYPE_MISMATCH", path + ".args[1]", "number.round digits must be an integer")
        if function.startswith("date.") and first_type not in {"any", "date", "datetime", "datetimezone"}:
            raise InputError("PQV2_TYPE_MISMATCH", path, f"{function} requires a date-like value")
        output_type = "text" if function.startswith("text.") and function != "text.length" else "integer" if function in {"text.length", "date.year", "date.month", "date.day"} else "number"
        return {"kind": kind, "function": function, "args": clean}, output_type
    if kind == "safeDivide":
        numerator, numerator_type = _normalize_expression(value.get("numerator"), schema, path + ".numerator")
        denominator, denominator_type = _normalize_expression(value.get("denominator"), schema, path + ".denominator")
        on_zero = value.get("onZero")
        if on_zero not in {"error", "null", "zero"}:
            raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path + ".onZero", "safeDivide requires an onZero policy")
        if numerator_type not in {"any", "number", "integer"} or denominator_type not in {"any", "number", "integer"}:
            raise InputError("PQV2_TYPE_MISMATCH", path, "safeDivide operands must be numeric")
        return {"kind": kind, "numerator": numerator, "denominator": denominator, "onZero": on_zero}, "number"
    raise InputError("PQV2_EXPRESSION_UNSUPPORTED", path, f"Expression kind {kind!r} is not supported")


def _column_list(schema: list[dict[str, Any]], value: Any, path: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > 200 or (not value and not allow_empty):
        raise InputError("PQV2_JSON_INVALID", path, "Expected a bounded non-empty column list")
    result = [_column(schema, item, f"{path}[{index}]")["columnId"] for index, item in enumerate(value)]
    if len(set(result)) != len(result):
        raise InputError("PQV2_JSON_INVALID", path, "Column list contains duplicates")
    return result


def _normalize_aggregations(value: Any, schema: list[dict[str, Any]], step_id: str, path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 50:
        raise InputError("PQV2_JSON_INVALID", path, "Expected 1-50 aggregations")
    clean, columns = [], []
    names: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise InputError("PQV2_JSON_INVALID", f"{path}[{index}]", "Aggregation must be an object")
        function, name = item.get("function"), item.get("outputName")
        if function not in AGGREGATIONS or not isinstance(name, str) or not name.strip() or len(name) > 200 or name in names:
            raise InputError("PQV2_JSON_INVALID", f"{path}[{index}]", "Aggregation function/output name is invalid")
        names.add(name)
        normalized: dict[str, Any] = {"function": function, "outputName": name}
        output_type = "integer" if function in {"rowCount", "countNonNull", "countDistinct"} else "number"
        if function != "rowCount":
            column = _column(schema, item.get("columnId", item.get("column")), f"{path}[{index}].column")
            normalized["columnId"] = column["columnId"]
            if function in {"min", "max"}:
                output_type = column["inferredType"]
            elif function in {"sum", "average"} and column["inferredType"] not in {"any", "number", "integer"}:
                raise InputError("PQV2_TYPE_MISMATCH", f"{path}[{index}]", "sum/average requires a numeric column")
        clean.append(normalized)
        columns.append(_new_column(step_id, name, output_type, len(columns), nullable=False))
    return clean, columns


def _normalize_operation(
    step_id: str, operation_type: str, parameters: Any,
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    if operation_type not in OPERATION_ARITY:
        raise InputError("PQV2_OPERATION_UNSUPPORTED", path + ".operationType", "Operation is not in the Typed v1 catalog")
    if not isinstance(parameters, dict):
        raise InputError("PQV2_JSON_INVALID", path + ".parameters", "Operation parameters must be an object")
    unknown = set(parameters) - PARAMETER_KEYS[operation_type]
    if unknown:
        code = "PQV2_POLICY_VIOLATION" if unknown & {"mCode", "rawM", "mExpression", "url", "path", "credential"} else "PQV2_JSON_INVALID"
        raise InputError(code, path + ".parameters", f"Operation contains unsupported fields: {sorted(unknown)}")
    from .registry import OPERATION_REGISTRY

    return OPERATION_REGISTRY[operation_type].normalize(
        step_id, operation_type, parameters, input_schemas, sources, path,
    )


def _normalize_source_workbook_table(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    source_id = parameters.get("sourceId")
    source = sources.get(source_id)
    expected_kind = "excelTable" if operation_type == "source.workbookTable" else "usedRange"
    if source is None or source["kind"] != expected_kind:
        raise InputError("PQV2_SOURCE_NOT_FOUND", path + ".parameters.sourceId", "Source does not exist or has the wrong kind")
    return {"sourceId": source_id}, deepcopy(source["columns"]), warnings


def _normalize_table_filter_rows(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    predicate, predicate_type = _normalize_expression(parameters.get("predicate"), schema, path + ".parameters.predicate")
    policy = parameters.get("onEvaluationError", "block")
    if predicate_type != "logical" or policy not in {"block", "keepRow", "dropRow"}:
        raise InputError("PQV2_TYPE_MISMATCH", path + ".parameters", "Filter requires a logical predicate and a valid error policy")
    if policy != "block":
        warnings.append(f"{operation_type} uses explicit error policy {policy}.")
    return {"predicate": predicate, "onEvaluationError": policy}, deepcopy(schema), warnings


def _normalize_table_select_columns(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    requested_ids = _column_list(schema, parameters.get("columnIds", parameters.get("columns")), path + ".parameters.columnIds")
    # Selecting columns is a membership operation in Typed mode, not a
    # reorder operation.  Preserve upstream ordinals regardless of the
    # order an AI draft happened to return.  Newly-created columns are
    # already appended by their producer operation.
    selected_ids = set(requested_ids)
    selected = [deepcopy(item) for item in schema if item["columnId"] in selected_ids]
    ids = [item["columnId"] for item in selected]
    for index, item in enumerate(selected): item["ordinal"] = index
    return {"columnIds": ids}, selected, warnings


def _normalize_table_remove_columns(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    ids = _column_list(schema, parameters.get("columnIds", parameters.get("columns")), path + ".parameters.columnIds")
    removed_ids = set(ids)
    output = [deepcopy(item) for item in schema if item["columnId"] not in removed_ids]
    if not output:
        raise InputError("PQV2_FINAL_OUTPUT_NOT_TABLE", path, "Removing every column would not produce a loadable result table")
    for index, item in enumerate(output): item["ordinal"] = index
    return {"columnIds": ids}, output, warnings


def _normalize_table_rename_columns(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    values = parameters.get("renames")
    if not isinstance(values, list) or not values:
        raise InputError("PQV2_JSON_INVALID", path + ".parameters.renames", "At least one rename is required")
    output = deepcopy(schema)
    clean = []
    for index, item in enumerate(values):
        if not isinstance(item, dict) or not isinstance(item.get("newName"), str) or not item["newName"].strip():
            raise InputError("PQV2_JSON_INVALID", f"{path}.parameters.renames[{index}]", "Rename is invalid")
        column = _column(output, item.get("columnId", item.get("column")), f"{path}.parameters.renames[{index}]")
        if any(existing["name"] == item["newName"] and existing["columnId"] != column["columnId"] for existing in output):
            raise InputError("PQV2_COLUMN_COLLISION", f"{path}.parameters.renames[{index}]", "New column name already exists")
        column["name"] = item["newName"]
        clean.append({"columnId": column["columnId"], "newName": item["newName"]})
    return {"renames": clean}, output, warnings


def _normalize_table_change_types(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    values = parameters.get("conversions")
    if not isinstance(values, list) or not values:
        raise InputError("PQV2_JSON_INVALID", path + ".parameters.conversions", "At least one conversion is required")
    output, clean = deepcopy(schema), []
    for index, item in enumerate(values):
        target = item.get("targetType") if isinstance(item, dict) else None
        if target not in TYPE_NAMES:
            raise InputError("PQV2_TYPE_MISMATCH", f"{path}.parameters.conversions[{index}]", "Target type is unsupported")
        column = _column(output, item.get("columnId", item.get("column")), f"{path}.parameters.conversions[{index}]")
        column["inferredType"] = target
        clean.append({"columnId": column["columnId"], "targetType": target, "culture": item.get("culture")})
    return {"conversions": clean}, output, warnings


def _normalize_table_add_column(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    name, data_type = parameters.get("newColumnName"), parameters.get("dataType", "any")
    if not isinstance(name, str) or not name.strip() or len(name) > 200 or any(item["name"] == name for item in schema):
        raise InputError("PQV2_COLUMN_COLLISION", path + ".parameters.newColumnName", "New column name is empty, too long or already exists")
    if data_type not in TYPE_NAMES:
        raise InputError("PQV2_TYPE_MISMATCH", path + ".parameters.dataType", "New column type is unsupported")
    expression, inferred = _normalize_expression(parameters.get("expression"), schema, path + ".parameters.expression")
    policy = parameters.get("onEvaluationError", "block")
    if policy not in {"block", "null"}:
        raise InputError("PQV2_JSON_INVALID", path + ".parameters.onEvaluationError", "Add-column error policy must be block or null")
    if data_type != "any" and inferred not in {"any", data_type} and not ({data_type, inferred} <= {"number", "integer"}):
        raise InputError("PQV2_TYPE_MISMATCH", path + ".parameters.expression", "Expression output does not match the declared type")
    output = deepcopy(schema) + [_new_column(step_id, name, data_type if data_type != "any" else inferred, len(schema), nullable=policy == "null")]
    if policy == "null": warnings.append("Calculated-column errors are explicitly replaced with null.")
    return {"newColumnName": name, "newColumnId": output[-1]["columnId"], "dataType": data_type, "expression": expression, "onEvaluationError": policy}, output, warnings


def _normalize_table_sort_rows(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    keys = parameters.get("keys")
    if not isinstance(keys, list) or not keys:
        raise InputError("PQV2_JSON_INVALID", path + ".parameters.keys", "At least one sort key is required")
    clean = []
    for index, item in enumerate(keys):
        direction = item.get("direction") if isinstance(item, dict) else None
        if direction not in {"ascending", "descending"}:
            raise InputError("PQV2_JSON_INVALID", f"{path}.parameters.keys[{index}]", "Sort direction is invalid")
        column = _column(schema, item.get("columnId", item.get("column")), f"{path}.parameters.keys[{index}]")
        clean.append({"columnId": column["columnId"], "direction": direction})
    return {"keys": clean}, deepcopy(schema), warnings


def _normalize_table_distinct_rows(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    scope = parameters.get("scope")
    if scope == "all":
        ids = [item["columnId"] for item in schema]
    elif scope == "columns":
        ids = _column_list(schema, parameters.get("columnIds", parameters.get("columns")), path + ".parameters.columnIds")
    else:
        raise InputError("PQV2_JSON_INVALID", path + ".parameters.scope", "Distinct scope must be all or columns")
    return {"scope": scope, "columnIds": ids}, deepcopy(schema), warnings


def _normalize_table_group_rows(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    keys = [] if operation_type == "table.aggregateRows" else _column_list(schema, parameters.get("keyColumnIds", parameters.get("keyColumns")), path + ".parameters.keyColumnIds", allow_empty=True)
    aggs, agg_columns = _normalize_aggregations(parameters.get("aggregations"), schema, step_id, path + ".parameters.aggregations")
    key_columns = [deepcopy(_column(schema, item, path)) for item in keys]
    output = key_columns + agg_columns
    for index, item in enumerate(output): item["ordinal"] = index
    return {"keyColumnIds": keys, "aggregations": aggs}, output, warnings


def _normalize_table_append_tables(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    mode = parameters.get("schemaMode")
    if mode not in {"strict", "union"}:
        raise InputError("PQV2_JSON_INVALID", path + ".parameters.schemaMode", "Append schemaMode is required")
    first_signature = [(item["name"], item["inferredType"]) for item in input_schemas[0]]
    if mode == "strict" and any([(item["name"], item["inferredType"]) for item in candidate] != first_signature for candidate in input_schemas[1:]):
        raise InputError("PQV2_TYPE_MISMATCH", path, "Strict append requires identical names, order and types")
    names: list[str] = []
    types: dict[str, set[str]] = {}
    for candidate in input_schemas:
        for item in candidate:
            if item["name"] not in names: names.append(item["name"])
            types.setdefault(item["name"], set()).add(item["inferredType"])
    output = [_new_column(step_id, name, next(iter(types[name])) if len(types[name]) == 1 else "any", index) for index, name in enumerate(names)]
    if mode == "union": warnings.append("Append union fills columns absent from an input with null.")
    return {"schemaMode": mode}, output, warnings


def _normalize_table_merge_tables(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    pairs = parameters.get("keyPairs")
    join_kind, nested_name = parameters.get("joinKind"), parameters.get("nestedColumnName")
    if join_kind not in JOIN_KINDS or not isinstance(nested_name, str) or not nested_name.strip():
        raise InputError("PQV2_JSON_INVALID", path + ".parameters", "Merge join kind or nested column name is invalid")
    if any(item["name"] == nested_name for item in input_schemas[0]):
        raise InputError("PQV2_COLUMN_COLLISION", path + ".parameters.nestedColumnName", "Nested column name already exists")
    if not isinstance(pairs, list) or not pairs:
        raise InputError("PQV2_JSON_INVALID", path + ".parameters.keyPairs", "Merge requires at least one key pair")
    clean = []
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            raise InputError("PQV2_JSON_INVALID", f"{path}.parameters.keyPairs[{index}]", "Key pair is invalid")
        left = _column(input_schemas[0], pair.get("leftColumnId", pair.get("leftColumn")), f"{path}.parameters.keyPairs[{index}].left")
        right = _column(input_schemas[1], pair.get("rightColumnId", pair.get("rightColumn")), f"{path}.parameters.keyPairs[{index}].right")
        if left["inferredType"] != "any" and right["inferredType"] != "any" and left["inferredType"] != right["inferredType"]:
            raise InputError("PQV2_TYPE_MISMATCH", f"{path}.parameters.keyPairs[{index}]", "Merge key types differ")
        clean.append({"leftColumnId": left["columnId"], "rightColumnId": right["columnId"]})
    output = deepcopy(input_schemas[0])
    output.append(_new_column(step_id, nested_name, "table", len(output), nested_schema=input_schemas[1]))
    return {"keyPairs": clean, "joinKind": join_kind, "nestedColumnName": nested_name, "nestedColumnId": output[-1]["columnId"]}, output, warnings


def _normalize_table_expand_table_column(step_id: str, operation_type: str, parameters: dict[str, Any],
    input_schemas: list[list[dict[str, Any]]], sources: dict[str, dict[str, Any]], path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    schema = input_schemas[0]
    nested = _column(schema, parameters.get("nestedColumnId", parameters.get("nestedColumn")), path + ".parameters.nestedColumn")
    if nested.get("inferredType") != "table" or not isinstance(nested.get("nestedSchema"), list):
        raise InputError("PQV2_TYPE_MISMATCH", path + ".parameters.nestedColumn", "Expand target is not a nested table column")
    selected = parameters.get("columns")
    if not isinstance(selected, list) or not selected:
        raise InputError("PQV2_JSON_INVALID", path + ".parameters.columns", "At least one nested column is required")
    output = [deepcopy(item) for item in schema if item["columnId"] != nested["columnId"]]
    clean = []
    for index, item in enumerate(selected):
        if not isinstance(item, dict):
            raise InputError("PQV2_JSON_INVALID", f"{path}.parameters.columns[{index}]", "Expanded column must be an object")
        source = _column(
            nested["nestedSchema"],
            item.get("sourceColumnId", item.get("columnId", item.get("column"))),
            f"{path}.parameters.columns[{index}]",
        )
        # Structured Outputs requires optional fields to be present and
        # nullable.  Treat an explicit null exactly like the omitted v1
        # draft field while retaining deterministic collision checks.
        new_name = item.get("newName") or source["name"]
        if not isinstance(new_name, str) or not new_name.strip() or any(existing["name"] == new_name for existing in output):
            raise InputError("PQV2_COLUMN_COLLISION", f"{path}.parameters.columns[{index}]", "Expanded column name collides")
        new_column = _new_column(step_id, new_name, source["inferredType"], len(output), nullable=True)
        output.append(new_column)
        clean.append({"sourceColumnId": source["columnId"], "sourceName": source["name"], "newColumnId": new_column["columnId"], "newName": new_name})
    for index, item in enumerate(output): item["ordinal"] = index
    return {"nestedColumnId": nested["columnId"], "columns": clean}, output, warnings


def _validate_draft_shape(draft: Any) -> dict[str, Any]:
    value = _strict_keys(draft, {"summary", "questions", "assumptions", "warnings", "steps", "finalOutputRef"}, {"summary", "questions", "assumptions", "warnings", "steps", "finalOutputRef"}, "draft")
    if not isinstance(value["summary"], str) or not value["summary"].strip() or len(value["summary"]) > 3000:
        raise InputError("CODEX_RESPONSE_INVALID", "summary", "Typed plan summary is invalid")
    for name in ("questions", "assumptions", "warnings"):
        _list_of_strings(value[name], name)
    if not isinstance(value["steps"], list) or len(value["steps"]) > MAX_STEPS:
        raise InputError("PQV2_STEP_LIMIT", "steps", "Typed plan exceeds 50 steps")
    for index, step in enumerate(value["steps"]):
        _strict_keys(
            step,
            {"clientRef", "variableName", "actionDescription", "operationType", "inputs", "parameters"},
            {"clientRef", "variableName", "actionDescription", "operationType", "inputs", "parameters"},
            f"steps[{index}]",
        )
    if value["finalOutputRef"] is not None and not isinstance(value["finalOutputRef"], str):
        raise InputError("PQV2_JSON_INVALID", "finalOutputRef", "Final output reference must be text or null")
    return value


def _bind_single_draft_source(
    draft: dict[str, Any], sources: list[dict[str, Any]], primary_source_id: str | None,
) -> bool:
    """Bind one invalid AI source reference to the explicitly selected source.

    This is deliberately narrow: it never guesses for a multi-source draft and
    still requires the selected source kind to match the requested operation.
    Authoritative IDs continue to come from the coordinator source catalog.
    """

    if not primary_source_id:
        return False
    source_map = {source["sourceId"]: source for source in sources}
    primary = source_map.get(primary_source_id)
    if primary is None:
        return False
    source_steps = [
        step for step in draft.get("steps", [])
        if isinstance(step, dict) and str(step.get("operationType", "")).startswith("source.")
    ]
    if len(source_steps) != 1:
        return False
    step = source_steps[0]
    parameters = step.get("parameters")
    if not isinstance(parameters, dict):
        return False
    expected_operation = (
        "source.workbookTable" if primary.get("kind") == "excelTable"
        else "source.usedRange" if primary.get("kind") == "usedRange" else None
    )
    if step.get("operationType") != expected_operation:
        return False
    changed = parameters.get("sourceId") != primary_source_id
    parameters["sourceId"] = primary_source_id
    return changed


def _normalize_steps(
    raw_steps: list[Any], final_ref: Any, sources: list[dict[str, Any]], *,
    draft: bool, existing_ids: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str | None, list[dict[str, str]], list[str]]:
    blockers: list[dict[str, str]] = []
    warnings: list[str] = []
    source_map = {source["sourceId"]: source for source in sources}
    refs: list[str] = []
    step_ids: dict[str, str] = {}
    for index, raw in enumerate(raw_steps):
        path = f"steps[{index}]"
        if not isinstance(raw, dict):
            blockers.append(_issue("V1", "PQV2_JSON_INVALID", path, path, "Step must be an object", "Create a structured step"))
            continue
        reference = raw.get("clientRef") if draft else raw.get("stepId")
        if not isinstance(reference, str) or (draft and not CLIENT_REF.fullmatch(reference)) or reference in refs:
            blockers.append(_issue("V2", "PQV2_ID_INVALID", path, str(reference), "Step reference is invalid or duplicated", "Use a unique step reference"))
            continue
        refs.append(reference)
        step_ids[reference] = (existing_ids or {}).get(reference, _random_id("stp")) if draft else reference
    ref_set = set(refs)
    graph: dict[str, list[str]] = {}
    for raw in raw_steps:
        if not isinstance(raw, dict): continue
        reference = raw.get("clientRef") if draft else raw.get("stepId")
        inputs = raw.get("inputs", [])
        raw_input_refs = [item if isinstance(item, str) else item.get("ref") if isinstance(item, dict) else None for item in inputs] if isinstance(inputs, list) else []
        graph[str(reference)] = [str(item) for item in raw_input_refs if item is not None]
        for item in raw_input_refs:
            if item not in ref_set:
                blockers.append(_issue("V3", "PQV2_DEPENDENCY_INVALID", "steps.inputs", str(item), "Input step does not exist", "Restore the producer step or choose another input"))
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting:
            blockers.append(_issue("V3", "PQV2_DEPENDENCY_CYCLE", "steps.inputs", node, "Dependency cycle detected", "Remove the circular dependency"))
            return
        if node in visited: return
        visiting.add(node)
        for dependency in graph.get(node, []):
            if dependency in graph: visit(dependency)
        visiting.remove(node)
        visited.add(node)
    for node in graph: visit(node)

    output_schemas: dict[str, list[dict[str, Any]]] = {}
    normalized: list[dict[str, Any]] = []
    position_by_ref = {reference: index for index, reference in enumerate(refs)}
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict): continue
        path = f"steps[{index}]"
        reference = raw.get("clientRef") if draft else raw.get("stepId")
        if reference not in step_ids: continue
        variable = raw.get("variableName")
        description = raw.get("actionDescription")
        operation_type = raw.get("operationType") if draft else (raw.get("operation") or {}).get("type")
        parameters = raw.get("parameters") if draft else (raw.get("operation") or {}).get("parameters")
        raw_inputs = raw.get("inputs", [])
        if not isinstance(variable, str) or not VARIABLE.fullmatch(variable) or variable.lower() in M_RESERVED:
            blockers.append(_issue("V2", "PQV2_VARIABLE_INVALID", path + ".variableName", str(variable), "Variable name must be unique PascalCase and not reserved", "Choose a PascalCase name"))
        if any(step.get("variableName") == variable for step in normalized):
            blockers.append(_issue("V2", "PQV2_VARIABLE_INVALID", path + ".variableName", str(variable), "Variable name is duplicated", "Choose a unique name"))
        if not isinstance(description, str) or not description.strip() or len(description) > 500:
            blockers.append(_issue("V1", "PQV2_JSON_INVALID", path + ".actionDescription", "description", "Action description is missing or too long", "Provide a concise description"))
        if operation_type not in OPERATION_ARITY:
            blockers.append(_issue("V7", "PQV2_OPERATION_UNSUPPORTED", path + ".operation", str(operation_type), "Operation is outside the Typed v1 catalog", "Use Advanced M or a supported operation"))
            continue
        input_refs = [item if isinstance(item, str) else item.get("ref") if isinstance(item, dict) else None for item in raw_inputs] if isinstance(raw_inputs, list) else []
        minimum, maximum = OPERATION_ARITY[operation_type]
        if not minimum <= len(input_refs) <= maximum:
            blockers.append(_issue("V3", "PQV2_DEPENDENCY_INVALID", path + ".inputs", operation_type, f"Operation requires {minimum}-{maximum} inputs", "Select the required input steps"))
        if any(item in position_by_ref and position_by_ref[item] >= index for item in input_refs):
            blockers.append(_issue("V3", "PQV2_DEPENDENCY_INVALID", path + ".inputs", str(input_refs), "Steps are not topologically ordered", "Move the producer before this step"))
        input_schemas = [output_schemas[item] for item in input_refs if item in output_schemas]
        if len(input_schemas) != len(input_refs):
            output_schema = deepcopy(input_schemas[0]) if input_schemas else []
            normalized_params = deepcopy(parameters) if isinstance(parameters, dict) else {}
        else:
            try:
                normalized_params, output_schema, operation_warnings = _normalize_operation(step_ids[reference], operation_type, parameters, input_schemas, source_map, path)
                warnings.extend(operation_warnings)
            except InputError as exc:
                gate = "V8" if exc.code == "PQV2_POLICY_VIOLATION" else "V7" if "UNSUPPORTED" in exc.code else "V6" if exc.code == "PQV2_TYPE_MISMATCH" else "V5" if "COLUMN" in exc.code else "V4" if "SOURCE" in exc.code else "V1"
                blockers.append(_issue(gate, exc.code, exc.path, str(reference), exc.detail, "Edit the step parameters or restore the required source/column"))
                output_schema = deepcopy(input_schemas[0]) if input_schemas else []
                normalized_params = deepcopy(parameters) if isinstance(parameters, dict) else {}
        output_schemas[reference] = output_schema
        normalized.append({
            "stepId": step_ids[reference], "position": index + 1,
            "variableName": variable if isinstance(variable, str) else f"Invalid{index + 1}",
            "actionDescription": description if isinstance(description, str) else "Invalid step",
            "operation": {"type": operation_type, "parameters": normalized_params},
            # Preserve unresolved references in a blocked revision so the repair
            # engine can explain and reconnect the exact broken edge.
            "inputs": [{"kind": "step", "ref": step_ids.get(item, item)} for item in input_refs if isinstance(item, str)],
            "outputContract": {"kind": "table", "schemaHash": "sha256:" + _digest(output_schema), "columns": output_schema},
        })
    final_step_id = step_ids.get(final_ref) if isinstance(final_ref, str) else None
    if final_step_id is None or final_ref not in output_schemas:
        blockers.append(_issue(
            "V9", "PQV2_FINAL_OUTPUT_NOT_TABLE", "finalOutputStepId", str(final_ref),
            "Planner did not select an existing final output step",
            "Keep the current final step or set final output to the last flat-table step",
        ))
    elif not output_schemas.get(final_ref) and not blockers:
        blockers.append(_issue(
            "V9", "PQV2_FINAL_OUTPUT_NOT_TABLE", "finalOutputStepId", str(final_ref),
            "The selected final step has no resolved output columns",
            "Repair its inputs before selecting it as final output",
        ))
    elif nested_columns := [
        column.get("name", "?")
        for column in output_schemas[final_ref]
        if column.get("inferredType") == "table"
    ]:
        blockers.append(_issue(
            "V9", "PQV2_NESTED_TABLE_NOT_EXPANDED", "finalOutputStepId", str(final_ref),
            "Final output still contains nested table column(s): " + ", ".join(nested_columns),
            "Add table.expandTableColumn and choose the joined fields before setting final output",
        ))
    return normalized, final_step_id, blockers, warnings
