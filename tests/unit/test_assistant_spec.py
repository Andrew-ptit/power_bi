"""Kiểm biên assembler WL4 trên Brief synthetic và quyết định tường minh."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_brief import brief_hash
from pbip_assistant.sources.assistant_decisions import build_decisions, decisions_hash
from pbip_assistant.sources.assistant_execution import compile_steps
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_pack import load_pack
from pbip_assistant.sources.assistant_spec import build_spec, spec_fingerprint
from tests.support.paths import FIXTURES


GOLDEN = FIXTURES / "assistant"


def load(scenario, name):
    return json.loads((GOLDEN / scenario / name).read_text(encoding="utf-8"))


def model(scenario="tp-fin", *, brief=None, overrides=None, omit=None, metadata=True):
    """Caller tái hiện lựa chọn/audit synthetic từ fixture; producer không bịa consent."""
    brief = deepcopy(brief) if brief is not None else load(scenario, "wl3_brief.json")
    expected = load(scenario, "wl3_decisions.json")
    choices = {entry["subProblemId"]: entry["optionId"] for entry in expected["decisions"]}
    choices.update(overrides or {})
    if omit:
        choices.pop(omit)
    acks = {entry["subProblemId"]: entry["acknowledged"] for entry in expected["acknowledgements"]}
    audit = None
    if metadata:
        first = expected["decisions"][0]
        audit = {field: first[field] for field in ("decidedAt", "decidedBy", "rationale")}
        audit["acknowledgementNotes"] = {entry["subProblemId"]: entry["note"] for entry in expected["acknowledgements"]}
    decisions = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=audit)
    return brief, decisions, load_pack("fin-pl-v1" if scenario == "tp-fin" else "generic")


def create(data, scenario="tp-fin", **kwargs):
    kwargs.setdefault("created_at", load(scenario, "wl4_execution_spec.json")["createdAt"])
    return build_spec(*data, **kwargs)


class AssistantSpecTests(unittest.TestCase):
    def test_shape_hash_bindings_and_deterministic_identity(self):
        for scenario in ("tp-fin", "tp-sales"):
            data = model(scenario)
            result = create(data, scenario)
            self.assertEqual(set(result), set(load(scenario, "wl4_execution_spec.json")))
            self.assertRegex(result["id"], r"^spec_[a-f0-9]{24}$")
            for field in ("snapshotHash", "briefHash"):
                self.assertEqual(result[field], data[0][field])
            self.assertEqual(result["decisionsHash"], data[1]["decisionsHash"])
            self.assertEqual(result["fingerprint"], spec_fingerprint(result))
            self.assertEqual(result, create(data, scenario))

    def test_inputs_and_repeated_results_share_no_mutable_state(self):
        data = model()
        before = deepcopy(data)
        first, second = create(data), create(data)
        first["steps"][0]["params"]["operation"] = "changed"
        first["unverifiedAssumptions"].clear()
        first["labels"].clear()
        self.assertEqual(data, before)
        self.assertEqual(second, create(data))

    def test_creation_timestamp_is_explicit_without_hidden_clock(self):
        for timestamp in (None, "", 123, "2026-10-28", "2026-10-28T10:00:00", "not-a-date"):
            with self.subTest(timestamp=timestamp), self.assertRaises(InputError) as caught:
                build_spec(*model(), created_at=timestamp)
            self.assertEqual(caught.exception.code, "AF_SPEC_INVALID")
        with self.assertRaises(InputError):
            build_spec(*model())

    def test_creation_metadata_is_preserved_and_bound_to_fingerprint(self):
        first = create(model())
        second = create(model(), created_at="2026-10-28T10:00:00+07:00")
        self.assertEqual(second["createdAt"], "2026-10-28T10:00:00+07:00")
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertNotEqual(first["id"], second["id"])

    def test_hash_recomputes_independently_and_binds_step_content(self):
        result = create(model())
        self.assertEqual(result["fingerprint"], canonical_hash({k: result[k] for k in result["hashBasis"]}))
        result["steps"][0]["label"] = "Nhãn compile thay đổi"
        self.assertNotEqual(result["fingerprint"], spec_fingerprint(result))

    def test_hash_basis_cannot_omit_decisions_or_add_unknown_fields(self):
        for field in ("decisionsHash", "steps", "labels", "unverifiedAssumptions"):
            result = create(model())
            result["hashBasis"].remove(field)
            with self.subTest(field=field), self.assertRaises(InputError):
                spec_fingerprint(result)
        result = create(model())
        result["unhashedPolicy"] = "A"
        with self.assertRaises(InputError):
            spec_fingerprint(result)

    def test_fingerprint_rejects_malformed_hashes_labels_variants_and_types(self):
        changes = {"snapshotHash": "sha256:bad", "id": "spec_bad", "stale": 0,
                   "labels": ["verified"], "unverifiedAssumptions": ["asm_bad"],
                   "variantOf": "other", "variantReason": "changed"}
        for field, value in changes.items():
            result = create(model())
            result[field] = value
            with self.subTest(field=field), self.assertRaises(InputError):
                spec_fingerprint(result)

    def test_complete_draft_without_user_metadata_cannot_freeze(self):
        data = model(metadata=False)
        self.assertTrue(data[1]["freezeBlocked"])
        with self.assertRaises(InputError) as caught:
            create(data)
        self.assertEqual(caught.exception.code, "AF_MISSING_DATA")

    def test_partial_blocker_cannot_be_filled_from_recommendation(self):
        data = model(omit="SP-3")
        before = deepcopy(data)
        with self.assertRaises(InputError) as caught:
            create(data)
        self.assertEqual(caught.exception.code, "AF_MISSING_DATA")
        self.assertEqual(data, before)
        self.assertNotIn("SP-3", {entry["subProblemId"] for entry in data[1]["decisions"]})

    def test_forged_freeze_flag_is_rejected_even_after_rehash(self):
        data = model(metadata=False)
        data[1]["freezeBlocked"] = False
        data[1]["decisionsHash"] = decisions_hash(data[1])
        with self.assertRaises(InputError):
            create(data)

    def test_tampered_brief_is_rejected_without_changing_decisions(self):
        data = model()
        data[0]["prompt"] = "Đề bài mới"
        with self.assertRaises(InputError) as caught:
            create(data)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_decisions_from_other_valid_brief_revision_are_stale(self):
        data = model()
        data[0]["prompt"] = "Revision mới"
        data[0]["briefHash"] = brief_hash(data[0])
        with self.assertRaises(InputError) as caught:
            create(data)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_assumptions_remain_unverified_after_policy_choices(self):
        data = model()
        result = create(data)
        self.assertEqual(result["unverifiedAssumptions"], [entry["id"] for entry in data[0]["assumptions"]])
        self.assertIn("unverified", result["labels"])
        self.assertNotIn("verified", result["labels"])

    def test_invalid_or_duplicate_assumption_ids_cannot_enter_spec(self):
        for value in ("asm_bad", None, "duplicate"):
            brief = model()[0]
            brief["assumptions"][0]["id"] = brief["assumptions"][1]["id"] if value == "duplicate" else value
            brief["briefHash"] = brief_hash(brief)
            with self.subTest(value=value), self.assertRaises(InputError):
                create(model(brief=brief))

    def test_empty_assumption_ledger_does_not_invent_an_assumption(self):
        brief = model()[0]
        brief["assumptions"] = []
        brief["labels"] = []
        brief["briefHash"] = brief_hash(brief)
        result = create(model(brief=brief))
        self.assertEqual((result["unverifiedAssumptions"], result["labels"]), ([], []))

    def test_stale_brief_label_cannot_be_silently_reset(self):
        brief = model()[0]
        brief["labels"].append("stale")
        brief["briefHash"] = brief_hash(brief)
        with self.assertRaises(InputError) as caught:
            create(model(brief=brief))
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_compiler_pending_or_blocked_output_cannot_become_final_spec(self):
        data = model()
        for status, guard in (("pending", None), ("blocked", "AF_FANOUT_RISK")):
            steps = compile_steps(*data)
            steps[-1].update(status=status, guard=guard)
            with patch("pbip_assistant.sources.assistant_spec.compile_steps", return_value=steps):
                with self.subTest(status=status), self.assertRaises(InputError) as caught:
                    create(data)
            self.assertEqual(caught.exception.code, "AF_MISSING_DATA")

    def test_valid_graph_without_executable_decision_coverage_is_rejected(self):
        data = model()
        steps = compile_steps(*data)
        steps.pop(-2)  # Bỏ riêng calc SP-1; vẫn dựng graph dữ liệu hợp lệ.
        steps[-1]["inputs"] = [steps[-2]["output"]]
        steps[-1]["dependsOn"] = [steps[-2]["id"]]
        with patch("pbip_assistant.sources.assistant_spec.compile_steps", return_value=steps):
            with self.assertRaises(InputError) as caught:
                create(data)
        self.assertEqual(caught.exception.code, "AF_SPEC_INVALID")


if __name__ == "__main__":
    unittest.main()
