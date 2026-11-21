"""Hand-computed behavioral oracles for the local Typed executor (no Excel)."""

from copy import deepcopy
from decimal import Inexact, getcontext, setcontext
import json
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.powerquery.typed.validation import _normalize_steps
from pbip_assistant.powerquery.typed_local import execute_plan


def literal(value, value_type=None):
    if value_type is None:
        value_type = "null" if value is None else "logical" if isinstance(value, bool) else "number" if isinstance(value, (int, float)) else "text"
    return {"kind": "literal", "valueType": value_type, "value": value}


def ref(name):
    return {"kind": "columnRef", "column": name}


def source(sid="t", names=("Key", "Amount", "Note"), types=("text", "number", "text"), kind="excelTable"):
    return {"sourceId": sid, "kind": kind, "objectName": sid,
            "columns": [{"columnId": sid + "_" + name, "name": name, "inferredType": typ,
                         "ordinal": i, "nullable": True} for i, (name, typ) in enumerate(zip(names, types))]}


def plan_for(operations=(), sources=None):
    sources = sources or [source()]
    raw = []
    for item in sources:
        operation = "source.workbookTable" if item["kind"] == "excelTable" else "source.usedRange"
        raw.append({"clientRef": item["sourceId"], "variableName": "Source" + str(len(raw)),
                    "actionDescription": "Read synthetic table", "operationType": operation,
                    "inputs": [], "parameters": {"sourceId": item["sourceId"]}})
    previous = sources[0]["sourceId"]
    for i, item in enumerate(operations):
        operation, params, *custom_inputs = item
        step_ref = "op" + str(i)
        raw.append({"clientRef": step_ref, "variableName": "Step" + str(i),
                    "actionDescription": "Synthetic operation", "operationType": "table." + operation,
                    "inputs": custom_inputs[0] if custom_inputs else [previous], "parameters": params})
        previous = step_ref
    steps, final, blockers, _ = _normalize_steps(raw, previous, sources, draft=True,
                                               existing_ids={s["clientRef"]: "stp_" + s["clientRef"] for s in raw})
    if blockers:
        raise AssertionError(blockers)
    return {"sources": sources, "steps": steps, "finalOutputStepId": final}


def table(rows, sid="t", header=None):
    result = {"sourceId": sid, "rows": rows}
    if header is not None:
        result["header"] = header
    return result


def merge_ops(kind="inner", source_name="Key"):
    return [("mergeTables", {"keyPairs": [{"leftColumn": source_name, "rightColumn": "Key"}],
                              "joinKind": kind, "nestedColumnName": "Matches"}, ["t", "r"]),
            ("expandTableColumn", {"nestedColumn": "Matches", "columns": [{"column": "Amount", "newName": "RightAmount"}]})]


def all_operations_fixture():
    """One actual graph containing all fifteen closed catalog operations."""
    sources = [source(), source("r", kind="usedRange")]
    operations = [
        ("appendTables", {"schemaMode": "strict"}, ["t", "r"]),
        ("filterRows", {"predicate": {"kind": "compare", "operator": "gt", "left": ref("Amount"), "right": literal(1)}}),
        ("selectColumns", {"columns": ["Key", "Amount", "Note"]}),
        ("removeColumns", {"columns": ["Note"]}),
        ("renameColumns", {"renames": [{"column": "Key", "newName": "Group"}]}),
        ("changeTypes", {"conversions": [{"column": "Amount", "targetType": "number"}]}),
        ("addColumn", {"newColumnName": "Double", "expression": {"kind": "arithmetic", "operator": "multiply", "left": ref("Amount"), "right": literal(2)}}),
        ("sortRows", {"keys": [{"column": "Group", "direction": "ascending"}]}),
        ("distinctRows", {"scope": "all"}),
        ("mergeTables", {"keyPairs": [{"leftColumn": "Group", "rightColumn": "Key"}], "joinKind": "inner", "nestedColumnName": "Matches"}, ["op8", "r"]),
        ("expandTableColumn", {"nestedColumn": "Matches", "columns": [{"column": "Amount", "newName": "RightAmount"}]}),
        ("groupRows", {"keyColumns": ["Group"], "aggregations": [{"function": "sum", "column": "Double", "outputName": "GroupTotal"}]}),
        ("aggregateRows", {"aggregations": [{"function": "sum", "column": "GroupTotal", "outputName": "Total"}]}),
    ]
    return plan_for(operations, sources), [table([["b", 2, "x"], ["a", 1, "x"]]), table([["a", 3, "x"], ["b", 4, "x"]], "r")]


