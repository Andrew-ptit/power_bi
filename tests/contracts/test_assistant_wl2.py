"""Golden-derived and invariant contracts for the local deterministic WL2 slice."""

from __future__ import annotations

import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.sources.assistant_ingest import canonical_hash, close, resolve
from pbip_assistant.sources.assistant_keys import has_finance_schema, key_report
from pbip_assistant.sources.assistant_profile import build_snapshot
from pbip_assistant.sources.assistant_roles import column_roles, warning_classification
from pbip_assistant.sources.assistant_understand import build_understand, understand_hash
from tests.support.json_schema_oracle import validate
from tests.support.paths import FIXTURES


ROOT = FIXTURES / "assistant"
SCENARIOS = ("tp-fin", "tp-sales")


def scenario_inputs(scenario: str) -> tuple[dict, dict]:
    root = ROOT / scenario
    requests = [{"kind": "csv", "path": "source/" + path.name}
                for path in sorted((root / "source").glob("*.csv"))]
    if scenario == "tp-sales":
        requests.append({"kind": "folder", "path": "source/orders", "name": "Orders"})
    session = {"root": root}
    result = resolve(session, requests)
    if result["errors"] or result["requiresRename"]:
        raise AssertionError(scenario + ": WL1 must succeed before WL2")
    return result, session


def bound_tables(raw: list[dict], snapshot: dict) -> list[dict]:
    ids = {table["name"]: table["id"] for table in snapshot["tables"]}
    result = deepcopy(raw)
    for table in result:
        table["id"] = ids[table["name"]]
    return result


def relation_key(relation: dict) -> tuple:
    return relation["fromTable"], tuple(relation["fromColumns"]), relation["toTable"], tuple(relation["toColumns"])


def walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def states(paths: list[Path]) -> dict:
    return {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns, path.stat().st_size)
            for path in paths}


