"""Unit test DomainPack: schema đóng, không số tiền và chỉ resource cho phép."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pbip_assistant.core.errors import InputError
from pbip_assistant.core.resources import package_path, schema_path
from pbip_assistant.sources import assistant_pack as packs
from tests.support.json_schema_oracle import validate


class AssistantPackTests(unittest.TestCase):
    def test_both_bundled_packs_load_and_validate_against_canonical_schema(self) -> None:
        schema = json.loads(schema_path("assistant_domain_pack.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        for identifier, industry, count in (("fin-pl-v1", "finance", 10), ("generic", "generic", 5)):
            with self.subTest(pack=identifier):
                pack = packs.load_pack(identifier)
                self.assertEqual((pack["id"], pack["industry"], len(pack["policies"])), (identifier, industry, count))
                self.assertEqual(validate(pack, schema), [])
                self.assertIsNone(packs.validate_pack(pack))

    def test_every_schema_object_is_closed_and_required_all(self) -> None:
        schema = json.loads(schema_path("assistant_domain_pack.schema.json").read_text(encoding="utf-8"))
        objects = []

        def walk(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    objects.append(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(schema)
        self.assertGreaterEqual(len(objects), 9)
        for rule in objects:
            self.assertIs(rule["additionalProperties"], False)
            self.assertEqual(set(rule["required"]), set(rule["properties"]))

    def test_resource_loader_uses_canonical_resolver_and_allowlisted_ids(self) -> None:
        with patch.object(packs, "package_path", wraps=package_path) as resolver:
            packs.load_pack("fin-pl-v1")
        resolver.assert_called_once_with("sources", "packs", "fin_pl_v1.json")
        for invalid in ("../generic", "fin_pl_v1", "unknown", "generic.json", "C:/private.json", None, []):
            with self.subTest(kind=type(invalid).__name__):
                with patch.object(packs, "package_path") as reader:
                    with self.assertRaises(InputError):
                        packs.load_pack(invalid)
                    reader.assert_not_called()

    def test_loader_returns_independent_objects_and_validate_does_not_mutate(self) -> None:
        pack = packs.load_pack("generic")
        previous = deepcopy(pack)
        packs.validate_pack(pack)
        self.assertEqual(pack, previous)
        pack["policies"][0]["options"][0]["label"] = "Nhãn thay đổi trong bản sao."
        self.assertEqual(packs.load_pack("generic"), previous)

    def test_pack_files_are_canonical_utf8_lf_and_schema_is_canonical(self) -> None:
        paths = [schema_path("assistant_domain_pack.schema.json"),
                 package_path("sources", "packs", "fin_pl_v1.json"),
                 package_path("sources", "packs", "generic.json")]
        for path in paths:
            payload = path.read_bytes()
            data = json.loads(payload)
            self.assertEqual(payload, (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"), path.name)

    def test_select_pack_is_driven_by_consistent_wl2_metadata(self) -> None:
        self.assertEqual(packs.select_pack({"pack": {"id": "fin-pl-v1", "genericMode": False}}), "fin-pl-v1")
        self.assertEqual(packs.select_pack({"pack": {"id": "generic", "genericMode": True}}), "generic")
        for invalid in (None, {}, {"pack": {}}, {"pack": {"id": "generic", "genericMode": False}},
                        {"pack": {"id": "fin-pl-v1", "genericMode": True}},
                        {"pack": {"id": "generic", "genericMode": 1}}):
            with self.assertRaises(InputError):
                packs.select_pack(invalid)

    def test_policy_ids_statuses_and_engine_verification_rule_match_contract(self) -> None:
        fin = packs.load_pack("fin-pl-v1")
        generic = packs.load_pack("generic")
        self.assertEqual([p["subProblemId"] for p in fin["policies"]], [f"SP-{i}" for i in range(1, 11)])
        self.assertEqual([p["status"] for p in fin["policies"]],
                         ["assumed", "assumed", "assumed", "inferred", "inferred", "inferred", "missing_data", "inferred", "conflict", "missing_data"])
        self.assertEqual([p["provenance"] for p in fin["policies"]], ["pack"] * 3 + ["data"] * 7)
        self.assertEqual([p["status"] for p in generic["policies"]], ["assumed", "assumed", "conflict", "inferred", "missing_data"])
        self.assertTrue(all(p["provenance"] == "data" for p in generic["policies"]))
        self.assertEqual(fin["policies"][3]["evaluationRule"], "measured_dedupe_sign")
        self.assertTrue(all(p["status"] != "verified" for p in fin["policies"] + generic["policies"]))
        for policy in fin["policies"] + generic["policies"]:
            self.assertEqual([o["id"] for o in policy["options"]], ["A", "B"])
            self.assertEqual([o["id"] for o in policy["options"] if o["recommended"]], [policy["proposedOptionId"]])

    def test_output_contract_insights_assumptions_and_reallocation_prose(self) -> None:
        fin, generic = packs.load_pack("fin-pl-v1"), packs.load_pack("generic")
        self.assertEqual(fin["outputContract"]["grain"], ["pnlLine", "accountCode", "costCenter", "entityCode"])
        self.assertEqual([m["name"] for m in fin["outputContract"]["measures"]], ["NetRevenue", "GrossProfit"])
        self.assertEqual(generic["outputContract"]["grain"], ["region"])
        self.assertEqual([m["name"] for m in generic["outputContract"]["measures"]], ["NetRevenue"])
        self.assertIn("Gom FX vào Op", fin["policies"][1]["options"][1]["label"])
        self.assertNotIn("cố định", fin["policies"][1]["options"][1]["label"])
        for pack in (fin, generic):
            self.assertEqual(pack["outputContract"]["currency"], "VND")
            self.assertEqual({i["kind"] for i in pack["insights"]}, {"hypothesis", "slice"})
            self.assertTrue(all(a["source"] in {"data", "pack"} for a in pack["assumptions"]))

    def test_packs_declare_only_registry_formulas_and_matching_units_expressions(self) -> None:
        from pbip_assistant.sources.assistant_findings import formulas
        registry = {entry["formulaId"]: entry for entry in formulas()}
        for pack_id in ("fin-pl-v1", "generic"):
            pack = packs.load_pack(pack_id)
            for entry in pack["metrics"]:
                self.assertIn(entry["formulaId"], registry)
                self.assertEqual((entry["expression"], entry["unit"]),
                                 (registry[entry["formulaId"]]["expression"], registry[entry["formulaId"]]["unit"]))

    def test_numeric_money_numeric_strings_and_money_prose_are_rejected(self) -> None:
        mutations = []
        for value in (10000000, 10000000.0, "10000000", "10.000.000"):
            item = packs.load_pack("generic")
            item["total"] = value
            mutations.append(item)
        for value in ("Tổng doanh thu 43839000000", "Chênh lệch 10.000.000 VND", "USD 200"):
            item = packs.load_pack("generic")
            item["insights"][0]["statement"] = value
            mutations.append(item)
        for candidate in mutations:
            with self.assertRaises(InputError):
                packs.validate_pack(candidate)

    def test_missing_unknown_and_wrong_typed_fields_are_rejected(self) -> None:
        candidates = []
        for change in (lambda p: p.pop("version"), lambda p: p.update(extra="unexpected"),
                       lambda p: p["policies"][0].update(blocker="false"),
                       lambda p: p["policies"][0]["options"][0].update(extra="unexpected"),
                       lambda p: p["metrics"][0].update(formulaId="not-a-formula")):
            pack = packs.load_pack("generic")
            change(pack)
            candidates.append(pack)
        for candidate in candidates:
            with self.assertRaises(InputError):
                packs.validate_pack(candidate)

    def test_duplicate_ids_broken_references_and_recommendations_are_rejected(self) -> None:
        changes = (
            lambda p: p["metrics"].append(deepcopy(p["metrics"][0])),
            lambda p: p["policies"].append(deepcopy(p["policies"][0])),
            lambda p: p["policies"][0].update(consequenceMetric="fm_missing"),
            lambda p: p["outputContract"]["measures"][0].update(formulaId="fm_missing"),
            lambda p: p["insights"][0].update(formulaId="fm_missing"),
            lambda p: p["policies"][0]["options"][1].update(id="A"),
            lambda p: p["policies"][0]["options"][1].update(recommended=True),
            lambda p: p["policies"][0].update(proposedOptionId="B"),
            lambda p: p["outputContract"]["measures"][0].update(formulaId="fm_orders"),
            lambda p: p["policies"][0].update(consequenceMetric="fm_orders"),
        )
        for index, change in enumerate(changes):
            candidate = packs.load_pack("generic")
            change(candidate)
            with self.subTest(case=index):
                with self.assertRaises(InputError):
                    packs.validate_pack(candidate)

    def test_missing_data_cannot_publish_a_consequence_and_rule_cannot_grant_verified(self) -> None:
        for change in (lambda p: p["policies"][-1].update(consequenceMetric="fm_orders"),
                       lambda p: p["policies"][-1].update(labels=[]),
                       lambda p: p["policies"][0].update(status="verified"),
                       lambda p: p["policies"][0].update(evaluationRule="measured_dedupe_sign"),
                       lambda p: p["assumptions"][0].update(source="llm")):
            candidate = packs.load_pack("generic")
            change(candidate)
            with self.assertRaises(InputError):
                packs.validate_pack(candidate)

    def test_resource_invalid_json_duplicate_keys_and_nonfinite_are_rejected(self) -> None:
        from io import BytesIO
        for payload in (b"not-json", b'{"id":"generic","id":"generic"}', b'{"value":NaN}', b"[]",
                        b" " * (packs._MAX_RESOURCE_BYTES + 1)):
            with self.subTest(payload_kind=payload[:1].decode("ascii")):
                with patch.object(Path, "open", return_value=BytesIO(payload)):
                    with self.assertRaises(InputError):
                        packs.load_pack("generic")

    def test_unsupported_schema_keyword_and_cyclic_inputs_fail_closed(self) -> None:
        candidate = packs.load_pack("generic")
        candidate["cycle"] = candidate
        with self.assertRaises(InputError):
            packs.validate_pack(candidate)
        valid = packs.load_pack("generic")
        schema = json.loads(schema_path("assistant_domain_pack.schema.json").read_text(encoding="utf-8"))
        schema["$defs"]["metric"]["unsupported"] = True
        with patch.object(packs, "_resource_json", return_value=schema):
            with self.assertRaises(InputError):
                packs.validate_pack(valid)
        malformed = json.loads(schema_path("assistant_domain_pack.schema.json").read_text(encoding="utf-8"))
        malformed["properties"] = []
        with patch.object(packs, "_resource_json", return_value=malformed):
            with self.assertRaises(InputError):
                packs.validate_pack(valid)


if __name__ == "__main__":
    unittest.main()
