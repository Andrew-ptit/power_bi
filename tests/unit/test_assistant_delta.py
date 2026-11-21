"""Delta diagnostic WL7 tính từ raw/result và lineage của Spec synthetic."""

from copy import deepcopy
from decimal import Decimal
import hashlib
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_delta import changed_columns, compute_delta, null_profile
from pbip_assistant.sources.assistant_reconcile import build_reconciliation
from tests.support.paths import FIXTURES
from tests.unit.test_assistant_preview import marker, pipeline
from tests.unit.test_assistant_spec import load
from pbip_assistant.sources.assistant_preview import build_preview


def delta_for(data, scenario):
    return compute_delta(data[0][0]["tables"], data[-1], data[1], scenario=scenario)


class AssistantDeltaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {name: pipeline(name) for name in ("tp-fin", "tp-sales")}

    def test_fin_and_sales_delta_match_all_golden_numbers_and_lineage(self):
        for scenario, data in self.models.items():
            expected = load(scenario, "wl7_decision_record.json")["delta"]
            actual = delta_for(data, scenario)
            self.assertEqual(actual, expected)

    def test_deleting_result_row_changes_real_delta_and_control_total(self):
        data = self.models["tp-fin"]
        changed = deepcopy(data[-1])
        index = next(i for i, row in enumerate(changed["rows"]) if row[4] != 0)
        changed["rows"].pop(index)
        actual = compute_delta(data[0][0]["tables"], changed, data[1], scenario="tp-fin")
        self.assertEqual(actual["rowsOut"], len(data[-1]["rows"]) - 1)
        preview = build_preview(data[-1], data[1], data[0][1], sheet="PnL_Preview",
                                marker=marker(data[1], "PnL_Preview"))
        reconciliation = build_reconciliation(preview, data[1], data[0][0]["tables"], changed)
        self.assertFalse(reconciliation["controlTotalPassed"])
        self.assertFalse(reconciliation["passed"])

    def test_fin_blank_mapped_bucket_increases_logical_null_after(self):
        data = self.models["tp-fin"]
        changed = deepcopy(data[-1])
        changed["rows"][0][changed["columns"].index("pnlLine")] = "  "
        actual = compute_delta(data[0][0]["tables"], changed, data[1], scenario="tp-fin")
        self.assertEqual(actual["nullsAfter"], {"PartnerEntity": 1})
        self.assertEqual(actual["nullsBefore"], delta_for(data, "tp-fin")["nullsBefore"])

    def test_sales_blank_mapped_region_and_customer_count_are_measured(self):
        data = self.models["tp-sales"]
        for source, target in (("TerritoryID", "region"), ("CustomerID", "customerCount")):
            changed = deepcopy(data[-1])
            changed["rows"][0][changed["columns"].index(target)] = None
            with self.subTest(target=target):
                actual = compute_delta(data[0][0]["tables"], changed, data[1], scenario="tp-sales")
                self.assertEqual(actual["nullsAfter"][source], 1)
                other = "CustomerID" if source == "TerritoryID" else "TerritoryID"
                self.assertEqual(actual["nullsAfter"][other], 0)

    def test_null_profile_counts_cells_without_treating_zero_as_blank(self):
        self.assertEqual(null_profile(["text", "number"], [["", 0], [None, Decimal("0")],
                         [" \t", None], ["value", ""]]), {"text": 3, "number": 2})

    def test_added_empty_row_changes_rows_out_nulls_and_never_returns_fixed_delta(self):
        for scenario, data in self.models.items():
            changed = deepcopy(data[-1])
            changed["rows"].append([""] * len(changed["columns"]))
            actual = compute_delta(data[0][0]["tables"], changed, data[1], scenario=scenario)
            self.assertEqual(actual["rowsOut"], len(data[-1]["rows"]) + 1)
            self.assertTrue(all(value == 1 for value in actual["nullsAfter"].values()))

    def test_exact_source_duplicate_and_rows_in_are_counted_from_primary_table(self):
        for scenario, data in self.models.items():
            tables = deepcopy(data[0][0]["tables"])
            signature = "DebitCredit" if scenario == "tp-fin" else "DiscountPct"
            primary = next(table for table in tables if signature in table["header"])
            before = delta_for(data, scenario)
            primary["rows"].append(deepcopy(primary["rows"][0]))
            actual = compute_delta(tables, data[-1], data[1], scenario=scenario)
            self.assertEqual(actual["rowsIn"], before["rowsIn"] + 1)
            self.assertEqual(actual["duplicatesBefore"], before["duplicatesBefore"] + 1)

    def test_duplicates_after_use_grain_even_when_amount_values_differ(self):
        for scenario, data in self.models.items():
            changed = deepcopy(data[-1])
            duplicate = deepcopy(changed["rows"][0])
            duplicate[4 if scenario == "tp-fin" else 1] += Decimal("1")
            changed["rows"].append(duplicate)
            actual = compute_delta(data[0][0]["tables"], changed, data[1], scenario=scenario)
            self.assertEqual(actual["duplicatesAfter"], 1)

    def test_sales_nulls_before_measure_orders_while_rows_in_measure_order_items(self):
        data = self.models["tp-sales"]
        tables = deepcopy(data[0][0]["tables"])
        orders = next(table for table in tables if "Status" in table["header"])
        customer = orders["header"].index("CustomerID")
        orders["rows"][0][customer] = ""
        actual = compute_delta(tables, data[-1], data[1], scenario="tp-sales")
        self.assertEqual(actual["rowsIn"], delta_for(data, "tp-sales")["rowsIn"])
        self.assertEqual(actual["nullsBefore"]["CustomerID"], 1)

    def test_changed_columns_drop_only_lineage_of_removed_operation(self):
        for scenario, data in self.models.items():
            original = changed_columns(data[1])
            operations = (("normalize_sign", "DebitCredit→amountSigned"),
                          ("map_account", "AccountCode→accountMapped"),
                          ("lookup_fx", "Amount→amountVnd")) if scenario == "tp-fin" else (
                          ("line_revenue_net_returns", "Quantity×UnitPrice×DiscountPct→revenue"),
                          ("resolve_territory", "TerritoryID→region"),
                          ("join_customers", "CustomerID→customerBucket"))
            for operation, lineage in operations:
                draft = deepcopy(data[1])
                draft["steps"] = [step for step in draft["steps"] if step["params"]["operation"] != operation]
                with self.subTest(operation=operation):
                    self.assertEqual(changed_columns(draft), [entry for entry in original if entry != lineage])

    def test_lineage_is_step_derived_stable_and_independent_of_labels_or_step_ids(self):
        data = self.models["tp-fin"]
        changed = deepcopy(data[1])
        for index, step in enumerate(changed["steps"]):
            step["id"] = "renamed_" + str(index)
            step["label"] = "Nhãn thay đổi"
        changed["steps"].reverse()
        self.assertEqual(changed_columns(changed), changed_columns(data[1]))
        changed["steps"].append(deepcopy(changed["steps"][0]))
        self.assertEqual(changed_columns(changed), changed_columns(data[1]))

    def test_compute_delta_rejects_stale_or_modified_spec_without_granting_authority(self):
        data = self.models["tp-fin"]
        changed = deepcopy(data[1])
        changed["steps"][2]["label"] = "Đã thay đổi"
        with self.assertRaises(InputError):
            compute_delta(data[0][0]["tables"], data[-1], changed, scenario="tp-fin")

    def test_malformed_profiles_results_scenarios_and_operations_fail_closed(self):
        data = self.models["tp-fin"]
        for columns, rows in ((["a", "a"], [["x", "y"]]), (["a"], [["x", "y"]]),
                              (["a"], [[float("nan")]]), (["a"], [[True]])):
            with self.assertRaises(InputError):
                null_profile(columns, rows)
        for scenario, result in (("other", data[-1]), ([], data[-1]),
                                 ("tp-fin", {**data[-1], "raw": []}),
                                 ("tp-sales", data[-1])):
            with self.assertRaises(InputError):
                compute_delta(data[0][0]["tables"], result, data[1], scenario=scenario)
        for draft in ({}, {"steps": [None]}, {"steps": [{"params": {"operation": []}}]},
                      {"steps": [{"params": {"operation": "unknown"}}]}):
            with self.assertRaises(InputError):
                changed_columns(draft)

    def test_repeatability_and_mutable_output_do_not_change_any_input(self):
        for scenario, data in self.models.items():
            before = deepcopy(data)
            first = delta_for(data, scenario)
            self.assertEqual(first, delta_for(data, scenario))
            first["nullsAfter"].clear()
            first["changedColumns"].append("caller mutation")
            self.assertEqual(data, before)
            self.assertNotEqual(first, delta_for(data, scenario))

    def test_engine_offline_no_file_io_and_fixture_hash_mtime_unchanged(self):
        paths = [p for scenario in self.models for p in (FIXTURES / "assistant" / scenario / "source").rglob("*.csv")]
        paths += [FIXTURES / "assistant" / scenario / "wl1_snapshot.json" for scenario in self.models]
        state = lambda: {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths}
        before = state()
        expected = {scenario: delta_for(data, scenario) for scenario, data in self.models.items()}
        with patch("builtins.open", side_effect=AssertionError("Delta không được mở file")):
            with patch("pathlib.Path.open", side_effect=AssertionError("Delta không được mở file")):
                with patch.object(socket.socket, "connect", side_effect=AssertionError("Delta không được gọi mạng")):
                    for scenario, data in self.models.items():
                        self.assertEqual(delta_for(data, scenario), expected[scenario])
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