class AssistantWL2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs, cls.snapshots, cls.models, cls.reports, cls.bounds = {}, {}, {}, {}, {}
        for scenario in SCENARIOS:
            cls.inputs[scenario], session = scenario_inputs(scenario)
            cls.snapshots[scenario] = json.loads((ROOT / scenario / "wl1_snapshot.json").read_text(encoding="utf-8"))
            cls.bounds[scenario] = bound_tables(cls.inputs[scenario]["tables"], cls.snapshots[scenario])
            cls.reports[scenario] = key_report(cls.bounds[scenario])
            cls.models[scenario] = build_understand(cls.inputs[scenario]["tables"], cls.snapshots[scenario])
            close(session)

    def eq(self, actual: object, expected: object, field: str) -> None:
        self.assertEqual(actual, expected, field)

    def check(self, value: object, field: str) -> None:
        self.assertTrue(value, field)

    def golden(self, scenario: str) -> None:
        expected = json.loads((ROOT / scenario / "wl2_understand.json").read_text(encoding="utf-8"))
        actual, report = self.models[scenario], self.reports[scenario]
        actual_pairs = {relation_key(link): link for link in actual["relationships"]}
        self.eq(len(actual_pairs), len(actual["relationships"]), scenario + ": unique relationship tuples")
        for link in expected["relationships"]:
            key = relation_key(link)
            self.check(key in actual_pairs, scenario + ": golden relationship exists " + str(key))
            found = actual_pairs[key]
            for field in ("score", "cardinality", "status", "fanOutRisk", "fanOutEvidence"):
                self.eq(found[field], link[field], scenario + ": selected relationship." + field)
            for field in ("name", "type", "overlap", "orphan"):
                self.eq(found["evidence"][field], link["evidence"][field], scenario + ": selected evidence." + field)
            if link["fanOutEvidence"] is not None:
                fan = {"fromTable": link["fromTable"], "toTable": link["toTable"],
                       **link["fanOutEvidence"], "risk": "high"}
                self.assertIn(fan, report["fanOut"], scenario + ": golden fanOut entry")
        self.check(set(relation_key(link) for link in expected["relationships"]) <= set(actual_pairs), scenario + ": superset is allowed")
        self.eq(actual["snapshotHash"], self.snapshots[scenario]["snapshotHash"], scenario + ": provided WL1 hash")
        self.eq(actual["snapshotHash"], expected["snapshotHash"], scenario + ": golden snapshot binding")
        self.eq(actual["pack"]["genericMode"], expected["pack"]["genericMode"], scenario + ": genericMode")
        self.eq(actual["pack"]["notice"] is None, expected["pack"]["notice"] is None, scenario + ": notice nullability")
        schema = json.loads((ROOT / "schema" / "understand.schema.json").read_text(encoding="utf-8"))
        self.eq(validate(actual, schema), [], scenario + ": core understand schema")

    def test_golden_fin_compares_only_derived_selected_pairs(self) -> None:
        self.golden("tp-fin")

    def test_golden_sales_compares_only_derived_selected_pairs(self) -> None:
        self.golden("tp-sales")

    def test_af_un_001_exactly_one_measured_fact_and_structural_invariants(self) -> None:
        for scenario, name in (("tp-fin", "GL_Actuals_2026-09"), ("tp-sales", "OrderItems")):
            model, snapshot = self.models[scenario], self.snapshots[scenario]
            expected_id = next(table["id"] for table in snapshot["tables"] if table["name"] == name)
            facts = [role for role in model["roles"] if role["structural"] == "fact"]
            self.eq([role["tableId"] for role in facts], [expected_id], scenario + ": one fact")
            for role in model["roles"]:
                self.check(role["evidence"], scenario + ": role evidence")
                self.check(any(e["value"] is not None and Decimal(e["value"]).is_finite() for e in role["evidence"]), scenario + ": measured evidence")
                self.check(0 <= role["confidence"] <= 1, scenario + ": role confidence")
                self.check(role["structural"] in {"fact", "dim", "bridge", "lookup"}, scenario + ": role enum")
                if role["structural"] == "bridge":
                    self.check(any(link["cardinality"] == "N:N" and link["evidence"]["overlap"] > 0
                                   and role["tableId"] in (link["fromTable"], link["toTable"])
                                   for link in model["relationships"]), scenario + ": bridge requires measured N:N")
                    raw_keys = [set(key["columns"]) for key in self.reports[scenario]["keys"] if key["tableId"] == role["tableId"]]
                    partial_fact_lookup = [link for link in model["relationships"]
                                           if link["fromTable"] == expected_id and link["toTable"] == role["tableId"]
                                           and link["cardinality"] in {"N:1", "1:1"} and link["evidence"]["overlap"] > 0
                                           and not any(key <= set(link["toColumns"]) for key in raw_keys)]
                    self.eq(partial_fact_lookup, [], scenario + ": supported partial lookup outranks secondary N:N candidate")

    def test_af_un_002_primary_keys_and_nonunique_raw_gl_document_key(self) -> None:
        expected = {"tp-fin": (("CoA", "AccountCode"), ("CostCenter", "CostCenter"), ("Currency", "CurrencyCode"), ("Entity", "EntityCode")),
                    "tp-sales": (("Customers", "CustomerID"), ("Products", "ProductID"), ("Territory", "TerritoryID"))}
        for scenario in SCENARIOS:
            ids = {table["name"]: table["id"] for table in self.snapshots[scenario]["tables"]}
            keys = self.reports[scenario]["keys"]
            for table, column in expected[scenario]:
                self.check(any(key["tableId"] == ids[table] and key["columns"] == [column]
                               and key["unique"] and key["nullCount"] == 0 and key["distinctRatio"] == 1.0 for key in keys), scenario + ": PK " + table + "." + column)
            if scenario == "tp-fin":
                self.check(not any(key["tableId"] == ids["GL_Actuals_2026-09"] and set(key["columns"]) == {"DocNo", "LineNo"} for key in keys), "AF-UN-002: duplicate GL document tuple is not unique")
                self.eq(len(next(raw for raw in self.bounds[scenario] if raw["name"] == "GL_Actuals_2026-09")["rows"]), 31, "AF-UN-002: raw GL rows retained")

    def test_af_un_003_every_relationship_has_measured_score_and_cardinality(self) -> None:
        one_to_many = []
        for scenario in SCENARIOS:
            for link in self.models[scenario]["relationships"]:
                self.eq(set(link["evidence"]), {"name", "type", "overlap", "orphan"}, scenario + ": relationship evidence fields")
                self.eq(link["score"], link["evidence"]["overlap"], scenario + ": score=overlap")
                self.check(0 <= link["score"] <= 1 and link["evidence"]["orphan"] >= 0, scenario + ": score/orphan ranges")
                self.check(link["cardinality"] in {"1:1", "1:N", "N:1", "N:N"}, scenario + ": cardinality enum")
                if link["cardinality"] == "1:N" and link["fanOutRisk"] == "high":
                    one_to_many.append(link)
                    self.eq(link["status"], "needs_confirm", scenario + ": actual 1:N fan-out confirmation")
        self.check(one_to_many, "AF-UN-003: 1:N remains distinct from N:N")

    def test_af_un_004_gl_budget_fan_out_matches_independent_anchor(self) -> None:
        scenario = "tp-fin"
        ids = {t["name"]: t["id"] for t in self.snapshots[scenario]["tables"]}
        link = next(link for link in self.models[scenario]["relationships"]
                    if relation_key(link) == (ids["GL_Actuals_2026-09"], ("AccountCode", "CostCenter", "Month"), ids["Budget_2026"], ("AccountCode", "CostCenter", "Month")))
        self.eq((link["fanOutRisk"], link["status"], link["cardinality"]), ("high", "needs_confirm", "N:N"), "AF-UN-004: GL/Budget gate")
        self.eq(link["fanOutEvidence"], {"rowsBefore": 30, "rowsAfter": 32, "inflationFactor": 1.067, "blockedBy": "AF_FANOUT_RISK"}, "AF-UN-004: independent fan-out anchors")

    def test_af_un_005_column_meaning_and_currency_key_precedence(self) -> None:
        scenario = "tp-fin"
        proposals = column_roles(self.snapshots[scenario], self.bounds[scenario])
        ids = {table["name"]: table["id"] for table in self.snapshots[scenario]["tables"]}
        by_column = {(proposal["tableId"], proposal["name"]): proposal for proposal in proposals}
        for name, role in (("PostingDate", "date"), ("Amount", "amount"), ("Currency", "currency")):
            self.eq(by_column[(ids["GL_Actuals_2026-09"], name)]["role"], role, "AF-UN-005: GL." + name)
        self.eq(by_column[(ids["Currency"], "CurrencyCode")]["role"], "currency", "AF-UN-005: currency semantics take precedence")
        for proposal in proposals:
            self.check(proposal["evidence"], "AF-UN-005: every proposal has evidence")
            if any(e["kind"] == "detected_key" for e in proposal["evidence"]):
                self.check(proposal["role"] in {"key", "currency"}, "AF-UN-005: key/currency evidence retained")
        self.check(any(e["kind"] == "detected_key" for e in by_column[(ids["Currency"], "CurrencyCode")]["evidence"]), "AF-UN-005: currency still carries key evidence")

    def test_af_un_006_ledger_has_only_used_sources_evidence_and_risk(self) -> None:
        for scenario in SCENARIOS:
            ledger = self.models[scenario]["assumptions"]
            sources = {entry["source"] for entry in ledger}
            self.eq(sources, {"data", "pack"} if scenario == "tp-fin" else {"data"}, scenario + ": actually used provenance")
            for entry in ledger:
                self.eq(set(entry), {"id", "statement", "source", "confidence", "risk", "evidence"}, scenario + ": ledger shape")
                self.assertRegex(entry["id"], r"^asm_[a-f0-9]{12}$", scenario + ": ledger id")
                self.check(entry["source"] in {"data", "pack", "history", "user"}, scenario + ": ledger source enum")
                self.check(entry["risk"] in {"low", "medium", "high"}, scenario + ": risk enum")
                self.check(0 <= entry["confidence"] <= 1 and entry["evidence"] and entry["statement"], scenario + ": confidence/evidence/statement")

    def test_af_un_007_generic_notice_and_pack_detection_use_schema_not_names(self) -> None:
        self.eq(self.models["tp-sales"]["pack"]["id"], "generic", "AF-UN-007: SALES pack")
        self.check("kém chính xác hơn" in self.models["tp-sales"]["pack"]["notice"], "AF-UN-007: generic notice")
        renamed = deepcopy(self.inputs["tp-fin"])
        for index, raw in enumerate(renamed["tables"]):
            raw["name"] = "Renamed_" + str(index)
        self.check(has_finance_schema(renamed["tables"]), "AF-UN-007: finance schema ignores table names")
        model = build_understand(renamed["tables"], build_snapshot(renamed))
        self.eq((model["pack"]["id"], model["pack"]["genericMode"], model["pack"]["notice"]), ("fin-pl-v1", False, None), "AF-UN-007: renamed finance model")

    def test_af_un_008_ambiguous_segment_stays_unknown(self) -> None:
        snapshot = self.snapshots["tp-fin"]
        gl_id = next(table["id"] for table in snapshot["tables"] if table["name"] == "GL_Actuals_2026-09")
        proposals = column_roles(snapshot, self.bounds["tp-fin"])
        segment = next(p for p in proposals if p["tableId"] == gl_id and p["name"] == "Segment2")
        self.eq((segment["role"], segment["roleStatus"]), (None, "unknown"), "AF-UN-008: no guessed Segment2 meaning")
        for proposal in proposals:
            self.eq(proposal["roleStatus"], "unknown" if proposal["role"] is None else "inferred", "AF-UN-008: role label")

    def test_af_un_009_understand_is_deterministic_and_hash_recomputes(self) -> None:
        for scenario in SCENARIOS:
            raw, snapshot = self.inputs[scenario]["tables"], self.snapshots[scenario]
            first = build_understand(raw, snapshot)
            second = build_understand(list(reversed(raw)), snapshot)
            self.eq(first, second, scenario + ": repeated/reordered deterministic model")
            self.eq(first["understandHash"], understand_hash(first), scenario + ": public recompute")
            self.eq(first["understandHash"], canonical_hash({key: first[key] for key in first["hashBasis"]}), scenario + ": independent canonical recompute")

    def test_br_001_numeric_gates_and_explicit_pack_confirmation_policy(self) -> None:
        for scenario in SCENARIOS:
            for link in self.models[scenario]["relationships"]:
                if link["fanOutRisk"] == "high" or link["evidence"]["overlap"] < 0.5:
                    self.eq(link["status"], "needs_confirm", scenario + ": fan-out/low-overlap gate")
                if scenario == "tp-sales" and link["evidence"]["orphan"] > 0:
                    self.eq(link["status"], "needs_confirm", "BR-001: generic orphan confirmation")
        finance_orphan_auto = [link for link in self.models["tp-fin"]["relationships"] if link["evidence"]["orphan"] > 0 and link["fanOutRisk"] == "none" and link["score"] >= 0.5]
        self.check(finance_orphan_auto, "BR-001: positive finance policy example")
        self.check(all(link["status"] == "auto" for link in finance_orphan_auto), "BR-001: finance threshold policy")

    def test_br_002_no_verified_or_llm_and_no_engine_network(self) -> None:
        for scenario in SCENARIOS:
            for entry in walk(self.models[scenario]):
                self.check(entry.get("source") != "llm" and entry.get("provenance") != "llm", scenario + ": no LLM provenance")
                self.check(entry.get("status") != "verified" and entry.get("roleStatus") != "verified", scenario + ": no verified inference")
            with patch.object(socket, "socket", side_effect=AssertionError("WL2 must not open a network socket")):
                result = build_understand(self.inputs[scenario]["tables"], self.snapshots[scenario])
            self.eq(result["understandHash"], self.models[scenario]["understandHash"], scenario + ": local-only output")
        package = FIXTURES.parents[1] / "pbip_assistant" / "sources"
        forbidden = {"socket", "urllib", "http", "requests", "subprocess", "openai"}
        for name in ("assistant_keys.py", "assistant_roles.py", "assistant_understand.py"):
            tree = ast.parse((package / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.check(not any(alias.name.split(".")[0] in forbidden for alias in node.names), name + ": no external/network import")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.check(node.module.split(".")[0] not in forbidden, name + ": no external/network import")

    def test_runtime_wl1_pipeline_and_every_used_source_remain_read_only(self) -> None:
        paths = [p for scenario in SCENARIOS for p in (ROOT / scenario / "source").rglob("*.csv")]
        paths.extend(ROOT / scenario / name for scenario in SCENARIOS for name in ("wl1_snapshot.json", "wl2_understand.json"))
        before = states(paths)
        for scenario in SCENARIOS:
            raw, session = scenario_inputs(scenario)
            snapshot = build_snapshot(raw)
            raw_before, snapshot_before = deepcopy(raw), deepcopy(snapshot)
            model = build_understand(raw["tables"], snapshot)
            self.eq(model["snapshotHash"], snapshot["snapshotHash"], scenario + ": runtime WL1 hash binding")
            ids = {table["id"] for table in snapshot["tables"]}
            self.check(all(link["fromTable"] in ids and link["toTable"] in ids for link in model["relationships"]), scenario + ": runtime table references")
            self.eq((raw, snapshot), (raw_before, snapshot_before), scenario + ": in-memory inputs unchanged")
            close(session)
        self.eq(states(paths), before, "WL2 must preserve all source/golden bytes, size and mtime")

    def test_rate_warnings_distinguish_used_average_from_unused_or_closing(self) -> None:
        base = self.models["tp-fin"]["warnings"]
        self.check(base and all(w["severity"] == "warning" for w in base), "FIN: missing unused rates are warnings only")
        self.check(any("USD" in w["message"] and "closing" in w["message"] and "2026-08" in w["message"] for w in base), "FIN: missing USD closing prior period warning")
        altered = deepcopy(self.inputs["tp-fin"])
        gl = next(t for t in altered["tables"] if t["name"] == "GL_Actuals_2026-09")
        currency_index = gl["header"].index("Currency")
        gl["rows"][0][currency_index] = "EUR"
        snapshot = build_snapshot(altered)
        warnings = warning_classification(snapshot, altered["tables"])
        self.check(any(w["code"] == "AF_MISSING_DATA" and w["severity"] == "blocker" and "EUR" in w["message"] and "average" in w["message"] for w in warnings), "FIN: used missing EUR average is blocker")
        self.check(any(w["severity"] == "warning" and "USD" in w["message"] and "closing" in w["message"] for w in warnings), "FIN: closing remains warning")


if __name__ == "__main__":
    unittest.main()