class TypedLocalTests(unittest.TestCase):
    def run_op(self, op, params, rows, sources=None):
        return execute_plan(plan_for([(op, params)], sources), [table(rows)])["rows"]

    def add(self, expression, rows=None, policy="block", sources=None):
        return self.run_op("addColumn", {"newColumnName": "Result", "expression": expression, "onEvaluationError": policy},
                           [["a", 2, None]] if rows is None else rows, sources)

    def test_execute_plan_smoke_all_15_operations(self):
        plan, tables = all_operations_fixture()
        self.assertEqual(len({s["operation"]["type"] for s in plan["steps"]}), 15)
        self.assertEqual(execute_plan(plan, tables)["rows"], [["18"]])

    def test_source_workbook_table(self):
        self.assertEqual(execute_plan(plan_for(), [table([["a", 2, None]])]),
                         {"columns": [{"name": "Key", "type": "text"}, {"name": "Amount", "type": "number"}, {"name": "Note", "type": "text"}], "rows": [["a", "2", None]], "rowCount": 1, "fanOut": None})

    def test_source_used_range_empty(self):
        self.assertEqual(execute_plan(plan_for(sources=[source(kind="usedRange")]), [table([])])["rows"], [])

    def test_source_empty_keeps_schema(self):
        result = execute_plan(plan_for(), [table([])])
        self.assertEqual((result["rowCount"], len(result["columns"])), (0, 3))

    def test_source_binds_unique_name_and_header_order(self):
        self.assertEqual(execute_plan(plan_for(), [{"name": "t", "header": ["Amount", "Note", "Key"], "rows": [[2, None, "a"]]}])["rows"], [["a", "2", None]])

    def test_filter_null_and_case_sensitive_text(self):
        self.assertEqual(self.run_op("filterRows", {"predicate": {"kind": "compare", "operator": "eq", "left": ref("Key"), "right": literal("A")}}, [["a", 1, None], [None, 2, None], ["A", 3, None]]), [["A", "3", None]])

    def test_filter_empty(self):
        self.assertEqual(self.run_op("filterRows", {"predicate": literal(True)}, []), [])

    def test_filter_evaluation_error_policies(self):
        condition = {"kind": "compare", "operator": "gt", "left": {"kind": "safeDivide", "numerator": literal(1), "denominator": literal(0), "onZero": "error"}, "right": literal(0)}
        for policy, expected in [("keepRow", [["a", "1", None]]), ("dropRow", [])]:
            with self.subTest(policy=policy):
                self.assertEqual(self.run_op("filterRows", {"predicate": condition, "onEvaluationError": policy}, [["a", 1, None]]), expected)
        with self.assertRaises(InputError):
            self.run_op("filterRows", {"predicate": condition}, [["a", 1, None]])

    def test_select_preserves_upstream_order(self):
        self.assertEqual(self.run_op("selectColumns", {"columns": ["Note", "Key"]}, [["a", 1, None]]), [["a", None]])

    def test_select_empty_table(self):
        self.assertEqual(self.run_op("selectColumns", {"columns": ["Key"]}, []), [])

    def test_remove_columns_null(self):
        self.assertEqual(self.run_op("removeColumns", {"columns": ["Amount"]}, [[None, 1, "x"]]), [[None, "x"]])

    def test_rename_columns_preserves_rows(self):
        plan = plan_for([("renameColumns", {"renames": [{"column": "Key", "newName": "Renamed"}]})])
        result = execute_plan(plan, [table([[None, 1, "x"]])])
        self.assertEqual((result["columns"][0], result["rows"]), ({"name": "Renamed", "type": "text"}, [[None, "1", "x"]]))

    def test_rename_empty_table(self):
        self.assertEqual(self.run_op("renameColumns", {"renames": [{"column": "Key", "newName": "K"}]}, []), [])

    def test_change_types_decimal_integer_logical(self):
        sources = [source(types=("text", "text", "text"))]
        self.assertEqual(self.run_op("changeTypes", {"conversions": [{"column": "Key", "targetType": "logical"}, {"column": "Amount", "targetType": "integer"}]}, [["true", "2.5", None]], sources), [[True, "2", None]])

    def test_change_types_null(self):
        self.assertEqual(self.run_op("changeTypes", {"conversions": [{"column": "Amount", "targetType": "integer"}]}, [["x", None, None]]), [["x", None, None]])

    def test_change_types_invalid_date_null_warning(self):
        plan = plan_for([("changeTypes", {"conversions": [{"column": "Key", "targetType": "date"}]})])
        result = execute_plan(plan, [table([["bad-date", 1, None]])])
        self.assertEqual(result["rows"], [[None, "1", None]])
        self.assertEqual(result["warnings"], [{"code": "AF_EXECUTOR_DATE_NULL", "path": "stp_op0.t_Key"}])

    def test_change_types_explicit_culture(self):
        self.assertEqual(self.run_op("changeTypes", {"conversions": [{"column": "Key", "targetType": "number", "culture": "vi-VN"}]}, [["1.234,50", 1, None]]), [["1234.50", "1", None]])

    def test_change_types_temporal_catalog(self):
        cases = [("date", "2026-10-30", "2026-10-30"), ("datetime", "2026-10-30T12:00:00", "2026-10-30T12:00:00"), ("datetimezone", "2026-10-30T12:00:00+07:00", "2026-10-30T12:00:00+07:00"), ("time", "12:30:00", "12:30:00"), ("duration", "1.02:03:04", "1.02:03:04")]
        for typ, value, expected in cases:
            with self.subTest(typ=typ):
                self.assertEqual(self.run_op("changeTypes", {"conversions": [{"column": "Key", "targetType": typ}]}, [[value, 1, None]]), [[expected, "1", None]])

    def test_duration_sort_and_extrema_are_chronological(self):
        plan = plan_for([("changeTypes", {"conversions": [{"column": "Key", "targetType": "duration"}]}),
                         ("sortRows", {"keys": [{"column": "Key", "direction": "ascending"}]}),
                         ("aggregateRows", {"aggregations": [{"function": "min", "column": "Key", "outputName": "Minimum"}, {"function": "max", "column": "Key", "outputName": "Maximum"}]})])
        tables = [table([["10.00:00:00", 1, None], ["2.00:00:00", 2, None], ["-1.00:00:00", 3, None]])]
        sorted_plan = deepcopy(plan)
        sorted_plan["finalOutputStepId"] = "stp_op1"
        self.assertEqual(execute_plan(sorted_plan, tables)["rows"], [["-1.00:00:00", "3", None], ["2.00:00:00", "2", None], ["10.00:00:00", "1", None]])
        self.assertEqual(execute_plan(plan, tables)["rows"], [["-1.00:00:00", "10.00:00:00"]])

    def test_zoned_datetime_sort_and_compare_use_instant(self):
        plan = plan_for([("changeTypes", {"conversions": [{"column": "Key", "targetType": "datetimezone"}]}),
                         ("sortRows", {"keys": [{"column": "Key", "direction": "ascending"}]}),
                         ("addColumn", {"newColumnName": "Earlier", "expression": {"kind": "compare", "operator": "lt", "left": ref("Key"), "right": ref("Key")}})])
        self.assertEqual(execute_plan(plan, [table([["2026-10-30T02:00:00+00:00", 1, None], ["2026-10-30T08:00:00+07:00", 2, None]])])["rows"], [["2026-10-30T08:00:00+07:00", "2", None, False], ["2026-10-30T02:00:00+00:00", "1", None, False]])

    def test_add_column_arithmetic(self):
        self.assertEqual(self.add({"kind": "arithmetic", "operator": "multiply", "left": ref("Amount"), "right": literal(3)}), [["a", "2", None, "6"]])

    def test_add_column_null_arithmetic(self):
        self.assertEqual(self.add({"kind": "arithmetic", "operator": "add", "left": ref("Amount"), "right": literal(3)}, [["a", None, None]]), [["a", None, None, None]])

    def test_add_column_empty(self):
        self.assertEqual(self.add(literal(1), []), [])

    def test_add_column_evaluation_error_null(self):
        expression = {"kind": "safeDivide", "numerator": literal(1), "denominator": literal(0), "onZero": "error"}
        self.assertEqual(self.add(expression, policy="null"), [["a", "2", None, None]])
        with self.assertRaises(InputError):
            self.add(expression)

    def test_sort_stable_multiple_keys(self):
        self.assertEqual(self.run_op("sortRows", {"keys": [{"column": "Key", "direction": "ascending"}, {"column": "Amount", "direction": "descending"}]}, [["b", 1, "b"], ["a", 2, "first"], ["a", 2, "second"], ["a", 1, "last"]]), [["a", "2", "first"], ["a", "2", "second"], ["a", "1", "last"], ["b", "1", "b"]])

    def test_sort_null_and_ordinal_text(self):
        self.assertEqual(self.run_op("sortRows", {"keys": [{"column": "Key", "direction": "ascending"}]}, [["a", 1, None], ["Z", 2, None], [None, 3, None]]), [[None, "3", None], ["Z", "2", None], ["a", "1", None]])

    def test_distinct_first_row_and_null(self):
        self.assertEqual(self.run_op("distinctRows", {"scope": "columns", "columns": ["Key"]}, [[None, 1, "first"], ["a", 2, None], [None, 3, "last"]]), [[None, "1", "first"], ["a", "2", None]])

    def test_distinct_all(self):
        self.assertEqual(self.run_op("distinctRows", {"scope": "all"}, [["a", 1, None], ["a", 1, None], ["a", 2, None]]), [["a", "1", None], ["a", "2", None]])

    def test_distinct_empty(self):
        self.assertEqual(self.run_op("distinctRows", {"scope": "all"}, []), [])

    def test_group_sorted_with_null(self):
        self.assertEqual(self.run_op("groupRows", {"keyColumns": ["Key"], "aggregations": [{"function": "sum", "column": "Amount", "outputName": "Total"}]}, [["b", 2, None], ["a", 1, None], ["b", 3, None], [None, 4, None]]), [[None, "4"], ["a", "1"], ["b", "5"]])

    def test_group_empty_keys_present(self):
        self.assertEqual(self.run_op("groupRows", {"keyColumns": ["Key"], "aggregations": [{"function": "rowCount", "outputName": "Count"}]}, []), [])

    def test_aggregate_all_functions(self):
        aggs = [{"function": f, "outputName": f, **({} if f == "rowCount" else {"column": "Amount"})} for f in ["rowCount", "countNonNull", "countDistinct", "sum", "average", "min", "max"]]
        self.assertEqual(self.run_op("aggregateRows", {"aggregations": aggs}, [["a", 2, None], ["b", None, None], ["c", 2, None], ["d", 5, None]]), [["4", "3", "2", "9", "3", "2", "5"]])

    def test_average_empty_is_null(self):
        self.assertEqual(self.run_op("aggregateRows", {"aggregations": [{"function": "average", "column": "Amount", "outputName": "Average"}]}, []), [[None]])

    def test_aggregate_all_nulls(self):
        aggs = [{"function": f, "column": "Amount", "outputName": f} for f in ["sum", "average", "min", "max"]]
        self.assertEqual(self.run_op("aggregateRows", {"aggregations": aggs}, [["a", None, None]]), [[None, None, None, None]])

    def test_append_union_fills_null(self):
        sources = [source(), source("r", ("Key", "Extra"), ("text", "integer"))]
        plan = plan_for([("appendTables", {"schemaMode": "union"}, ["t", "r"])], sources)
        self.assertEqual(execute_plan(plan, [table([["a", 1, None]]), table([["b", 3]], "r")])["rows"], [["a", "1", None, None], ["b", None, None, "3"]])

    def test_append_strict_empty(self):
        plan = plan_for([("appendTables", {"schemaMode": "strict"}, ["t", "r"])], [source(), source("r")])
        self.assertEqual(execute_plan(plan, [table([]), table([["a", 1, None]], "r")])["rows"], [["a", "1", None]])

    def test_merge_reports_fan_out(self):
        plan = plan_for(merge_ops(), [source(), source("r")])
        result = execute_plan(plan, [table([["a", 1, None]]), table([["a", 2, None], ["a", 3, None]], "r")])
        self.assertEqual(result["rows"], [["a", "1", None, "2"], ["a", "1", None, "3"]])
        self.assertEqual(result["fanOut"], {"rowsBefore": 1, "rowsAfter": 2, "ratio": "2", "joins": [{"stepId": "stp_op0", "joinKind": "inner", "rowsBefore": 1, "nestedRowsAfter": 1, "rowsAfter": 2, "ratio": "2"}]})

    def test_merge_all_six_join_kinds(self):
        expected = {
            "inner": [["a", "1", None, "3"]],
            "leftOuter": [["a", "1", None, "3"], ["b", "2", None, None]],
            "rightOuter": [["a", "1", None, "3"], [None, None, None, "4"]],
            "fullOuter": [["a", "1", None, "3"], ["b", "2", None, None], [None, None, None, "4"]],
            "leftAnti": [["b", "2", None, None]],
            "rightAnti": [[None, None, None, "4"]],
        }
        for kind, rows in expected.items():
            with self.subTest(kind=kind):
                plan = plan_for(merge_ops(kind), [source(), source("r")])
                self.assertEqual(execute_plan(plan, [table([["a", 1, None], ["b", 2, None]]), table([["a", 3, None], ["c", 4, None]], "r")])["rows"], rows)

    def test_merge_duplicate_left_preserves_order(self):
        plan = plan_for(merge_ops(), [source(), source("r")])
        self.assertEqual(execute_plan(plan, [table([["b", 1, None], ["a", 2, None], ["b", 3, None]]), table([["a", 8, None], ["b", 9, None]], "r")])["rows"], [["b", "1", None, "9"], ["a", "2", None, "8"], ["b", "3", None, "9"]])

    def test_multiple_merges_keep_consistent_per_join_fan_out(self):
        operations = merge_ops() + [
            ("mergeTables", {"keyPairs": [{"leftColumn": "Key", "rightColumn": "Key"}], "joinKind": "inner", "nestedColumnName": "More"}, ["op1", "r"]),
            ("expandTableColumn", {"nestedColumn": "More", "columns": [{"column": "Amount", "newName": "MoreAmount"}]})]
        result = execute_plan(plan_for(operations, [source(), source("r")]), [table([["a", 1, None]]), table([["a", 2, None], ["a", 3, None]], "r")])
        self.assertEqual(result["rows"], [["a", "1", None, "2", "2"], ["a", "1", None, "2", "3"], ["a", "1", None, "3", "2"], ["a", "1", None, "3", "3"]])
        self.assertEqual((result["fanOut"]["rowsBefore"], result["fanOut"]["rowsAfter"], result["fanOut"]["ratio"]), (2, 4, "2"))
        self.assertEqual([(j["rowsBefore"], j["rowsAfter"], j["ratio"]) for j in result["fanOut"]["joins"]], [(1, 2, "2"), (2, 4, "2")])

    def test_merge_null_keys_match(self):
        plan = plan_for(merge_ops(), [source(), source("r")])
        self.assertEqual(execute_plan(plan, [table([[None, 1, None]]), table([[None, 2, None]], "r")])["rows"], [[None, "1", None, "2"]])

    def test_merge_empty_left_ratio_undefined(self):
        plan = plan_for(merge_ops("rightOuter"), [source(), source("r")])
        result = execute_plan(plan, [table([]), table([["a", 2, None]], "r")])
        self.assertEqual((result["rows"], result["fanOut"]["ratio"]), ([[None, None, None, "2"]], None))

    def test_expand_empty_inner(self):
        plan = plan_for(merge_ops(), [source(), source("r")])
        self.assertEqual(execute_plan(plan, [table([["a", 1, None]]), table([], "r")])["rows"], [])

    def test_expression_not_boolean_and_if_lazy(self):
        error = {"kind": "safeDivide", "numerator": literal(1), "denominator": literal(0), "onZero": "error"}
        condition = {"kind": "boolean", "operator": "and", "operands": [literal(True), {"kind": "not", "operand": literal(False)}]}
        self.assertEqual(self.add({"kind": "ifThenElse", "condition": condition, "then": literal(7), "else": error}), [["a", "2", None, "7"]])

    def test_expression_boolean_short_circuit(self):
        error = {"kind": "compare", "operator": "gt", "left": {"kind": "safeDivide", "numerator": literal(1), "denominator": literal(0), "onZero": "error"}, "right": literal(0)}
        self.assertEqual(self.add({"kind": "boolean", "operator": "or", "operands": [literal(True), error]}), [["a", "2", None, True]])

    def test_expression_coalesce_lazy(self):
        error = {"kind": "safeDivide", "numerator": literal(1), "denominator": literal(0), "onZero": "error"}
        self.assertEqual(self.add({"kind": "coalesce", "values": [literal(None), literal(9), error]}), [["a", "2", None, "9"]])

    def test_expression_safe_divide_policies(self):
        for denominator in [0, None]:
            for policy, expected in [("zero", "0"), ("null", None)]:
                with self.subTest(denominator=denominator, policy=policy):
                    self.assertEqual(self.add({"kind": "safeDivide", "numerator": literal(1), "denominator": literal(denominator), "onZero": policy}), [["a", "2", None, expected]])
        self.assertEqual(self.add({"kind": "safeDivide", "numerator": literal(1), "denominator": literal(4), "onZero": "error"}), [["a", "2", None, "0.25"]])

    def test_expression_all_function_calls(self):
        cases = [("text.trim", [literal(" x ")], "x"), ("text.upper", [literal("x")], "X"), ("text.lower", [literal("X")], "x"), ("text.length", [literal("abc")], "3"), ("number.round", [literal(2.5)], "2"), ("number.round", [literal(1.255), literal(2, "integer")], "1.26"), ("date.year", [literal("2026-10-30", "date")], "2026"), ("date.month", [literal("2026-10-30", "date")], "10"), ("date.day", [literal("2026-10-30", "date")], "30")]
        for function, args, expected in cases:
            with self.subTest(function=function):
                self.assertEqual(self.add({"kind": "functionCall", "function": function, "args": args}), [["a", "2", None, expected]])

    def test_expression_function_null(self):
        self.assertEqual(self.add({"kind": "functionCall", "function": "text.upper", "args": [literal(None)]}), [["a", "2", None, None]])

    def test_mixed_any_numeric_text_requires_explicit_conversion(self):
        sources = [source(types=("any", "any", "any"))]
        expressions = [
            {"kind": "arithmetic", "operator": "add", "left": ref("Amount"), "right": literal(1)},
            {"kind": "safeDivide", "numerator": ref("Amount"), "denominator": literal(2), "onZero": "null"},
            {"kind": "safeDivide", "numerator": literal(2), "denominator": ref("Amount"), "onZero": "null"},
            {"kind": "functionCall", "function": "number.round", "args": [ref("Amount")]},
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                with self.assertRaises(InputError) as error:
                    self.add(expression, [["a", "2", None]], sources=sources)
                self.assertEqual(error.exception.code, "AF_EXECUTOR_INVALID")
                self.assertEqual(self.add(expression, [["a", "2", None]], policy="null", sources=sources), [["a", "2", None, None]])
        for function in ["sum", "average"]:
            with self.subTest(function=function), self.assertRaises(InputError):
                self.run_op("aggregateRows", {"aggregations": [{"function": function, "column": "Amount", "outputName": "Total"}]}, [["a", "2", None]], sources)

    def test_mixed_any_invalid_numeric_filter_obeys_error_policy(self):
        expression = {"kind": "compare", "operator": "gt", "left": {"kind": "arithmetic", "operator": "add", "left": ref("Amount"), "right": literal(1)}, "right": literal(2)}
        sources = [source(types=("any", "any", "any"))]
        for policy, expected in [("keepRow", [["a", "2", None]]), ("dropRow", [])]:
            with self.subTest(policy=policy):
                self.assertEqual(self.run_op("filterRows", {"predicate": expression, "onEvaluationError": policy}, [["a", "2", None]], sources), expected)

    def test_date_functions_do_not_implicitly_parse_any_text(self):
        sources = [source(types=("any", "any", "any"))]
        for function in ["date.year", "date.month", "date.day"]:
            with self.subTest(function=function), self.assertRaises(InputError):
                self.add({"kind": "functionCall", "function": function, "args": [ref("Key")]}, [["2026-10-30", 1, None]], sources=sources)

    def test_mixed_any_relational_comparison_rejects_incompatible_types(self):
        sources = [source(types=("any", "any", "any"))]
        with self.assertRaises(InputError):
            self.add({"kind": "compare", "operator": "gt", "left": ref("Amount"), "right": literal(1)}, [["a", "2", None]], sources=sources)

    def test_text_comparisons_keep_compiler_explicit_text_from(self):
        sources = [source(types=("any", "any", "any"))]
        self.assertEqual(self.add({"kind": "compare", "operator": "startsWith", "left": ref("Key"), "right": literal("tr")}, [[True, 1, None]], sources=sources), [[True, "1", None, True]])
        self.assertEqual(self.add({"kind": "compare", "operator": "contains", "left": ref("Amount"), "right": literal("2")}, [["a", 12, None]], sources=sources), [["a", "12", None, True]])

    def test_expression_comparison_catalog(self):
        cases = [("eq", 2, 2, True), ("ne", 2, 3, True), ("gt", 3, 2, True), ("gte", 2, 2, True), ("lt", 2, 3, True), ("lte", 2, 2, True), ("contains", "ABC", "B", True), ("startsWith", "ABC", "A", True), ("endsWith", "ABC", "c", False), ("isNull", None, None, True), ("isNotNull", 2, None, True)]
        for operator, left, right, expected in cases:
            expression = {"kind": "compare", "operator": operator, "left": literal(left)}
            if operator not in {"isNull", "isNotNull"}:
                expression["right"] = literal(right)
            with self.subTest(operator=operator):
                self.assertEqual(self.add(expression), [["a", "2", None, expected]])

    def test_executor_is_deterministic(self):
        plan, tables = all_operations_fixture()
        before = deepcopy((plan, tables))
        first = json.dumps(execute_plan(plan, tables), sort_keys=True)
        self.assertEqual(first, json.dumps(execute_plan(plan, tables), sort_keys=True))
        self.assertEqual((plan, tables), before)

    def test_executor_money_uses_decimal(self):
        self.assertEqual(self.run_op("aggregateRows", {"aggregations": [{"function": "sum", "column": "Amount", "outputName": "Total"}]}, [["a", 0.1, None], ["b", 0.2, None]]), [["0.3"]])

    def test_executor_decimal_context_independent(self):
        context, original = getcontext(), getcontext().prec
        try:
            context.prec = 3
            sources = [source(types=("text", "text", "text"))]
            plan = plan_for([("changeTypes", {"conversions": [{"column": "Amount", "targetType": "number"}]}), ("aggregateRows", {"aggregations": [{"function": "sum", "column": "Amount", "outputName": "Total"}]})], sources)
            self.assertEqual(execute_plan(plan, [table([["a", "123456789012345678901234567890.01", None], ["b", "0.02", None]])])["rows"], [["123456789012345678901234567890.03"]])
            self.assertEqual(context.prec, 3)
        finally:
            context.prec = original

    def test_executor_decimal_traps_and_exponents_independent(self):
        original = getcontext().copy()
        try:
            getcontext().traps[Inexact] = True
            getcontext().Emax = 2
            getcontext().Emin = -2
            expression = {"kind": "safeDivide", "numerator": literal(1), "denominator": literal(3), "onZero": "error"}
            self.assertEqual(self.add(expression), [["a", "2", None, "0." + "3" * 100]])
            self.assertEqual(self.add({"kind": "arithmetic", "operator": "multiply", "left": literal(100), "right": literal(100)}), [["a", "2", None, "10000"]])
            self.assertTrue(getcontext().traps[Inexact])
            self.assertEqual((getcontext().Emax, getcontext().Emin), (2, -2))
        finally:
            setcontext(original)

    def test_executor_enforces_limits(self):
        with self.assertRaises(InputError) as error:
            execute_plan(plan_for(), [table([[None, None, None]] * 100_001)])
        self.assertEqual(error.exception.code, "AF_EXECUTOR_LIMIT")

    def test_executor_column_limit(self):
        src = source(names=tuple("c" + str(i) for i in range(257)), types=("text",) * 257)
        with self.assertRaises(InputError) as error:
            execute_plan({"sources": [src], "steps": [{}]}, [])
        self.assertEqual(error.exception.code, "AF_EXECUTOR_LIMIT")

    def test_executor_join_limit_before_allocation(self):
        plan = plan_for(merge_ops(), [source(), source("r")])
        with self.assertRaises(InputError) as error:
            execute_plan(plan, [table([["a", 1, None]] * 317), table([["a", 2, None]] * 317, "r")])
        self.assertEqual(error.exception.code, "AF_EXECUTOR_LIMIT")

    def test_executor_rejects_bad_shape(self):
        for plan in [None, {}, {"steps": [None], "sources": []}]:
            with self.subTest(plan=plan), self.assertRaises(InputError) as error:
                execute_plan(plan, [])
            self.assertEqual(error.exception.code, "AF_EXECUTOR_INVALID")

    def test_executor_rejects_wrong_row_width(self):
        with self.assertRaises(InputError) as error:
            execute_plan(plan_for(), [table([[1]])])
        self.assertEqual(error.exception.code, "AF_EXECUTOR_INVALID")

    def test_executor_rejects_sample_only(self):
        for extra in [{"sampleOnly": True}, {"totalRows": 100}]:
            with self.subTest(extra=extra), self.assertRaises(InputError):
                execute_plan(plan_for(), [{**table([["a", 1, None]]), **extra}])

    def test_executor_rejects_contract_tampering(self):
        plan = plan_for()
        plan["steps"][0]["outputContract"]["columns"][0]["name"] = "Changed"
        with self.assertRaises(InputError) as error:
            execute_plan(plan, [table([])])
        self.assertEqual(error.exception.code, "AF_EXECUTOR_INVALID")

    def test_executor_rejects_unexpanded_nested_output(self):
        plan = plan_for(merge_ops(), [source(), source("r")])
        plan["finalOutputStepId"] = "stp_op0"
        with self.assertRaises(InputError) as error:
            execute_plan(plan, [table([]), table([], "r")])
        self.assertEqual(error.exception.code, "AF_EXECUTOR_INVALID")

    def test_executor_rejects_invalid_numeric_without_raw_value_leak(self):
        with self.assertRaises(InputError) as error:
            execute_plan(plan_for(), [table([["a", "private-value", None]])])
        self.assertEqual(error.exception.code, "AF_EXECUTOR_INVALID")
        self.assertNotIn("private-value", str(error.exception))


if __name__ == "__main__":
    unittest.main()
