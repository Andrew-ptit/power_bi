"""Hợp đồng dữ liệu Assistant WL1–WL7; không kiểm chứng runtime Excel/Power BI."""
from __future__ import annotations

from collections import Counter
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from tests.support import assistant_fin, assistant_sales, assistant_variants
from tests.support.json_schema_oracle import validate, validate_or_raise
from tests.support.paths import FIXTURES

ROOT = FIXTURES / "assistant"
SCENARIOS = ("tp-fin", "tp-sales")
ARTIFACTS = ("formulas.json", "wl1_snapshot.json", "wl2_understand.json", "wl3_brief.json", "wl3_decisions.json", "wl4_execution_spec.json", "wl5_preview.json", "wl5_reconciliation.json", "wl6_apply.json", "wl7_decision_record.json")
FIN_SOURCES = ("Entity.csv", "Currency.csv", "CoA.csv", "CostCenter.csv", "FX_Rates_2026.csv", "GL_Actuals_2026-09.csv", "Budget_2026.csv")
SALES_SOURCES = ("Territory.csv", "Customers.csv", "Products.csv", "OrderItems.csv", "orders/Orders_2026-07.csv", "orders/Orders_2026-08.csv", "orders/Orders_2026-09.csv")
SCHEMAS = ("snapshot", "understand", "brief", "formulas", "execution_spec", "preview", "reconciliation", "apply", "decision_record", "source", "table", "column", "role", "relationship", "assumption", "subproblem", "step", "insight_case", "variant")
VARIANTS = {
    "fin_reconcile_control_drift.json": "wl5_reconciliation.json",
    "fin_rate_missing_blocker.json": "wl2_understand.json",
    "fin_rate_closing_missing_warning.json": "wl2_understand.json",
    "fin_spec_invalidated.json": "wl4_execution_spec.json",
    "fin_record_stale.json": "wl7_decision_record.json",
    "wl1_csv_ambiguous.json": "wl1_snapshot.json",
    "wl1_connector_blocked.json": "wl1_snapshot.json",
    "wl1_duplicate_table_name.json": "wl1_snapshot.json",
}
HASH_FIELDS = dict(zip(ARTIFACTS, ("hash", "snapshotHash", "understandHash", "briefHash", "decisionsHash", "fingerprint", "previewHash", "reconcileHash", "hash", "hash"), strict=True))
HASH_FIELDS.update({"wl3_brief_unresolved.json": "briefHash", "wl3_decisions_unresolved.json": "decisionsHash"})
LABELS = {"unverified", "assumed", "out_of_scope", "stale"}
FIN_ANCHORS = {
    "rowsRaw": "31", "exactDuplicates": "1", "rowsDeduped": "30", "keyCollisionGroups": "1", "keyCollisionRows": "2",
    "unmappedAccounts": ["511150", "632150", "641950"],
    "orphanCostCenters": ["CC-901", "CC-902", "CC-903", "CC-904", "CC-905", "CC-906", "CC-907"],
    "intercompanyRows": "2", "intercompanyNetVnd": "4374000000", "controlTotalRawSource": "16906900000", "controlTotalSource": "14206900000",
    "grossActual": "43931000000", "rebateActual": "-92000000", "netRevenueActual": "43839000000", "netRevenueBudget": "45579600000",
    "variance": "-1740600000", "variancePct": "-3.82", "cogsActual": "-30083200000", "cogsBudget": "-30361800000",
    "opexActual": "-3922900000", "opexBudget": "-3556700000", "grossProfitActual": "13755800000", "grossProfitBudget": "15217800000",
    "grossMarginActualPct": "31.38", "grossMarginBudgetPct": "33.39", "grossMarginDeltaPp": "-2.01",
    "actualUsd": "1450000", "actualVnd": "8604000000", "budgetUsd": "1470000", "budgetVnd": "8565000000",
    "rateActualUsdAverage": "24300", "rateBudgetUsd": "25180", "op": "-464600000", "fx": "-1276000000", "bridgeTotal": "-1740600000",
    "fxSharePct": "73.31", "icExcludedEffectGrossProfit": "-4374000000",
}
SALES_ANCHORS = {
    "orders": "12", "orderLines": "24", "cancelledOrders": "2", "returnedOrders": "1", "orphanCustomerOrders": "1", "ordersMissingTerritory": "3",
    "revenueAllOrders": "162742500", "revenueExcludingCancelled": "133942500", "revenueCancelledExcluded": "28800000", "returnLinesEffect": "-4500000",
    "regionTotals": {"CENTRAL": "10620000", "NORTH": "40880000", "SOUTH": "70542500", "UNKNOWN": "11900000"},
}
FIN_ALIASES = {"rowsRaw": "rows_raw", "exactDuplicates": "exact_duplicates", "rowsDeduped": "rows_deduped", "keyCollisionGroups": "key_collisions", "keyCollisionRows": "key_collision_rows", "controlTotalRawSource": "control_total_raw", "controlTotalSource": "control_total_deduped"}
FIN_SP = (("assumed", "pack"), ("assumed", "pack"), ("assumed", "pack"), ("verified", "data"), ("inferred", "data"), ("inferred", "data"), ("missing_data", "data"), ("inferred", "data"), ("conflict", "data"), ("missing_data", "data"))
SALES_SP = (("assumed", "data"), ("assumed", "data"), ("conflict", "data"), ("inferred", "data"), ("missing_data", "data"))


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def walk(value: object, path: str = "$"):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from walk(child, path + "." + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def csv_data(scenario: str, name: str) -> list[dict[str, str]]:
    with (ROOT / scenario / "source" / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def schema_for(name: str) -> dict:
    if "decisions" in name:
        brief = load("schema/brief.schema.json")
        return {"$ref": "#/$defs/decisionsDocument", "$defs": brief["$defs"]}
    stem = name.removesuffix(".json")
    if stem.startswith("wl"):
        stem = stem.split("_", 1)[1].removesuffix("_unresolved")
    return load(f"schema/{stem}.schema.json")


def documents():
    for scenario in SCENARIOS:
        for name in ARTIFACTS:
            yield f"{scenario}/{name}", name, load(f"{scenario}/{name}")
    for name in ("wl3_brief_unresolved.json", "wl3_decisions_unresolved.json"):
        yield f"tp-unknown/{name}", name, load(f"tp-unknown/{name}")
    for name, base in VARIANTS.items():
        yield f"variants/{name}", base, load(f"variants/{name}")


class AssistantFixtureContractTests(unittest.TestCase):
    def eq(self, actual: object, expected: object, field: str) -> None:
        self.assertEqual(actual, expected, field)

    def check(self, condition: object, field: str) -> None:
        self.assertTrue(condition, field)

    def test_01_exact_file_tree_and_json_serialization(self) -> None:
        expected = {"manifest.json"} | {f"schema/{name}.schema.json" for name in SCHEMAS}
        for scenario, sources in (("tp-fin", FIN_SOURCES), ("tp-sales", SALES_SOURCES)):
            expected.update(f"{scenario}/{name}" for name in ARTIFACTS)
            expected.update(f"{scenario}/source/{name}" for name in sources)
        expected.update(f"variants/{name}" for name in VARIANTS)
        expected.update(f"tp-unknown/{name}" for name in ("wl3_brief_unresolved.json", "wl3_decisions_unresolved.json"))
        expected.update(f"model_view/{name}" for name in (
            "star_model_valid.json", "per_sheet_valid.json", "single_table_valid.json", "invalid_examples.json"))
        actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
        self.eq(actual, expected, "assistant tree: thiếu/thừa file so với contract")
        for relative in sorted(expected):
            if relative.endswith(".json"):
                with self.subTest(file=relative):
                    self.eq((ROOT / relative).read_bytes(), (json.dumps(load(relative), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"), relative + ": UTF8/no BOM/LF/sort_keys")

    def test_02_schemas_are_closed_and_validate_every_artifact(self) -> None:
        count = 0
        for name in SCHEMAS:
            schema = load(f"schema/{name}.schema.json")
            self.eq(schema["$schema"], "https://json-schema.org/draft/2020-12/schema", name + ": draft")
            for path, rule in walk(schema):
                if rule.get("type") == "object":
                    count += 1
                    self.eq(rule.get("additionalProperties"), False, name + path + ": closed")
                    self.eq(set(rule.get("required", [])), set(rule.get("properties", {})), name + path + ": required-all")
        self.check(count > len(SCHEMAS), "schema: kiểm cả object lồng nhau")
        for relative, name, document in documents():
            with self.subTest(file=relative):
                self.eq(validate(document, schema_for(name)), [], relative + ": schema")
                if relative.startswith("variants/"):
                    self.eq(validate({key: document[key] for key in ("variantOf", "variantReason")}, load("schema/variant.schema.json")), [], relative + ": metadata")

    def test_03_schema_oracle_rejects_invalid_and_unsupported_contracts(self) -> None:
        cases = (
            (True, {"type": "integer"}), ("x", {"type": ["integer", "null"]}),
            ({"extra": 1}, {"type": "object", "properties": {}, "required": [], "additionalProperties": False}),
            ({}, {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"], "additionalProperties": False}),
            ([1, 1], {"type": "array", "uniqueItems": True}), ([1], {"type": "array", "items": {"type": "string"}}),
            ("ab", {"minLength": 3}), ("abcd", {"maxLength": 3}), ("xx1", {"pattern": "[0-9]+"}),
            (0, {"minimum": 1}), (2, {"maximum": 1}), ([], {"minItems": 1}), ([1, 2], {"maxItems": 1}),
            (True, {"enum": [1]}), (False, {"const": 0}),
            (1, {"oneOf": [{"type": "integer"}, {"type": "number"}]}),
            (None, {"anyOf": [{"type": "integer"}, {"type": "string"}]}),
            ("x", {"$defs": {"v": {"type": "integer"}}, "$ref": "#/$defs/v"}),
            ({"a": 1}, {"additionalProperties": {"type": "string"}}),
        )
        for index, (instance, schema) in enumerate(cases):
            with self.subTest(case=index):
                self.check(validate(instance, schema), f"oracle case {index}: từ chối instance sai")
                with self.assertRaises(AssertionError, msg=f"oracle case {index}: validate_or_raise"):
                    validate_or_raise(instance, schema)
        for schema in ({"not": {}}, {"properties": {"a": {"format": "date"}}}, {"anyOf": [{"type": "string"}, {"unsupported": True}]}, {"$defs": {"unused": {"unknown": True}}}, {"$ref": "https://example.invalid/schema"}):
            with self.assertRaises(ValueError, msg="oracle: keyword lạ/ref ngoài bị chặn cả nhánh không dùng"):
                validate("x", schema)
        self.eq(validate(None, {"type": ["integer", "null"]}), [], "oracle nullable")
        self.eq(validate([True, 1], {"uniqueItems": True}), [], "oracle boolean khác số")
        self.eq(validate({"a": "v"}, {"additionalProperties": {"type": "string"}}), [], "oracle additionalProperties schema")

    def test_04_manifest_anchors_match_independent_contract_constants(self) -> None:
        manifest = load("manifest.json")
        self.eq(manifest["anchors"], {"tp-fin": FIN_ANCHORS, "tp-sales": SALES_ANCHORS}, "manifest.anchors: toàn bộ §4 độc lập")
        self.eq(manifest["fixture_set"], "ASSISTANT-FLOW-v1.1", "manifest.fixture_set")
        self.eq(manifest["provenance"]["synthetic"], True, "manifest.provenance.synthetic")
        self.eq(manifest["provenance"]["user_rows_used"], 0, "manifest.provenance.user_rows_used")
        self.check(len(manifest["limitations"]) >= 2, "manifest.limitations")
        for case in manifest["cases"]:
            self.check("?" not in case["expects"] and "\ufffd" not in case["expects"], case["id"] + ": expects không mất dấu tiếng Việt")

    def test_05_all_numeric_anchors_appear_in_findings_and_reconcile(self) -> None:
        for scenario, expected in (("tp-fin", FIN_ANCHORS), ("tp-sales", SALES_ANCHORS)):
            found = {item["value"]["formulaId"]: item["value"]["value"] for item in load(scenario + "/wl3_brief.json")["findings"]}
            for key, amount in expected.items():
                if isinstance(amount, (list, dict)):
                    continue
                snake = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
                if scenario == "tp-fin":
                    snake = FIN_ALIASES.get(key, snake)
                self.check("fm_" + snake in found, scenario + ": finding " + key)
                self.eq(Decimal(found["fm_" + snake]), Decimal(amount), scenario + ": anchor " + key)
            recon = load(scenario + "/wl5_reconciliation.json")
            control = expected["controlTotalSource"] if scenario == "tp-fin" else expected["revenueExcludingCancelled"]
            self.eq(Decimal(recon["controlTotalResult"]), Decimal(control), scenario + ": result total")
        fin = load("tp-fin/wl5_reconciliation.json")
        for key in ("controlTotalRawSource", "controlTotalSource"):
            self.eq(Decimal(fin[key]), Decimal(FIN_ANCHORS[key]), "tp-fin reconcile." + key)
        for key, anchor in (("op", "op"), ("fx", "fx"), ("total", "bridgeTotal"), ("variance", "variance"), ("actualUsd", "actualUsd"), ("actualVnd", "actualVnd"), ("budgetUsd", "budgetUsd"), ("budgetVnd", "budgetVnd"), ("rateActual", "rateActualUsdAverage"), ("rateBudget", "rateBudgetUsd")):
            self.eq(Decimal(fin["bridge"][key]), Decimal(FIN_ANCHORS[anchor]), "tp-fin bridge." + key)
        measures = {f["value"]["formulaId"]: f["value"]["value"] for f in load("tp-sales/wl3_brief.json")["findings"]}
        for region, amount in SALES_ANCHORS["regionTotals"].items():
            self.eq(Decimal(measures["fm_region_" + region.lower()]), Decimal(amount), "tp-sales region." + region)
        gl = csv_data("tp-fin", "GL_Actuals_2026-09.csv")
        deduped = list({tuple(row.values()): row for row in gl}.values())
        coa = {row["AccountCode"] for row in csv_data("tp-fin", "CoA.csv")}
        cc = {row["CostCenter"] for row in csv_data("tp-fin", "CostCenter.csv")}
        self.eq(sorted({row["AccountCode"] for row in deduped} - coa), FIN_ANCHORS["unmappedAccounts"], "tp-fin source unmappedAccounts")
        self.eq(sorted({row["CostCenter"] for row in deduped} - cc), FIN_ANCHORS["orphanCostCenters"], "tp-fin source orphanCostCenters")
        self.eq(len(gl) - len(deduped), int(FIN_ANCHORS["exactDuplicates"]), "tp-fin source exactDuplicates")
        collisions = Counter(tuple(row[k] for k in ("EntityCode", "Ledger", "DocNo", "LineNo")) for row in deduped)
        self.eq(sum(n > 1 for n in collisions.values()), int(FIN_ANCHORS["keyCollisionGroups"]), "tp-fin source collision groups")
        self.eq(sum(n for n in collisions.values() if n > 1), int(FIN_ANCHORS["keyCollisionRows"]), "tp-fin source collision rows")

    def test_06_snapshot_profiles_relationships_and_unknown_role(self) -> None:
        for scenario in SCENARIOS:
            snapshot = load(scenario + "/wl1_snapshot.json")
            self.eq(snapshot["snapshot"]["tableCount"], len(snapshot["tables"]), scenario + ": tableCount")
            self.eq(snapshot["snapshot"]["sourceCount"], len(snapshot["sources"]), scenario + ": sourceCount")
            for table in snapshot["tables"]:
                locator = table["locator"]
                paths = sorted((ROOT / scenario / locator["path"]).glob("*.csv")) if locator["kind"] == "folder" else [ROOT / scenario / locator["path"]]
                rows = []
                for path in paths:
                    with path.open(encoding="utf-8", newline="") as handle:
                        parsed = list(csv.reader(handle))
                    header = parsed[0]
                    rows.extend(parsed[1:])
                field = scenario + ": table " + table["name"]
                self.eq(table["rowCount"], len(rows), field + ".rowCount")
                self.eq(table["columnCount"], len(header), field + ".columnCount")
                self.eq(table["headerHash"], canonical_hash(header), field + ".headerHash")
                self.eq(table["sampleHash"], canonical_hash(rows[:20]), field + ".sampleHash")
                self.eq(table["fingerprint"], canonical_hash({"name": table["name"], "header": header, "sample": rows[:20]}), field + ".fingerprint")
                self.eq(locator["fileCount"], len(paths), field + ".fileCount")
                for index, column in enumerate(table["columns"]):
                    self.eq(column["sample"], [row[index] for row in rows[:20]], field + ".sample order")
                    values = [row[index] for row in rows]
                    nonempty = [v for v in values if v]
                    ratio = lambda n: float((Decimal(n) / Decimal(len(rows))).quantize(Decimal("0.001"), ROUND_HALF_UP)) if rows else 0.0
                    self.eq(column["nullRate"], ratio(len(rows) - len(nonempty)), field + ".nullRate")
                    self.eq(column["distinctCount"], len(set(nonempty)), field + ".distinctCount")
                    self.eq(column["distinctRatio"], ratio(len(set(nonempty))), field + ".distinctRatio")
                    if column["role"] is None:
                        self.eq(column["roleStatus"], "unknown", field + ".roleStatus")
        tables = {t["name"]: t for t in load("tp-fin/wl1_snapshot.json")["tables"]}
        segment = next(c for c in tables["GL_Actuals_2026-09"]["columns"] if c["name"] == "Segment2")
        self.eq(segment["role"], None, "tp-fin Segment2.role")
        understand = load("tp-fin/wl2_understand.json")
        roles = {r["tableId"]: r["structural"] for r in understand["roles"]}
        for name, role in (("GL_Actuals_2026-09", "fact"), ("CoA", "dim"), ("CostCenter", "dim"), ("Entity", "dim"), ("Currency", "dim"), ("FX_Rates_2026", "lookup")):
            self.eq(roles[tables[name]["id"]], role, "tp-fin role." + name)
        relations = {(r["fromTable"], r["toTable"]): r for r in understand["relationships"]}
        for left, right in (("GL_Actuals_2026-09", "CoA"), ("GL_Actuals_2026-09", "CostCenter"), ("GL_Actuals_2026-09", "Entity"), ("GL_Actuals_2026-09", "Currency"), ("CostCenter", "Entity"), ("GL_Actuals_2026-09", "FX_Rates_2026"), ("GL_Actuals_2026-09", "Budget_2026")):
            self.check((tables[left]["id"], tables[right]["id"]) in relations, "tp-fin relation " + left + "->" + right)
        gl_id = tables["GL_Actuals_2026-09"]["id"]
        self.eq(relations[(gl_id, tables["CostCenter"]["id"])]["evidence"]["orphan"], 7, "tp-fin GL->CC orphan")
        fx_relation = relations[(gl_id, tables["FX_Rates_2026"]["id"])]
        self.eq(fx_relation["fromColumns"], ["Currency", "Month"], "tp-fin FX row Currency x Month")
        self.eq(fx_relation["toColumns"], ["CurrencyCode", "Month"], "tp-fin FX composite target key")
        relation = relations[(gl_id, tables["Budget_2026"]["id"])]
        self.eq((relation["status"], relation["fanOutRisk"]), ("needs_confirm", "high"), "tp-fin GL->Budget gate")
        fanout = relation["fanOutEvidence"]
        gl = list({tuple(r.values()): r for r in csv_data("tp-fin", "GL_Actuals_2026-09.csv")}.values())
        budget = csv_data("tp-fin", "Budget_2026.csv")
        after = sum(max(1, sum(r["AccountCode"] == b["AccountCode"] and r["CostCenter"] == b["CostCenter"] and b["Month"] == "2026-09" for b in budget)) for r in gl)
        self.eq((fanout["rowsBefore"], fanout["rowsAfter"]), (len(gl), after), "tp-fin raw fanout simulation")
        self.check(after > len(gl), "tp-fin fanout inflates rows")
        self.eq(fanout["blockedBy"], "AF_FANOUT_RISK", "tp-fin fanout blocker")
        orders = next(t for t in load("tp-sales/wl1_snapshot.json")["tables"] if t["name"] == "Orders")
        self.eq((orders["locator"]["kind"], orders["locator"]["path"], orders["locator"]["fileCount"], orders["rowCount"]), ("folder", "source/orders", 3, 12), "tp-sales folder append")

    def test_07_regeneration_is_byte_deterministic_and_preserves_sources(self) -> None:
        paths = [p for s in SCENARIOS for p in (ROOT / s / "source").rglob("*.csv")]
        before = {p: p.read_bytes() for p in paths}
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            roots = [Path(first), Path(second)]
            for root in roots:
                assistant_fin.generate(root)
                assistant_sales.generate(root / "tp-sales")
                assistant_variants.generate(root / "variants")
            names = set(assistant_fin.build_fixtures()) | {"tp-sales/" + n for n in assistant_sales.build_fixtures()} | {"variants/" + n for n in assistant_variants.build_variants()}
            self.eq(len(names), 30, "regenerate 12 FIN/UNKNOWN +10 SALES +8 variants JSON")
            for name in sorted(names):
                self.eq((roots[0] / name).read_bytes(), (roots[1] / name).read_bytes(), name + ": double generation")
                self.eq((roots[0] / name).read_bytes(), (ROOT / name).read_bytes(), name + ": committed bytes")
        self.eq({p: p.read_bytes() for p in paths}, before, "regeneration: sources byte-identical")

    def test_08_formula_ids_and_engine_numeric_evidence(self) -> None:
        for scenario in SCENARIOS:
            formulas = load(scenario + "/formulas.json")["formulas"]
            ids = [f["formulaId"] for f in formulas]
            self.eq(len(ids), len(set(ids)), scenario + ": unique formulaId")
            for formula in formulas:
                self.eq(formula["basis"], "engine-decimal", scenario + ": formula basis")
                self.check(formula["expression"], scenario + ": formula expression")
            for relative, _, document in documents():
                owner = "tp-sales" if relative.startswith("tp-sales/") else "tp-fin"
                if owner != scenario:
                    continue
                for path, obj in walk(document):
                    if obj.get("formulaId") is not None:
                        self.check(obj["formulaId"] in ids, relative + path + ": formulaId exists")
                    numeric = False
                    if isinstance(obj.get("value"), str):
                        try:
                            numeric = Decimal(obj["value"]).is_finite()
                        except InvalidOperation:
                            pass
                    if numeric:
                        self.check(isinstance(obj.get("formulaId"), str) and obj["formulaId"] in ids, relative + path + ": mọi numeric value có formulaId tồn tại")
                    if "value" in obj and "unit" in obj:
                        self.check(isinstance(obj.get("formulaId"), str), relative + path + ": numeric value formulaId")
                        self.check(isinstance(obj["value"], str), relative + path + ": decimal string")
                        self.check(Decimal(obj["value"]).is_finite(), relative + path + ": finite number")

    def test_09_verified_requires_non_llm_provenance_and_measured_evidence(self) -> None:
        verified = []
        for relative, _, document in documents():
            for path, obj in walk(document):
                if obj.get("status") == "verified":
                    verified.append(relative + path)
                    self.check(obj.get("provenance") in {"pack", "data", "history", "user"}, relative + path + ": verified provenance")
                    self.check(any(e.get("kind") == "engine" and e.get("value") is not None and e.get("formulaId") for e in obj.get("evidence", [])), relative + path + ": measured engine evidence")
                if obj.get("provenance") == "llm":
                    self.check(obj.get("status") in {"inferred", "assumed", "unknown"}, relative + path + ": llm status")
                if "labels" in obj:
                    self.check(set(obj["labels"]) <= LABELS, relative + path + ": labels enum")
        self.check(verified, "verified: positive measured SP-4 example")

    def test_10_briefs_policies_missing_data_scenarios_and_generic_mode(self) -> None:
        for scenario, expected in (("tp-fin", FIN_SP), ("tp-sales", SALES_SP)):
            brief = load(scenario + "/wl3_brief.json")
            self.eq([sp["id"] for sp in brief["subProblems"]], [f"SP-{n}" for n in range(1, len(expected) + 1)], scenario + ": exact SP ids")
            self.eq([(sp["status"], sp["provenance"]) for sp in brief["subProblems"]], list(expected), scenario + ": status/provenance")
            self.eq({case["kind"] for case in brief["insightCases"]}, {"hypothesis", "slice"}, scenario + ": insight kinds")
            self.check("unverified" in brief["labels"], scenario + ": labels")
            self.check(brief["outputContract"]["grain"] and brief["outputContract"]["measures"] and brief["outputContract"]["filters"], scenario + ": output contract")
            for sp in brief["subProblems"]:
                self.eq(sp["chosenOptionId"], None, scenario + ": choice only in decisions " + sp["id"])
                self.check(len(sp["options"]) >= 2, scenario + ": A/B " + sp["id"])
                for option in sp["options"]:
                    self.check(option["consequence"]["statement"], scenario + ": consequence " + sp["id"])
                    if sp["status"] == "missing_data":
                        self.eq(option["consequence"]["value"], None, scenario + ": missing_data no invented number " + sp["id"])
                if sp["status"] == "missing_data":
                    self.check("out_of_scope" in sp["labels"], scenario + ": missing_data label " + sp["id"])
        fin = load("tp-fin/wl3_brief.json")
        self.eq([s["id"] for s in fin["scenarios"]], ["A", "B"], "tp-fin scenarios A/B")
        scenarios = [{v["name"]: Decimal(v["value"]) for v in s["values"]} for s in fin["scenarios"]]
        self.eq(Decimal(fin["delta"]["value"]), abs(scenarios[0]["FX"] - scenarios[1]["FX"]), "tp-fin delta engine difference")
        self.check(Decimal(fin["delta"]["value"]) > 0, "tp-fin delta positive")
        unknown = load("tp-unknown/wl3_brief_unresolved.json")
        review = load("tp-unknown/wl3_decisions_unresolved.json")
        self.eq(review["decisions"], [], "tp-unknown decisions empty")
        self.eq(review["freezeBlocked"], True, "tp-unknown freezeBlocked")
        self.check(len(review["checklist"]) >= 3, "tp-unknown checklist")
        self.eq(len(unknown["scenarios"]), 2, "tp-unknown two scenarios")
        self.check(Decimal(unknown["delta"]["value"]) > 0, "tp-unknown delta positive")
        for scenario in unknown["scenarios"]:
            self.check(scenario["values"], "tp-unknown scenario engine values")
        for sp in unknown["subProblems"][:3]:
            self.eq(sp["chosenOptionId"], None, "tp-unknown no forced choice " + sp["id"])
        generic = load("tp-sales/wl2_understand.json")["pack"]
        self.eq((generic["id"], generic["genericMode"]), ("generic", True), "tp-sales generic pack")
        self.check("kém chính xác hơn" in generic["notice"], "tp-sales generic disclosure")
        self.eq(load("tp-sales/wl3_brief.json")["prompt"], "Doanh thu theo khu vực quý 3 giảm vì đơn huỷ hay thiếu khách?", "tp-sales exact prompt")

    def test_11_freeze_decision_mapping_dag_and_group_before_budget(self) -> None:
        for scenario in SCENARIOS:
            brief = load(scenario + "/wl3_brief.json")
            decisions = load(scenario + "/wl3_decisions.json")
            spec = load(scenario + "/wl4_execution_spec.json")
            ids = [item["subProblemId"] for item in decisions["decisions"] + decisions["acknowledgements"]]
            self.eq(Counter(ids), Counter(sp["id"] for sp in brief["subProblems"]), scenario + ": one decision/ack per SP")
            self.eq(decisions["freezeBlocked"], False, scenario + ": freeze allowed")
            mapped = {ref for step in spec["steps"] for ref in step["decisionRefs"]}
            self.check({d["subProblemId"] for d in decisions["decisions"]} <= mapped, scenario + ": executable decision mapping")
            seen_ids, outputs = set(), set()
            source_ids = {t["id"] for t in load(scenario + "/wl1_snapshot.json")["tables"]}
            for index, step in enumerate(spec["steps"]):
                self.check(step["id"] not in seen_ids, scenario + ": unique step id")
                self.check(set(step["dependsOn"]) <= seen_ids, scenario + ": dependency earlier " + step["id"])
                self.check(set(step["inputs"]) <= outputs | source_ids, scenario + ": inputs bound " + step["id"])
                if index:
                    self.check(step["inputs"], scenario + ": no orphan " + step["id"])
                if step["guard"] == "AF_FANOUT_RISK":
                    self.eq(step["status"], "blocked", scenario + ": guard only blocked")
                seen_ids.add(step["id"])
                outputs.add(step["output"])
            self.check("unverified" in spec["labels"], scenario + ": unverified assumptions preserved")
            self.check(spec["unverifiedAssumptions"], scenario + ": assumption ids")
        steps = load("tp-fin/wl4_execution_spec.json")["steps"]
        ops = {step["params"]["operation"]: index for index, step in enumerate(steps)}
        for first, second in (("dedupe", "normalize_sign"), ("normalize_sign", "join_coa"), ("join_coa", "group"), ("group", "join_budget"), ("join_budget", "variance_bridge")):
            self.check(ops[first] < ops[second], "tp-fin operation order: " + first + "->" + second)
        self.check(steps[ops["group"]]["id"] in steps[ops["join_budget"]]["dependsOn"], "tp-fin Budget depends on group")

    def test_12_every_artifact_hash_recomputes_and_covers_business_fields(self) -> None:
        for relative, base_name, document in list(documents()) + [("manifest.json", "manifest.json", load("manifest.json"))]:
            field = HASH_FIELDS.get(base_name, "hash")
            basis = document["hashBasis"]
            self.eq(len(basis), len(set(basis)), relative + ": unique hashBasis")
            self.check(field not in basis, relative + ": hash excludes itself")
            mandatory = set(document) - {"schemaVersion", "id", "createdAt", "appliedAt", "hashBasis", field}
            self.check(mandatory <= set(basis), relative + ": hashBasis covers business/variant fields")
            self.eq(document[field], canonical_hash({key: document[key] for key in basis}), relative + ": canonical " + field)

    def test_13_complete_cross_artifact_hash_chain(self) -> None:
        for scenario in SCENARIOS:
            docs = {name: load(scenario + "/" + name) for name in ARTIFACTS}
            snapshot, understand, brief, decisions, spec, preview, recon, applied, record = [docs[name] for name in ARTIFACTS[1:]]
            for name in ("wl2_understand.json", "wl3_brief.json", "wl3_decisions.json", "wl4_execution_spec.json"):
                self.eq(docs[name]["snapshotHash"], snapshot["snapshotHash"], scenario + "/" + name + ": snapshot chain")
            for name in ("wl3_brief.json", "wl3_decisions.json"):
                self.eq(docs[name]["understandHash"], understand["understandHash"], scenario + "/" + name + ": understand chain")
            self.eq(decisions["briefHash"], brief["briefHash"], scenario + ": decisions briefHash")
            self.eq(spec["briefHash"], brief["briefHash"], scenario + ": spec briefHash")
            self.eq(spec["decisionsHash"], decisions["decisionsHash"], scenario + ": spec decisionsHash")
            for name in ("wl5_preview.json", "wl5_reconciliation.json", "wl6_apply.json"):
                self.eq(docs[name]["specFingerprint"], spec["fingerprint"], scenario + "/" + name + ": spec chain")
            self.eq(recon["previewHash"], preview["previewHash"], scenario + ": reconcile previewHash")
            self.eq(applied["previewHash"], preview["previewHash"], scenario + ": apply previewHash")
            self.eq(applied["approval"]["boundTo"], {"specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"]}, scenario + ": approval boundTo")
            self.eq(record["snapshot"]["snapshotHash"], snapshot["snapshotHash"], scenario + ": record snapshot")
            self.eq(record["brief"]["briefHash"], brief["briefHash"], scenario + ": record brief")
            self.eq(record["decisions"], decisions["decisions"], scenario + ": record decisions")
            self.eq(record["steps"], spec["steps"], scenario + ": record steps")
            self.eq(record["reconciliations"][0], recon, scenario + ": record reconciliation")
            self.check("spec=" + spec["fingerprint"] in applied["target"]["marker"], scenario + ": marker spec")
            self.check("preview=" + preview["previewHash"] in applied["target"]["marker"], scenario + ": marker preview")
        self.eq(load("tp-unknown/wl3_decisions_unresolved.json")["briefHash"], load("tp-unknown/wl3_brief_unresolved.json")["briefHash"], "tp-unknown decisions brief chain")

    def test_14_preview_values_only_source_preserved_and_reconcile_gate(self) -> None:
        for scenario in SCENARIOS:
            preview = load(scenario + "/wl5_preview.json")
            recon = load(scenario + "/wl5_reconciliation.json")
            self.eq(preview["counts"], {"formulaCount": 0, "queryCount": 0, "connectionCount": 0}, scenario + ": values only counts")
            self.eq((preview["target"]["workbook"], preview["target"]["mode"]), ("temp_copy", "values_only"), scenario + ": preview temporary values only")
            self.eq(preview["source"]["before"], preview["source"]["after"], scenario + ": preview source hashes")
            self.eq(preview["source"]["unchanged"], True, scenario + ": source unchanged")
            self.eq(Decimal(recon["controlTotalRawSource"]) - Decimal(recon["droppedByDedupe"]), Decimal(recon["controlTotalSource"]), scenario + ": raw-dropped=source")
            self.check(abs(Decimal(recon["controlTotalSource"]) - Decimal(recon["controlTotalResult"])) <= Decimal(recon["controlTotalTolerance"]), scenario + ": source=result within tolerance")
            self.eq(recon["controlTotalPassed"], True, scenario + ": controlTotalPassed")
            self.eq(recon["passed"], True, scenario + ": reconciliation passed")
            self.eq({c["id"] for c in recon["checks"]}, {"row_count", "control_total", "bridge_identity"}, scenario + ": three checks")
            self.check(all(c["passed"] for c in recon["checks"]), scenario + ": all checks pass")
            self.eq(preview["sheets"]["before"], {"rows": recon["rowsIn"], "cols": recon["colsIn"]}, scenario + ": before dimensions")
            self.eq(preview["sheets"]["after"], {"rows": recon["rowsOut"], "cols": recon["colsOut"]}, scenario + ": after dimensions")
            bridge = recon["bridge"]
            if scenario == "tp-fin":
                self.eq(bridge["applicable"], True, "tp-fin bridge applicable")
                self.eq(Decimal(bridge["op"]) + Decimal(bridge["fx"]), Decimal(bridge["total"]), "tp-fin op+fx=total")
                self.eq(Decimal(bridge["total"]), Decimal(bridge["variance"]), "tp-fin total=variance")
                self.eq(bridge["passed"], True, "tp-fin bridge passed")
            else:
                self.eq(bridge, {"applicable": False, "scope": None, "op": None, "fx": None, "total": None, "variance": None, "passed": None}, "tp-sales no artificial FX")
                self.eq(recon["droppedByDedupe"], "0", "tp-sales no dedupe loss")

    def test_15_apply_approval_single_use_new_sheet_and_no_save(self) -> None:
        for scenario in SCENARIOS:
            applied = load(scenario + "/wl6_apply.json")
            recon = load(scenario + "/wl5_reconciliation.json")
            self.eq(applied["approval"]["consumed"], True, scenario + ": approval consumed")
            self.eq(applied["approval"]["singleUse"], True, scenario + ": approval singleUse")
            self.eq(applied["approval"]["approvedBy"], "user", scenario + ": explicit user approval")
            self.eq(applied["target"]["mode"], "values_only", scenario + ": apply mode")
            self.eq(applied["target"]["writeMode"], "new_sheet_only", scenario + ": new sheet only")
            self.eq(applied["workbookSaved"], False, scenario + ": no auto-save")
            self.eq(applied["source"]["before"], applied["source"]["after"], scenario + ": source hash unchanged")
            self.eq(applied["source"]["unchanged"], True, scenario + ": source unchanged")
            self.eq(applied["source"]["sheetsWritten"], [], scenario + ": no source sheets written")
            self.eq(applied["written"], {"rowCount": recon["rowsOut"], "columnCount": recon["colsOut"]}, scenario + ": written dimensions")
            for label in applied["labels"]:
                self.check(label in applied["target"]["marker"], scenario + ": marker label " + label)

    def test_16_record_delta_has_provenance_and_measured_changes(self) -> None:
        for scenario in SCENARIOS:
            record = load(scenario + "/wl7_decision_record.json")
            recon = load(scenario + "/wl5_reconciliation.json")
            self.check(isinstance(record["reconciliations"], list), scenario + ": reconciliation array")
            self.eq(record["stale"], False, scenario + ": record current")
            self.eq(record["delta"]["rowsIn"], recon["rowsIn"], scenario + ": delta rowsIn")
            self.eq(record["delta"]["rowsOut"], recon["rowsOut"], scenario + ": delta rowsOut")
            self.check(record["assumptions"], scenario + ": assumption ledger")
            self.check(record["delta"]["changedColumns"], scenario + ": changed columns")
            self.check("verified" not in record["labels"], scenario + ": output never verified")
            for assumption in record["assumptions"]:
                self.check(assumption["source"] in {"pack", "data", "history", "llm", "user"}, scenario + ": assumption provenance")
                self.check(assumption["risk"] in {"low", "medium", "high"}, scenario + ": assumption risk")
        fin = load("tp-fin/wl7_decision_record.json")["delta"]
        gl = csv_data("tp-fin", "GL_Actuals_2026-09.csv")
        self.eq(fin["nullsBefore"]["PartnerEntity"], sum(not r["PartnerEntity"] for r in gl), "tp-fin delta null count")
        self.eq(fin["duplicatesBefore"], len(gl) - len({tuple(r.values()) for r in gl}), "tp-fin delta exact duplicates")
        self.eq(fin["duplicatesAfter"], 0, "tp-fin dedupe exact duplicates")

    def test_17_all_eight_variant_semantics(self) -> None:
        variants = {name: load("variants/" + name) for name in VARIANTS}
        for name, doc in variants.items():
            self.eq(doc["variantOf"], VARIANTS[name], name + ": variantOf")
            self.check(doc["variantReason"], name + ": variantReason")
        drift = variants["fin_reconcile_control_drift.json"]
        source = load("tp-fin/wl5_reconciliation.json")
        self.eq(Decimal(drift["controlTotalResult"]) - Decimal(source["controlTotalResult"]), Decimal("1234560"), "drift exact injection")
        self.eq(drift["passed"], False, "drift approval blocked")
        self.eq(drift["controlTotalPassed"], False, "drift control failed")
        self.check(any(b["code"] == "AF_RECONCILE_FAILED" and b["severity"] == "blocker" for b in drift["blockers"]), "drift reconcile blocker")
        self.check(drift["labels"], "drift labels visible")
        missing = variants["fin_rate_missing_blocker.json"]
        self.eq(missing["passed"], False, "EUR missing blocked")
        self.check(any(b["code"] == "AF_MISSING_DATA" and b["severity"] == "blocker" and "EUR" in b["message"] for b in missing["blockers"]), "EUR used rate blocker")
        warning = variants["fin_rate_closing_missing_warning.json"]
        self.eq(warning["passed"], True, "closing rate continuation")
        self.eq(warning["blockers"], [], "closing rate no blocker")
        self.check(warning["warnings"] and all(w["severity"] == "warning" and "USD" in w["message"] for w in warning["warnings"]), "closing only USD warning")
        spec = variants["fin_spec_invalidated.json"]
        self.eq((spec["stale"], spec["code"], spec["invalidatedBy"]), (True, "AF_SPEC_STALE", "decisionChanged"), "spec stale gate")
        record = variants["fin_record_stale.json"]
        self.eq((record["stale"], record["code"]), (True, "AF_SPEC_STALE"), "record stale code")
        self.check("stale" in record["labels"], "record stale label")
        ambiguous = variants["wl1_csv_ambiguous.json"]
        self.eq(ambiguous["status"], "needs_clarification", "CSV clarification")
        self.eq(ambiguous["synthetic"], True, "CSV synthetic")
        self.check(ambiguous["csvProfile"]["auto"]["fingerprint"] != ambiguous["csvProfile"]["manual"]["fingerprint"], "CSV changed profile fingerprint")
        blocked = variants["wl1_connector_blocked.json"]
        self.eq({c["kind"] for c in blocked["cases"]}, {"exe", "pathTraversal", "oversize"}, "connector three cases")
        for case in [blocked, *blocked["cases"]]:
            self.eq((case["code"], case["severity"], case["tempCreated"]), ("AF_INGEST_FAILED", "blocker", False), "connector block before temp")
        duplicate = variants["wl1_duplicate_table_name.json"]
        self.eq((duplicate["requiresRename"], duplicate["code"], duplicate["overwritten"]), (True, "AF_INGEST_FAILED", False), "duplicate rename without overwrite")
        names = [t["name"] for t in duplicate["tables"]]
        self.check(len(set(names)) < len(names), "duplicate actual collision")

    def test_18_manifest_covers_exactly_45_case_ids_and_existing_files(self) -> None:
        expected = {f"T-WL{layer}-{index:02d}" for layer, count in ((1, 7), (2, 7), (3, 6), (4, 5), (5, 6), (6, 5), (7, 5)) for index in range(1, count + 1)}
        expected.update({"T-E2E-FIN", "T-E2E-SALES", "T-E2E-UNKNOWN", "T-E2E-NOPACK"})
        cases = load("manifest.json")["cases"]
        self.eq(len(cases), 45, "manifest case count")
        self.eq({case["id"] for case in cases}, expected, "manifest exact 45 IDs")
        for case in cases:
            self.check(case["artifacts"], case["id"] + ": artifacts required")
            for name in case["artifacts"]:
                relative = name if name.startswith(("variants/", "tp-fin/", "tp-sales/", "tp-unknown/")) else case["scenario"] + "/" + name
                self.check((ROOT / relative).is_file(), case["id"] + ": artifact exists " + relative)


if __name__ == "__main__":
    unittest.main()
