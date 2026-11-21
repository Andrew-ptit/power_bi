"""Unit boundaries for the deterministic Brief assembler over synthetic sources."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_brief import build_brief, brief_hash, build_unresolved_decisions
from pbip_assistant.sources.assistant_ingest import canonical_hash, resolve
from pbip_assistant.sources.assistant_pack import load_pack, select_pack
from pbip_assistant.sources.assistant_profile import build_snapshot
from pbip_assistant.sources.assistant_understand import build_understand
from tests.support.paths import FIXTURES


def inputs(scenario: str = "tp-fin") -> tuple:
    root = FIXTURES / "assistant" / scenario
    requests = [{"kind": "csv", "path": "source/" + p.name} for p in sorted((root / "source").glob("*.csv"))]
    if scenario == "tp-sales":
        requests.append({"kind": "folder", "path": "source/orders", "name": "Orders"})
    ingested = resolve({"root": root}, requests)
    if ingested["errors"] or ingested["requiresRename"]:
        raise AssertionError("Synthetic ingest must succeed")
    snapshot = build_snapshot(ingested)
    understood = build_understand(ingested["tables"], snapshot)
    return ingested, snapshot, understood, load_pack(select_pack(understood))


def mutated_inputs(original: dict) -> tuple:
    changed = deepcopy(original)
    ledger = next(t for t in changed["tables"] if "DebitCredit" in t["header"])
    fields = ledger["header"]
    row = deepcopy(next(r for r in ledger["rows"] if r[fields.index("AccountCode")] == "511900"))
    for field, value in {"DocNo": "MUTATION-REBATE", "LineNo": "1", "Amount": "10000000",
                         "DebitCredit": "D", "Currency": "VND", "PartnerEntity": ""}.items():
        row[fields.index(field)] = value
    ledger["rows"].append(row)
    # This is a new in-memory input, not a claim that the persisted CSV changed.
    for source in changed["sources"]:
        source["hash"] = canonical_hash([{"header": t["header"], "rows": t["rows"]}
                                          for t in changed["tables"] if t["sourceId"] == source["id"]])
    snapshot = build_snapshot(changed)
    understood = build_understand(changed["tables"], snapshot)
    return changed, snapshot, understood, load_pack(select_pack(understood))


def make(data: tuple, *, prompt="Báo cáo synthetic", **options) -> dict:
    ingested, snapshot, understood, pack = data
    return build_brief(ingested["tables"], snapshot, understood, pack, prompt, **options)


def values(brief: dict) -> dict:
    return {f["value"]["formulaId"]: Decimal(f["value"]["value"]) for f in brief["findings"]}


class AssistantBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fin = inputs()
        cls.sales = inputs("tp-sales")

    def test_shape_period_hash_and_engine_values(self) -> None:
        result = make(self.fin)
        self.assertEqual(result["outputContract"]["period"]["from"], "2026-09-01")
        self.assertEqual(result["outputContract"]["period"]["to"], "2026-09-30")
        self.assertEqual(values(result)["fm_net_revenue_actual"], Decimal("43839000000"))
        self.assertEqual(result["briefHash"], brief_hash(result))
        self.assertEqual(result["briefHash"], canonical_hash({k: result[k] for k in result["hashBasis"]}))
        self.assertEqual(make(self.fin), result)

    def test_sales_period_and_no_artificial_fx(self) -> None:
        result = make(self.sales)
        self.assertEqual((result["outputContract"]["period"]["from"], result["outputContract"]["period"]["to"]),
                         ("2026-07-01", "2026-09-30"))
        self.assertEqual((result["scenarios"], result["delta"]), ([], None))
        self.assertEqual(values(result)["fm_revenue_excluding_cancelled"], Decimal("133942500"))

    def test_mutation_recomputes_rebate_net_consequence_and_variance(self) -> None:
        first = make(self.fin)
        changed = make(mutated_inputs(self.fin[0]))
        before, after = values(first), values(changed)
        self.assertEqual(after["fm_rebate_actual"], Decimal("-102000000"))
        self.assertEqual(after["fm_net_revenue_actual"], before["fm_net_revenue_actual"] - Decimal("10000000"))
        self.assertEqual(after["fm_sp1_option_b_delta"], Decimal("102000000"))
        self.assertEqual(after["fm_variance"], before["fm_variance"] - Decimal("10000000"))
        self.assertNotEqual(changed["briefHash"], first["briefHash"])

    def test_inputs_and_returned_model_do_not_share_state(self) -> None:
        data = deepcopy(self.fin)
        before = deepcopy(data)
        result = make(data)
        self.assertEqual(data, before)
        result["outputContract"]["grain"].reverse()
        result["subProblems"][0]["options"][0]["label"] = "changed"
        result["assumptions"][0]["statement"] = "changed"
        self.assertEqual(data, before)

    def test_pack_authored_content_is_not_verified_and_expressions_are_not_executed(self) -> None:
        data = deepcopy(self.fin)
        data[3]["metrics"][0]["expression"] = "__import__('invalid_module_must_not_be_imported')"
        result = make(data)
        for finding in result["findings"]:
            self.assertEqual((finding["status"], finding["provenance"]), ("inferred", "pack"))
        verified = [sp for sp in result["subProblems"] if sp["status"] == "verified"]
        self.assertEqual([sp["id"] for sp in verified], ["SP-4"])
        self.assertEqual(verified[0]["provenance"], "data")
        self.assertTrue(any(e["kind"] == "exact_duplicates" for e in verified[0]["evidence"]))
        for assumption in result["assumptions"]:
            self.assertTrue(any(e["kind"] == "authored_pack" for e in assumption["evidence"]))
            if assumption["source"] == "data":
                self.assertTrue(any(e["kind"] == "source" and e["ref"] == data[1]["snapshotHash"]
                                    for e in assumption["evidence"]))

    def test_stale_understand_snapshot_and_raw_are_rejected(self) -> None:
        for target in ("understand", "snapshot", "raw"):
            data = deepcopy(self.fin)
            if target == "understand":
                data[2]["understandHash"] = canonical_hash("stale")
            elif target == "snapshot":
                data[1]["snapshotHash"] = canonical_hash("stale")
            else:
                data[0]["tables"][0]["rows"].append(deepcopy(data[0]["tables"][0]["rows"][0]))
            with self.assertRaises((InputError, ValueError)):
                make(data)

    def test_bad_pack_prompt_and_policy_ids_are_rejected(self) -> None:
        with self.assertRaises(InputError):
            make(self.fin, prompt=" ")
        with self.assertRaises(InputError):
            make(self.fin, policy_unresolved={"SP-99"})
        data = list(deepcopy(self.fin))
        data[3] = load_pack("generic")
        with self.assertRaises(InputError):
            make(data)
        for malformed in (None, [], "invalid"):
            with self.assertRaises(InputError):
                build_brief(self.fin[0]["tables"], malformed, self.fin[2], self.fin[3], "Synthetic")
            with self.assertRaises(InputError):
                build_unresolved_decisions(malformed)

    def test_supported_output_override_is_hash_bound_and_unsupported_scope_is_blocked(self) -> None:
        original = make(self.fin)
        result = make(self.fin, output_contract_override={"grain": ["pnlLine"],
                      "measures": [deepcopy(self.fin[3]["outputContract"]["measures"][0])]})
        self.assertEqual(result["outputContract"]["grain"], ["pnlLine"])
        self.assertNotEqual(result["briefHash"], original["briefHash"])
        for override in ({"currency": "USD"}, {"grain": ["unsupported"]}, {"filters": []},
                         {"period": {"from": "2026-08-01", "to": "2026-08-31", "label": "T8"}}):
            with self.assertRaises(InputError):
                make(self.fin, output_contract_override=override)

    def test_unresolved_helper_blocks_without_approval_and_hash_binds_brief(self) -> None:
        result = make(self.fin, policy_unresolved={"SP-1", "SP-2", "SP-3"})
        decision = build_unresolved_decisions(result)
        self.assertTrue(decision["freezeBlocked"])
        self.assertEqual(decision["decisions"], [])
        self.assertGreaterEqual(len(decision["checklist"]), 3)
        self.assertEqual(decision["briefHash"], result["briefHash"])
        self.assertEqual(decision["decisionsHash"], canonical_hash({k: decision[k] for k in decision["hashBasis"]}))
        result["prompt"] = "changed"
        with self.assertRaises(InputError):
            build_unresolved_decisions(result)

    def test_hash_covers_content_and_prompt_and_rejects_unbound_extensions(self) -> None:
        result = make(self.fin)
        self.assertNotEqual(make(self.fin, prompt="Một bài toán khác")["briefHash"], result["briefHash"])
        changed = deepcopy(result)
        changed["hiddenPolicy"] = True
        with self.assertRaises(InputError):
            brief_hash(changed)
        for key in result["hashBasis"]:
            changed = deepcopy(result)
            changed[key] = "changed"
            self.assertNotEqual(brief_hash(changed), result["briefHash"], key)

    def test_build_is_local_and_does_not_open_network(self) -> None:
        with patch.object(socket, "socket", side_effect=AssertionError("WL3 must remain local")):
            result = make(self.fin)
        self.assertEqual(result["snapshotHash"], self.fin[1]["snapshotHash"])


if __name__ == "__main__":
    unittest.main()
