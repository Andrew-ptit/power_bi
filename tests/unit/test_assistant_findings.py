"""Kiểm phép đo WL3 độc lập bằng neo, biến đổi dữ liệu và cổng dữ liệu lỗi."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, Inexact, localcontext
import hashlib
import json
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash, resolve
from pbip_assistant.sources.assistant_profile import build_snapshot
from pbip_assistant.sources.assistant_findings import formulas, measure_set, number, scenario_fx_basis
from tests.support.paths import FIXTURES


def scenario(name: str) -> dict:
    root = FIXTURES / "assistant" / name
    requests = [{"kind": "csv", "path": "source/" + path.name}
                for path in sorted((root / "source").glob("*.csv"))]
    if name == "tp-sales":
        requests.append({"kind": "folder", "path": "source/orders", "name": "Orders"})
    result = resolve({"root": root}, requests)
    if result["errors"] or result["requiresRename"]:
        raise AssertionError("Nguồn synthetic phải nạp được trước phép đo")
    return result


def table(ingested: dict, *fields: str) -> dict:
    matches = [raw for raw in ingested["tables"] if set(fields) <= set(raw["header"])]
    if len(matches) != 1:
        raise AssertionError("Bảng synthetic phải được nhận diện duy nhất từ schema")
    return matches[0]


def set_value(raw: dict, row: list, field: str, value: str) -> None:
    row[raw["header"].index(field)] = value


class AssistantFindingsTests(unittest.TestCase):
    def test_finance_anchors_are_computed_from_raw_source(self) -> None:
        ingested = scenario("tp-fin")
        found = measure_set(ingested["tables"], build_snapshot(ingested))
        expected = {
            "rows_raw": "31", "exact_duplicates": "1", "rows_deduped": "30",
            "key_collisions": "1", "key_collision_rows": "2", "intercompany_rows": "2",
            "intercompany_net_vnd": "4374000000", "control_total_raw": "16906900000",
            "control_total_deduped": "14206900000", "gross_actual": "43931000000",
            "rebate_actual": "-92000000", "net_revenue_actual": "43839000000",
            "net_revenue_budget": "45579600000", "variance": "-1740600000", "variance_pct": "-3.82",
            "cogs_actual": "-30083200000", "cogs_budget": "-30361800000", "opex_actual": "-3922900000",
            "opex_budget": "-3556700000", "gross_profit_actual": "13755800000",
            "gross_profit_budget": "15217800000", "gross_margin_actual_pct": "31.38",
            "gross_margin_budget_pct": "33.39", "gross_margin_delta_pp": "-2.01",
            "actual_usd": "1450000", "actual_vnd": "8604000000", "budget_usd": "1470000",
            "budget_vnd": "8565000000", "rate_actual_usd_average": "24300", "rate_budget_usd": "25180",
            "op": "-464600000", "fx": "-1276000000", "bridge_total": "-1740600000",
            "fx_share_pct": "73.31", "ic_excluded_effect_gross_profit": "-4374000000",
            "op_policy_b": "-1740600000", "fx_zero": "0", "scenario_ab_delta": "1276000000",
            "sp1_option_b_delta": "92000000", "sp2_option_b_delta": "1276000000",
            "sp3_option_b_delta": "4374000000", "sp4_option_b_delta": "2700000000",
            "sp5_option_b_delta": "324000000", "sp6_option_b_delta": "0", "sp8_option_b_delta": "0",
            "sp9_option_b_delta": "154000000",
        }
        for name, expected_value in expected.items():
            with self.subTest(measure=name):
                self.assertEqual(Decimal(found[name]), Decimal(expected_value), name)
        self.assertIsNone(found["sp7_option_b_delta"])
        self.assertIsNone(found["sp10_option_b_delta"])
        self.assertEqual(found["op"] + found["fx"], found["bridge_total"])
        self.assertEqual(found["bridge_total"], found["variance"])

    def test_sales_anchors_include_returns_cancelled_orphans_and_regions(self) -> None:
        ingested = scenario("tp-sales")
        found = measure_set(ingested["tables"], build_snapshot(ingested))
        expected = {"orders": "12", "order_lines": "24", "cancelled_orders": "2", "returned_orders": "1",
                    "orphan_customer_orders": "1", "orders_missing_territory": "3",
                    "revenue_all_orders": "162742500", "revenue_excluding_cancelled": "133942500",
                    "revenue_cancelled_excluded": "28800000", "return_lines_effect": "-4500000",
                    "region_central": "10620000", "region_north": "40880000", "region_south": "70542500",
                    "region_unknown": "11900000", "orphan_customer_revenue": "11900000",
                    "territory_fallback_revenue": "24152500"}
        self.assertEqual(set(found), set(expected))
        for name, expected_value in expected.items():
            self.assertEqual(Decimal(found[name]), Decimal(expected_value), name)
        self.assertEqual(sum((value for name, value in found.items() if name.startswith("region_")), Decimal(0)),
                         found["revenue_excluding_cancelled"])
        self.assertEqual(scenario_fx_basis(found), {"scenarios": [], "delta": None})

    def test_rebate_mutation_changes_engine_values_and_bridge_without_source_writes(self) -> None:
        ingested = scenario("tp-fin")
        original = measure_set(ingested["tables"], build_snapshot(ingested))
        changed = deepcopy(ingested)
        ledger = table(changed, "PostingDate", "DebitCredit")
        row = list(ledger["rows"][0])
        for field, value in {"DocNo": "MUTATION-REBATE", "LineNo": "1", "AccountCode": "511900",
                             "DebitCredit": "D", "Amount": "10000000", "Currency": "VND",
                             "PartnerEntity": ""}.items():
            set_value(ledger, row, field, value)
        ledger["rows"].append(row)
        changed_snapshot = build_snapshot(changed)
        changed_values = measure_set(changed["tables"], changed_snapshot)
        self.assertEqual(changed_values["rebate_actual"], Decimal("-102000000"))
        self.assertEqual(changed_values["net_revenue_actual"], original["net_revenue_actual"] - Decimal("10000000"))
        self.assertEqual(changed_values["sp1_option_b_delta"], Decimal("102000000"))
        self.assertEqual(changed_values["variance"], original["variance"] - Decimal("10000000"))
        self.assertEqual(changed_values["op"] + changed_values["fx"], changed_values["variance"])
        self.assertEqual(changed_values["fx"], original["fx"])
        self.assertNotEqual(changed_snapshot["snapshotHash"], build_snapshot(ingested)["snapshotHash"])
        self.assertEqual(len(table(ingested, "PostingDate", "DebitCredit")["rows"]), 31)

    def test_exact_duplicate_view_changes_control_raw_only(self) -> None:
        ingested = scenario("tp-fin")
        before = measure_set(ingested["tables"], build_snapshot(ingested))
        ledger = table(ingested, "PostingDate", "DebitCredit")
        ledger["rows"].append(list(ledger["rows"][0]))
        after = measure_set(ingested["tables"], build_snapshot(ingested))
        self.assertEqual(after["rows_raw"], before["rows_raw"] + 1)
        self.assertEqual(after["exact_duplicates"], before["exact_duplicates"] + 1)
        self.assertEqual(after["rows_deduped"], before["rows_deduped"])
        self.assertEqual(after["net_revenue_actual"], before["net_revenue_actual"])
        self.assertNotEqual(after["control_total_raw"], before["control_total_raw"])

    def test_budget_expense_sign_uses_pnl_group_and_budget_values_are_not_cached(self) -> None:
        ingested = scenario("tp-fin")
        before = measure_set(ingested["tables"], build_snapshot(ingested))
        accounts = table(ingested, "AccountCode", "AccountType", "PnlGroup")
        for row in accounts["rows"]:
            if row[accounts["header"].index("PnlGroup")] == "COGS":
                set_value(accounts, row, "AccountType", "Expense")
        after = measure_set(ingested["tables"], build_snapshot(ingested))
        self.assertEqual(after["cogs_budget"], before["cogs_budget"])
        budget = table(ingested, "Month", "AccountCode", "CostCenter", "Currency", "Amount")
        for row in budget["rows"]:
            if row[budget["header"].index("Month")] == "2026-09" and row[budget["header"].index("AccountCode")] == "511100":
                amount = Decimal(row[budget["header"].index("Amount")])
                set_value(budget, row, "Amount", format(amount + 1, "f"))
                break
        changed = measure_set(ingested["tables"], build_snapshot(ingested))
        self.assertNotEqual(changed["net_revenue_budget"], before["net_revenue_budget"])
        self.assertEqual(changed["op"] + changed["fx"], changed["variance"])

    def test_registry_covers_every_measure_and_has_no_numeric_result_payload(self) -> None:
        registry = formulas()
        ids = [item["formulaId"] for item in registry]
        self.assertEqual(len(ids), len(set(ids)))
        for item in registry:
            self.assertEqual(set(item), {"formulaId", "expression", "basis", "unit", "inputs"})
            self.assertEqual(item["basis"], "engine-decimal")
            self.assertTrue(item["expression"])
            self.assertTrue(item["inputs"])
        for name in ("tp-fin", "tp-sales"):
            ingested = scenario(name)
            found = measure_set(ingested["tables"], build_snapshot(ingested))
            self.assertTrue({"fm_" + key for key in found} <= set(ids))
        registry[0]["inputs"].append("changed")
        self.assertNotEqual(registry, formulas())

    def test_runtime_region_registry_is_pure_and_rejects_identifier_collisions(self) -> None:
        ingested = scenario("tp-sales")
        territories = table(ingested, "TerritoryID", "Region")
        set_value(territories, territories["rows"][0], "Region", "WEST")
        found = measure_set(ingested["tables"], build_snapshot(ingested))
        self.assertIn("region_west", found)
        self.assertIn("fm_region_west", {item["formulaId"] for item in formulas(found)})
        self.assertNotIn("fm_region_west", {item["formulaId"] for item in formulas()})
        with self.assertRaises(ValueError):
            formulas({"region_bad;code": Decimal(1)})
        set_value(territories, territories["rows"][1], "Region", "west")
        orders = table(ingested, "OrderID", "OrderDate", "Status")
        for index, row in enumerate(orders["rows"][:2]):
            set_value(orders, row, "TerritoryID", territories["rows"][index][territories["header"].index("TerritoryID")])
            set_value(orders, row, "Status", "Completed")
        with self.assertRaises(InputError):
            measure_set(ingested["tables"], build_snapshot(ingested))

    def test_decimal_context_does_not_round_money_or_leak_ambient_settings(self) -> None:
        ingested = scenario("tp-fin")
        snapshot = build_snapshot(ingested)
        expected = measure_set(ingested["tables"], snapshot)
        expected_scenarios = scenario_fx_basis(expected)
        with localcontext() as context:
            context.prec = 6
            context.traps[Inexact] = True
            self.assertEqual(measure_set(ingested["tables"], snapshot), expected)
            self.assertEqual(scenario_fx_basis(expected), expected_scenarios)
            self.assertEqual(number(expected["net_revenue_actual"]), "43839000000")
            self.assertEqual(context.prec, 6)
            self.assertTrue(context.traps[Inexact])
        ledger = table(ingested, "PostingDate", "DebitCredit")
        set_value(ledger, ledger["rows"][0], "Amount", "1E1000")
        with self.assertRaises(InputError) as error:
            measure_set(ingested["tables"], build_snapshot(ingested))
        self.assertEqual(error.exception.code, "AF_MISSING_DATA")

    def test_number_formatter_is_strict_finite_and_rounds_percent_half_up(self) -> None:
        self.assertEqual(number(Decimal("14206900000.00")), "14206900000")
        self.assertEqual(number(Decimal("-2.005"), "percentage_points"), "-2.01")
        self.assertEqual(number(Decimal("1.2"), "percent"), "1.20")
        self.assertEqual(number(Decimal("12.50"), "USD"), "12.5")
        for value in (True, 1.0, None, Decimal("NaN"), Decimal("Infinity"), Decimal("0.1")):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ValueError):
                    number(value)

    def test_fx_scenarios_preserve_variance_and_delta_recomputes(self) -> None:
        ingested = scenario("tp-fin")
        measures = measure_set(ingested["tables"], build_snapshot(ingested))
        scenario_result = scenario_fx_basis(measures)
        self.assertEqual([item["id"] for item in scenario_result["scenarios"]], ["A", "B"])
        values = [{value["name"]: Decimal(value["value"]) for value in item["values"]} for item in scenario_result["scenarios"]]
        self.assertEqual(values[0]["Op"] + values[0]["FX"], measures["variance"])
        self.assertEqual(values[1]["Op"] + values[1]["FX"], measures["variance"])
        self.assertEqual(Decimal(scenario_result["delta"]["value"]), abs(values[0]["FX"] - values[1]["FX"]))
        for altered in ({**measures, "fx_zero": Decimal(1)}, {"fx": Decimal(1)}, {**measures, "fx": Decimal("NaN")}):
            with self.assertRaises(ValueError):
                scenario_fx_basis(altered)

    def test_zero_revenue_denominators_remain_unknown_instead_of_fake_zero(self) -> None:
        ingested = scenario("tp-fin")
        ledger = table(ingested, "PostingDate", "DebitCredit")
        budget = table(ingested, "Month", "AccountCode", "CostCenter", "Currency", "Amount")
        for raw in (ledger, budget):
            for row in raw["rows"]:
                set_value(raw, row, "Amount", "0")
        found = measure_set(ingested["tables"], build_snapshot(ingested))
        for name in ("variance_pct", "gross_margin_actual_pct", "gross_margin_budget_pct", "gross_margin_delta_pp", "fx_share_pct"):
            self.assertIsNone(found[name], name)

    def test_invalid_rates_signs_amounts_and_unknown_prefixes_block(self) -> None:
        original = scenario("tp-fin")
        mutations = []
        changed = deepcopy(original)
        ledger = table(changed, "PostingDate", "DebitCredit")
        set_value(ledger, ledger["rows"][0], "DebitCredit", "unknown")
        mutations.append(changed)
        changed = deepcopy(original)
        ledger = table(changed, "PostingDate", "DebitCredit")
        set_value(ledger, ledger["rows"][0], "Amount", "NaN")
        mutations.append(changed)
        changed = deepcopy(original)
        ledger = table(changed, "PostingDate", "DebitCredit")
        set_value(ledger, ledger["rows"][0], "AccountCode", "999999")
        mutations.append(changed)
        changed = deepcopy(original)
        rates = table(changed, "CurrencyCode", "Month", "RateType", "Rate")
        duplicate = list(rates["rows"][0])
        set_value(rates, duplicate, "Rate", "99999")
        rates["rows"].append(duplicate)
        mutations.append(changed)
        for candidate in mutations:
            with self.assertRaises(InputError):
                measure_set(candidate["tables"], build_snapshot(candidate))

    def test_missing_used_average_blocks_but_missing_unused_closing_does_not(self) -> None:
        ingested = scenario("tp-fin")
        rates = table(ingested, "CurrencyCode", "Month", "RateType", "Rate")
        positions = {name: rates["header"].index(name) for name in ("CurrencyCode", "Month", "RateType")}
        rates["rows"] = [row for row in rates["rows"] if row[positions["RateType"]] != "closing"]
        before = measure_set(ingested["tables"], build_snapshot(ingested))
        self.assertEqual(before["net_revenue_actual"], Decimal("43839000000"))
        rates["rows"] = [row for row in rates["rows"] if not (row[positions["CurrencyCode"]] == "USD" and
            row[positions["Month"]] == "2026-09" and row[positions["RateType"]] == "average")]
        with self.assertRaises(InputError) as error:
            measure_set(ingested["tables"], build_snapshot(ingested))
        self.assertEqual(error.exception.code, "AF_MISSING_DATA")

    def test_stale_snapshot_raw_and_ambiguous_schema_fail_closed(self) -> None:
        ingested = scenario("tp-fin")
        snapshot = build_snapshot(ingested)
        changed = deepcopy(ingested)
        table(changed, "PostingDate", "DebitCredit")["rows"].pop()
        with self.assertRaises(ValueError):
            measure_set(changed["tables"], snapshot)
        duplicate = deepcopy(ingested["tables"][0])
        duplicate["name"] += "_extra"
        duplicate["sourceId"] = "src_000000000000"
        copied = deepcopy(ingested)
        copied["sources"].append({"id": duplicate["sourceId"], "name": "Extra.csv", "type": "csv", "origin": "Extra.csv", "hash": canonical_hash("extra"), "addedAt": "2026-10-26T09:00:00Z"})
        copied["tables"].append(duplicate)
        with self.assertRaises(InputError):
            measure_set(copied["tables"], build_snapshot(copied))

    def test_schema_based_renaming_reorder_and_input_immutability(self) -> None:
        ingested = scenario("tp-fin")
        snapshot = build_snapshot(ingested)
        before = deepcopy((ingested, snapshot))
        found = measure_set(ingested["tables"], snapshot)
        self.assertEqual((ingested, snapshot), before)
        self.assertEqual(measure_set(list(reversed(ingested["tables"])), snapshot), found)
        renamed = deepcopy(ingested)
        for index, raw in enumerate(renamed["tables"]):
            raw["name"] = "Renamed_" + str(index)
        self.assertEqual(measure_set(renamed["tables"], build_snapshot(renamed)), found)

    def test_engine_has_no_network_and_source_files_keep_bytes_and_mtimes(self) -> None:
        paths = [p for name in ("tp-fin", "tp-sales") for p in (FIXTURES / "assistant" / name / "source").rglob("*.csv")]
        state = lambda: {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths}
        before = state()
        for name in ("tp-fin", "tp-sales"):
            ingested = scenario(name)
            snapshot = build_snapshot(ingested)
            with patch.object(socket, "socket", side_effect=AssertionError("Engine phải cục bộ")):
                found = measure_set(ingested["tables"], snapshot)
                scenario_fx_basis(found)
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
