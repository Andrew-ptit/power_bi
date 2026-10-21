"""Deterministic M rendering and dependency/cache-key calculations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from ...errors import InputError
import json
from .model import (
    MAX_COMPILED_M_CHARS,
    TYPED_COMPILER_POLICY_VERSION,
    TYPED_SCHEMA_POLICY_VERSION,
    _digest,
)


def _m_text(value: str) -> str:
    return '"' + value.replace("#", "##").replace('"', '""').replace("\r", "#(cr)").replace("\n", "#(lf)").replace("\t", "#(tab)") + '"'


def _m_type(value: str) -> str:
    return {"any": "type any", "text": "type text", "number": "type number", "integer": "Int64.Type", "logical": "type logical", "date": "type date", "datetime": "type datetime", "datetimezone": "type datetimezone", "time": "type time", "duration": "type duration"}[value]


def _compile_expression(value: dict[str, Any], columns: dict[str, str], row: str = "_") -> str:
    kind = value["kind"]
    if kind == "literal":
        literal = value["value"]
        if literal is None: return "null"
        if isinstance(literal, bool): return "true" if literal else "false"
        if isinstance(literal, (int, float)): return json.dumps(literal, ensure_ascii=False)
        if value["valueType"] == "date": return f"Date.FromText({_m_text(literal)})"
        if value["valueType"] == "datetime": return f"DateTime.FromText({_m_text(literal)})"
        return _m_text(literal)
    if kind == "columnRef": return f"Record.Field({row}, {_m_text(columns[value['columnId']])})"
    if kind == "compare":
        left = _compile_expression(value["left"], columns, row)
        op = value["operator"]
        if op in {"isNull", "isNotNull"}: return f"({left} {'=' if op == 'isNull' else '<>'} null)"
        right = _compile_expression(value["right"], columns, row)
        if op in {"contains", "startsWith", "endsWith"}:
            fn = {"contains": "Text.Contains", "startsWith": "Text.StartsWith", "endsWith": "Text.EndsWith"}[op]
            return f"{fn}(Text.From({left}), Text.From({right}))"
        symbol = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
        return f"({left} {symbol} {right})"
    if kind == "arithmetic":
        symbol = {"add": "+", "subtract": "-", "multiply": "*"}[value["operator"]]
        return f"({_compile_expression(value['left'], columns, row)} {symbol} {_compile_expression(value['right'], columns, row)})"
    if kind == "boolean":
        symbol = " and " if value["operator"] == "and" else " or "
        return "(" + symbol.join(_compile_expression(item, columns, row) for item in value["operands"]) + ")"
    if kind == "not": return f"not ({_compile_expression(value['operand'], columns, row)})"
    if kind == "ifThenElse": return f"if {_compile_expression(value['condition'], columns, row)} then {_compile_expression(value['then'], columns, row)} else {_compile_expression(value['else'], columns, row)}"
    if kind == "coalesce":
        result = _compile_expression(value["values"][-1], columns, row)
        for item in reversed(value["values"][:-1]):
            compiled = _compile_expression(item, columns, row)
            result = f"if {compiled} <> null then {compiled} else {result}"
        return result
    if kind == "functionCall":
        fn = {"text.trim": "Text.Trim", "text.upper": "Text.Upper", "text.lower": "Text.Lower", "text.length": "Text.Length", "number.round": "Number.Round", "date.year": "Date.Year", "date.month": "Date.Month", "date.day": "Date.Day"}[value["function"]]
        return f"{fn}(" + ", ".join(_compile_expression(item, columns, row) for item in value["args"]) + ")"
    if kind == "safeDivide":
        numerator = _compile_expression(value["numerator"], columns, row)
        denominator = _compile_expression(value["denominator"], columns, row)
        fallback = {"error": 'error "Division by zero"', "null": "null", "zero": "0"}[value["onZero"]]
        return f"if {denominator} = 0 or {denominator} = null then {fallback} else {numerator} / {denominator}"
    raise InputError("PQV2_COMPILE_FAILED", "expression", f"Cannot compile expression kind {kind}")


def _source_preserving_output_names(plan: dict[str, Any]) -> list[str]:
    """Return the stable presentation order for a Typed table result.

    Typed v1 has no user-facing column-reorder operation.  A planner may
    normalize an existing column by removing it, adding a replacement, and
    renaming the replacement back to the original name.  Table.AddColumn puts
    that replacement at the end, but that implementation detail must not move
    an existing source column in the final result.  Source columns therefore
    retain workbook order; genuinely new columns follow in their reviewed
    output-contract order.
    """

    steps = plan.get("steps") if isinstance(plan, dict) else None
    sources = plan.get("sources") if isinstance(plan, dict) else None
    final_step_id = plan.get("finalOutputStepId") if isinstance(plan, dict) else None
    if not isinstance(steps, list) or not isinstance(sources, list):
        return []
    by_id = {
        step.get("stepId"): step for step in steps
        if isinstance(step, dict) and isinstance(step.get("stepId"), str)
    }
    final_step = by_id.get(final_step_id)
    if not isinstance(final_step, dict):
        return []

    included: set[str] = set()
    pending = [final_step_id]
    while pending:
        step_id = pending.pop()
        if step_id in included:
            continue
        step = by_id.get(step_id)
        if not isinstance(step, dict):
            continue
        included.add(step_id)
        for item in step.get("inputs", []):
            if isinstance(item, dict) and isinstance(item.get("ref"), str):
                pending.append(item["ref"])

    source_by_id = {
        source.get("sourceId"): source for source in sources
        if isinstance(source, dict) and isinstance(source.get("sourceId"), str)
    }
    source_columns: list[dict[str, str]] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("stepId") not in included:
            continue
        operation = step.get("operation")
        if not isinstance(operation, dict) or not str(operation.get("type", "")).startswith("source."):
            continue
        parameters = operation.get("parameters")
        source = source_by_id.get(parameters.get("sourceId") if isinstance(parameters, dict) else None)
        columns = source.get("columns") if isinstance(source, dict) else None
        if not isinstance(columns, list):
            continue
        ordered = sorted(
            (item for item in columns if isinstance(item, dict)),
            key=lambda item: item.get("ordinal", 0),
        )
        for column in ordered:
            name, column_id = column.get("name"), column.get("columnId")
            if (
                isinstance(name, str) and isinstance(column_id, str)
                and not any(item["columnId"] == column_id for item in source_columns)
            ):
                source_columns.append({"columnId": column_id, "name": name})

    final_columns = final_step.get("outputContract", {}).get("columns")
    if not isinstance(final_columns, list):
        return []
    usable_final = [
        item for item in final_columns
        if isinstance(item, dict)
        and isinstance(item.get("columnId"), str)
        and isinstance(item.get("name"), str)
    ]
    final_by_id = {item["columnId"]: item for item in usable_final}
    used_ids: set[str] = set()
    desired: list[str] = []
    for source_column in source_columns:
        # A rename preserves lineage, so the current name occupies the source
        # column's original slot.
        current = final_by_id.get(source_column["columnId"])
        if current is not None:
            desired.append(current["name"])
            used_ids.add(current["columnId"])
            continue
        # Remove/add/rename creates a new lineage ID.  Matching the unique
        # original source name restores only its layout slot, never its ID.
        recreated = [
            item for item in usable_final
            if item["columnId"] not in used_ids and item["name"] == source_column["name"]
        ]
        if len(recreated) == 1:
            desired.append(recreated[0]["name"])
            used_ids.add(recreated[0]["columnId"])
    desired.extend(item["name"] for item in usable_final if item["columnId"] not in used_ids)
    return desired


def compile_m(plan: dict[str, Any], *, enforce_source_order: bool = False) -> str:
    from .registry import OPERATION_REGISTRY

    steps_by_id = {step["stepId"]: step for step in plan["steps"]}
    step_names = {step_id: step["variableName"] for step_id, step in steps_by_id.items()}
    final_step = next(
        (step for step in plan["steps"] if step["stepId"] == plan.get("finalOutputStepId")),
        None,
    )
    if final_step is not None:
        nested_columns = [
            column.get("name", "?")
            for column in final_step.get("outputContract", {}).get("columns", [])
            if column.get("inferredType") == "table"
        ]
        if nested_columns:
            raise InputError(
                "PQV2_NESTED_TABLE_NOT_EXPANDED", "finalOutputStepId",
                "Final output still contains nested table column(s): " + ", ".join(nested_columns),
            )
    lines = []
    source_by_id = {source["sourceId"]: source for source in plan["sources"]}
    for step in plan["steps"]:
        operation = step["operation"]
        operation_type, params = operation["type"], operation["parameters"]
        inputs = [step_names[item["ref"]] for item in step["inputs"]]
        input_columns = {}
        for input_ref in step["inputs"]:
            producer = steps_by_id[input_ref["ref"]]
            input_columns.update({item["columnId"]: item["name"] for item in producer["outputContract"]["columns"]})
        specification = OPERATION_REGISTRY.get(operation_type)
        if specification is None:
            raise InputError("PQV2_COMPILE_FAILED", step["stepId"], "Operation has no compiler template")
        expression = specification.compile(
            operation_type, params, inputs, input_columns, step, steps_by_id, source_by_id,
        )
        lines.append(f"    {step['variableName']} = {expression}")
    final_name = step_names.get(plan["finalOutputStepId"])
    if final_name is None:
        raise InputError("PQV2_FINAL_OUTPUT_NOT_TABLE", "finalOutputStepId", "Final output step is missing")
    final_expression = final_name
    if enforce_source_order:
        desired_names = _source_preserving_output_names(plan)
        final_step = steps_by_id[plan["finalOutputStepId"]]
        contract_names = [item["name"] for item in final_step["outputContract"]["columns"]]
        if desired_names and desired_names != contract_names:
            final_expression = (
                f"Table.ReorderColumns({final_name}, "
                "{" + ", ".join(_m_text(name) for name in desired_names) + "})"
            )
    code = "let\n" + ",\n".join(lines) + f"\nin\n    {final_expression}"
    if len(code) > MAX_COMPILED_M_CHARS:
        raise InputError("PQV2_COMPILED_M_LIMIT", "steps", "Compiled M exceeds 16000 characters")
    if any(token in code for token in ("Web.Contents", "File.Contents", "Odbc.", "Sql.Database")):
        raise InputError("PQV2_POLICY_VIOLATION", "steps", "Typed compiler produced a forbidden connector")
    return code


def dependency_closure_steps(plan: dict[str, Any], selected_step_id: str) -> list[dict[str, Any]]:
    """Return the selected step's transitive inputs in the plan's stable topo order."""

    steps = plan.get("steps") if isinstance(plan, dict) else None
    if not isinstance(steps, list):
        raise InputError("TSD_GRAPH_INVALID", "steps", "Typed step graph is missing")
    by_id = {
        step.get("stepId"): step for step in steps
        if isinstance(step, dict) and isinstance(step.get("stepId"), str)
    }
    if selected_step_id not in by_id:
        raise InputError("TSD_STEP_NOT_FOUND", "selectedStepId", "Selected step does not belong to this revision")
    if len(by_id) != len(steps):
        raise InputError("TSD_GRAPH_INVALID", "steps", "Typed step graph contains duplicate or invalid IDs")
    visiting: set[str] = set()
    included: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise InputError("TSD_GRAPH_INVALID", step_id, "Typed step graph contains a dependency cycle")
        if step_id in included:
            return
        step = by_id.get(step_id)
        if step is None:
            raise InputError("TSD_GRAPH_INVALID", step_id, "Typed step dependency is missing")
        visiting.add(step_id)
        inputs = step.get("inputs")
        if not isinstance(inputs, list):
            raise InputError("TSD_GRAPH_INVALID", step_id, "Typed step inputs are invalid")
        for item in inputs:
            if not isinstance(item, dict) or item.get("kind") != "step" or not isinstance(item.get("ref"), str):
                raise InputError("TSD_GRAPH_INVALID", step_id, "Typed step input is invalid")
            visit(item["ref"])
        visiting.remove(step_id)
        included.add(step_id)

    visit(selected_step_id)
    closure = [step for step in steps if step["stepId"] in included]
    positions = {step["stepId"]: index for index, step in enumerate(closure)}
    for step in closure:
        if any(positions[item["ref"]] >= positions[step["stepId"]] for item in step["inputs"]):
            raise InputError("TSD_GRAPH_INVALID", step["stepId"], "Typed steps are not in topological order")
    return deepcopy(closure)


def compile_m_to_step(plan: dict[str, Any], selected_step_id: str) -> tuple[str, list[dict[str, Any]]]:
    """Compile an immutable diagnostic prefix whose `in` is the selected step."""

    closure = dependency_closure_steps(plan, selected_step_id)
    used_source_ids = {
        step["operation"]["parameters"]["sourceId"]
        for step in closure if step["operation"]["type"].startswith("source.")
    }
    prefix = {
        "sources": [
            deepcopy(source) for source in plan.get("sources", [])
            if source.get("sourceId") in used_source_ids
        ],
        "steps": closure,
        "finalOutputStepId": selected_step_id,
    }
    return compile_m(prefix, enforce_source_order=True), closure


def diagnostic_step_cache_keys(
    plan: dict[str, Any], source_fingerprint: str, selected_step_id: str | None = None,
) -> dict[str, dict[str, str]]:
    """Derive deterministic keys; ordered inputs preserve merge/append semantics."""

    keys: dict[str, dict[str, str]] = {}
    target = selected_step_id or plan["finalOutputStepId"]
    for step in dependency_closure_steps(plan, target):
        operation = step["operation"]
        params_hash = "sha256:" + _digest({
            "operationType": operation["type"],
            "parameters": operation["parameters"],
            "compilerPolicyVersion": TYPED_COMPILER_POLICY_VERSION,
        })
        if operation["type"].startswith("source."):
            ordered_inputs = [{
                "sourceId": operation["parameters"]["sourceId"],
                "sourceFingerprint": source_fingerprint,
            }]
        else:
            ordered_inputs = [keys[item["ref"]]["stepCacheKey"] for item in step["inputs"]]
        input_version = "sha256:" + _digest(ordered_inputs)
        step_cache_key = "sha256:" + _digest({
            "stepId": step["stepId"], "inputVersion": input_version,
            "paramsHash": params_hash,
            "schemaPolicyVersion": TYPED_SCHEMA_POLICY_VERSION,
        })
        keys[step["stepId"]] = {
            "paramsHash": params_hash, "inputVersion": input_version,
            "stepCacheKey": step_cache_key,
        }
    return keys


def _compile_source_workbook_table(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    source = source_by_id[params["sourceId"]]
    object_name = source.get("objectName", source.get("runtimeAlias"))
    expression = f"Excel.CurrentWorkbook(){{[Name={_m_text(object_name)}]}}[Content]"
    return expression


def _compile_table_filter_rows(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    predicate = _compile_expression(params["predicate"], input_columns)
    policy = params["onEvaluationError"]
    if policy != "block": predicate = f"try {predicate} otherwise {'true' if policy == 'keepRow' else 'false'}"
    expression = f"Table.SelectRows({inputs[0]}, each {predicate})"
    return expression


def _compile_table_select_columns(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    expression = f"Table.SelectColumns({inputs[0]}, {{{', '.join(_m_text(input_columns[item]) for item in params['columnIds'])}}})"
    return expression


def _compile_table_remove_columns(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    expression = f"Table.RemoveColumns({inputs[0]}, {{{', '.join(_m_text(input_columns[item]) for item in params['columnIds'])}}})"
    return expression


def _compile_table_rename_columns(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    pairs = ", ".join("{" + _m_text(input_columns[item["columnId"]]) + ", " + _m_text(item["newName"]) + "}" for item in params["renames"])
    expression = f"Table.RenameColumns({inputs[0]}, {{{pairs}}})"
    return expression


def _compile_table_change_types(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    pairs = ", ".join("{" + _m_text(input_columns[item["columnId"]]) + ", " + _m_type(item["targetType"]) + "}" for item in params["conversions"])
    cultures = {item.get("culture") for item in params["conversions"] if item.get("culture")}
    culture = ", " + _m_text(next(iter(cultures))) if len(cultures) == 1 else ""
    expression = f"Table.TransformColumnTypes({inputs[0]}, {{{pairs}}}{culture})"
    return expression


def _compile_table_add_column(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    compiled = _compile_expression(params["expression"], input_columns)
    if params["onEvaluationError"] == "null": compiled = f"try {compiled} otherwise null"
    expression = f"Table.AddColumn({inputs[0]}, {_m_text(params['newColumnName'])}, each {compiled}, {_m_type(params['dataType'])})"
    return expression


def _compile_table_sort_rows(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    keys = ", ".join("{" + _m_text(input_columns[item["columnId"]]) + ", " + ("Order.Ascending" if item["direction"] == "ascending" else "Order.Descending") + "}" for item in params["keys"])
    expression = f"Table.Sort({inputs[0]}, {{{keys}}})"
    return expression


def _compile_table_distinct_rows(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    columns = ", {{{}}}".format(", ".join(_m_text(input_columns[item]) for item in params["columnIds"])) if params["scope"] == "columns" else ""
    expression = f"Table.Distinct({inputs[0]}{columns})"
    return expression


def _compile_table_group_rows(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    keys = "{" + ", ".join(_m_text(input_columns[item]) for item in params["keyColumnIds"]) + "}"
    aggregations = []
    for item in params["aggregations"]:
        function = item["function"]
        if function == "rowCount": body, result_type = "Table.RowCount(_)", "Int64.Type"
        else:
            column_name = _m_text(input_columns[item["columnId"]])
            body = {
                "countNonNull": f"List.NonNullCount(Table.Column(_, {column_name}))",
                "countDistinct": f"List.Count(List.Distinct(List.RemoveNulls(Table.Column(_, {column_name}))))",
                "sum": f"List.Sum(Table.Column(_, {column_name}))",
                "average": f"List.Average(Table.Column(_, {column_name}))",
                "min": f"List.Min(Table.Column(_, {column_name}))",
                "max": f"List.Max(Table.Column(_, {column_name}))",
            }[function]
            result_type = "type any"
        aggregations.append("{" + _m_text(item["outputName"]) + ", each " + body + ", " + result_type + "}")
    expression = f"Table.Group({inputs[0]}, {keys}, {{{', '.join(aggregations)}}})"
    return expression


def _compile_table_append_tables(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    expression = f"Table.Combine({{{', '.join(inputs)}}})"
    return expression


def _compile_table_merge_tables(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    left_keys = "{" + ", ".join(_m_text(input_columns[item["leftColumnId"]]) for item in params["keyPairs"]) + "}"
    # Resolve right-side IDs from the second producer rather than the merged input map.
    right_step = steps_by_id[step["inputs"][1]["ref"]]
    right_columns = {item["columnId"]: item["name"] for item in right_step["outputContract"]["columns"]}
    right_keys = "{" + ", ".join(_m_text(right_columns[item["rightColumnId"]]) for item in params["keyPairs"]) + "}"
    join = {"inner": "JoinKind.Inner", "leftOuter": "JoinKind.LeftOuter", "rightOuter": "JoinKind.RightOuter", "fullOuter": "JoinKind.FullOuter", "leftAnti": "JoinKind.LeftAnti", "rightAnti": "JoinKind.RightAnti"}[params["joinKind"]]
    expression = f"Table.NestedJoin({inputs[0]}, {left_keys}, {inputs[1]}, {right_keys}, {_m_text(params['nestedColumnName'])}, {join})"
    return expression


def _compile_table_expand_table_column(operation_type: str, params: dict[str, Any], inputs: list[str],
    input_columns: dict[str, str], step: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]], source_by_id: dict[str, dict[str, Any]],
) -> str:
    nested_name = input_columns[params["nestedColumnId"]]
    source_names = ", ".join(_m_text(item["sourceName"]) for item in params["columns"])
    new_names = ", ".join(_m_text(item["newName"]) for item in params["columns"])
    expression = f"Table.ExpandTableColumn({inputs[0]}, {_m_text(nested_name)}, {{{source_names}}}, {{{new_names}}})"
    return expression
