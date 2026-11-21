"""Hợp đồng quyết định WL4 trên Brief synthetic; không sửa artifact nguồn."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_brief import brief_hash
from pbip_assistant.sources.assistant_decisions import (
    build_decisions, decisions_hash, freeze_blocked, invalidate_message, validate_decisions,
)
from pbip_assistant.sources.assistant_ingest import canonical_hash
from tests.support.paths import FIXTURES


ROOT = FIXTURES / "assistant"


def load(scenario: str, name: str) -> dict:
    return json.loads((ROOT / scenario / name).read_text(encoding="utf-8"))


def requests(scenario: str = "tp-fin") -> tuple[dict, dict, dict, dict, dict]:
    brief = load(scenario, "wl3_brief.json")
    golden = load(scenario, "wl3_decisions.json")
    choices = {entry["subProblemId"]: entry["optionId"] for entry in golden["decisions"]}
    acks = {entry["subProblemId"]: entry["acknowledged"] for entry in golden["acknowledgements"]}
    metadata = {field: golden["decisions"][0][field] for field in ("decidedAt", "decidedBy", "rationale")}
    metadata["acknowledgementNotes"] = {entry["subProblemId"]: entry["note"] for entry in golden["acknowledgements"]}
    return brief, golden, choices, acks, metadata


def build(scenario: str = "tp-fin") -> tuple[dict, dict]:
    brief, _, choices, acks, metadata = requests(scenario)
    return brief, build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)


def rehash(document: dict) -> dict:
    document["decisionsHash"] = canonical_hash({key: document[key] for key in document["hashBasis"]})
    return document


class AssistantDecisionsTests(unittest.TestCase):
    def test_fin_explicit_choices_and_metadata_match_golden_without_mutating_brief(self) -> None:
        brief, golden, choices, acks, metadata = requests()
        before = deepcopy((brief, choices, acks, metadata))
        actual = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
        self.assertEqual(actual["decisions"], golden["decisions"])
        self.assertEqual(actual["acknowledgements"], golden["acknowledgements"])
        self.assertIs(actual["freezeBlocked"], False)
        validate_decisions(brief, actual)
        self.assertEqual((brief, choices, acks, metadata), before)
        self.assertTrue(all(problem["chosenOptionId"] is None for problem in brief["subProblems"]))

    def test_sales_metadata_is_caller_supplied_and_arrays_match_golden(self) -> None:
        brief, golden, choices, acks, metadata = requests("tp-sales")
        actual = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
        self.assertEqual(actual["decisions"], golden["decisions"])
        self.assertEqual(actual["acknowledgements"], golden["acknowledgements"])
        self.assertEqual(freeze_blocked(brief, actual), {"blocked": False, "blockers": []})

    def test_missing_audit_metadata_is_a_draft_and_never_fabricates_human_or_time(self) -> None:
        brief, _, choices, acks, metadata = requests()
        for audit in (None, {"decidedBy": "user"}, {"decidedAt": metadata["decidedAt"]}):
            with self.subTest(audit=audit):
                actual = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=audit)
                self.assertTrue(actual["freezeBlocked"])
                self.assertTrue(freeze_blocked(brief, actual)["blocked"])
        actual = build_decisions(brief, choices=choices, acknowledgements=acks)
        for entry in actual["decisions"]:
            self.assertIsNone(entry["decidedBy"])
            self.assertIsNone(entry["decidedAt"])
            self.assertIsNone(entry["rationale"])
        self.assertTrue(all(entry["note"] is None for entry in actual["acknowledgements"]))

    def test_missing_blocker_stays_partial_and_validation_rejects_incomplete_coverage(self) -> None:
        brief, _, choices, acks, metadata = requests()
        choices.pop("SP-3")
        actual = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
        state = freeze_blocked(brief, actual)
        self.assertTrue(actual["freezeBlocked"])
        self.assertTrue(state["blocked"])
        self.assertTrue(any("SP-3" in entry["message"] and "chưa chốt" in entry["message"] for entry in state["blockers"]))
        self.assertTrue(all((entry["code"], entry["severity"]) == ("AF_MISSING_DATA", "warning") for entry in state["blockers"]))
        self.assertNotIn("SP-3", {entry["subProblemId"] for entry in actual["decisions"]})
        with self.assertRaises(InputError):
            validate_decisions(brief, actual)

    def test_missing_nonblocker_also_blocks_instead_of_silently_using_recommendation(self) -> None:
        brief, _, choices, acks, metadata = requests()
        choices.pop("SP-5")
        actual = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
        self.assertTrue(freeze_blocked(brief, actual)["blocked"])
        self.assertTrue(actual["freezeBlocked"])
        self.assertNotIn("SP-5", {entry["subProblemId"] for entry in actual["decisions"]})

    def test_risk_ack_does_not_substitute_for_any_data_affecting_choice(self) -> None:
        for identifier in ("SP-3", "SP-5"):
            brief, _, choices, acks, metadata = requests()
            choices.pop(identifier)
            acks[identifier] = "risk"
            actual = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
            self.assertTrue(freeze_blocked(brief, actual)["blocked"], identifier)
            self.assertEqual(next(entry["acknowledged"] for entry in actual["acknowledgements"] if entry["subProblemId"] == identifier), "risk")
            self.assertNotIn(identifier, {entry["subProblemId"] for entry in actual["decisions"]})

    def test_missing_data_requires_out_of_scope_ack_and_never_becomes_available_by_choice(self) -> None:
        for replacement in ("A", "B", "risk"):
            brief, _, choices, acks, metadata = requests()
            acks.pop("SP-7")
            metadata["acknowledgementNotes"].pop("SP-7")
            if replacement == "risk":
                acks["SP-7"] = "risk"
            else:
                choices["SP-7"] = replacement
            actual = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
            self.assertTrue(freeze_blocked(brief, actual)["blocked"])
        brief, actual = build()
        self.assertFalse(freeze_blocked(brief, actual)["blocked"])

    def test_ack_only_remains_draft_and_does_not_invent_audit_sentinel_decisions(self) -> None:
        brief, _, _, _, metadata = requests()
        acks = {problem["id"]: "risk" for problem in brief["subProblems"]}
        metadata["acknowledgementNotes"] = {}
        actual = build_decisions(brief, choices={}, acknowledgements=acks, decision_metadata=metadata)
        self.assertEqual(actual["decisions"], [])
        self.assertEqual(len(actual["acknowledgements"]), len(brief["subProblems"]))
        self.assertTrue(actual["freezeBlocked"])
        self.assertTrue(all(set(entry) == {"subProblemId", "acknowledged", "note"} for entry in actual["acknowledgements"]))

    def test_unknown_option_id_overlap_extra_and_bad_input_maps_raise(self) -> None:
        brief, _, choices, acks, metadata = requests()
        cases = [({**choices, "SP-1": "Z"}, acks), ({**choices, "SP-99": "A"}, acks),
                 (choices, {**acks, "SP-1": "risk"}), (choices, {**acks, "SP-7": "unsupported"}),
                 ({**choices, "SP-1": None}, acks), ([], acks), (choices, [])]
        for choice_map, ack_map in cases:
            with self.subTest(shape=(type(choice_map).__name__, type(ack_map).__name__)):
                with self.assertRaises(InputError):
                    build_decisions(brief, choices=choice_map, acknowledgements=ack_map, decision_metadata=metadata)

    def test_metadata_rejects_unknown_fields_fake_actor_and_invalid_time(self) -> None:
        brief, _, choices, acks, _ = requests()
        for metadata in ({"decidedBy": "llm"}, {"decidedAt": "2026-10-26"}, {"decidedAt": "invalid"},
                         {"decidedAt": "2026-10-26T09:30:00"}, {"provenance": "user"},
                         {"acknowledgementNotes": {"SP-99": "unrelated"}}, {"rationale": 1}, []):
            with self.assertRaises(InputError):
                build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)

    def test_decisions_bind_the_exact_brief_snapshot_and_understand_revision(self) -> None:
        brief, actual = build()
        for field in ("snapshotHash", "understandHash", "briefHash"):
            changed = deepcopy(actual)
            changed[field] = canonical_hash("other revision")
            rehash(changed)
            with self.assertRaises(InputError) as caught:
                validate_decisions(brief, changed)
            self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
        changed_brief = deepcopy(brief)
        changed_brief["prompt"] = "Revision đã thay đổi"
        changed_brief["briefHash"] = brief_hash(changed_brief)
        with self.assertRaises(InputError):
            validate_decisions(changed_brief, actual)

    def test_tampered_hash_and_forged_freeze_flag_are_rejected(self) -> None:
        brief, actual = build()
        wrong = deepcopy(actual)
        wrong["decisions"][0]["optionId"] = "B"
        with self.assertRaises(InputError):
            validate_decisions(brief, wrong)
        wrong = deepcopy(actual)
        wrong["freezeBlocked"] = True
        rehash(wrong)
        with self.assertRaises(InputError):
            validate_decisions(brief, wrong)

    def test_duplicate_entries_and_malformed_documents_fail_closed(self) -> None:
        brief, actual = build()
        candidates = [None, {}, {**deepcopy(actual), "decisions": "bad"}]
        duplicate = deepcopy(actual)
        duplicate["decisions"].append(deepcopy(duplicate["decisions"][0]))
        rehash(duplicate)
        candidates.append(duplicate)
        overlap = deepcopy(actual)
        overlap["acknowledgements"][0]["subProblemId"] = "SP-1"
        rehash(overlap)
        candidates.append(overlap)
        bad_entry = deepcopy(actual)
        bad_entry["decisions"][0]["subProblemId"] = []
        candidates.append(bad_entry)
        for candidate in candidates:
            with self.assertRaises(InputError):
                validate_decisions(brief, candidate)

    def test_hash_basis_is_complete_and_known_fixture_variant_null_compatibility_is_explicit(self) -> None:
        brief, golden, _, _, _ = requests()
        _, actual = build()
        self.assertEqual(actual["hashBasis"], ["snapshotHash", "understandHash", "briefHash", "decisions", "acknowledgements", "freezeBlocked"])
        self.assertEqual(actual["decisionsHash"], canonical_hash({key: actual[key] for key in actual["hashBasis"]}))
        self.assertEqual(decisions_hash(golden), golden["decisionsHash"])
        validate_decisions(brief, golden)
        for candidate in ({**actual, "hashBasis": ["briefHash"]}, {**actual, "hiddenPolicy": "unbound"},
                          {**actual, "variantReason": "unbound mutation"}):
            with self.assertRaises(InputError):
                decisions_hash(candidate)

    def test_changed_choice_invalidate_is_readonly_and_stale_spec_stays_stale(self) -> None:
        brief, _, choices, acks, metadata = requests()
        first = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
        spec = {"decisionsHash": first["decisionsHash"], "stale": False}
        self.assertIsNone(invalidate_message(spec, first))
        choices["SP-1"] = "B"
        second = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
        before = deepcopy((spec, second))
        message = invalidate_message(spec, second)
        self.assertNotEqual(first["decisionsHash"], second["decisionsHash"])
        self.assertEqual(message, {"code": "AF_SPEC_STALE", "severity": "blocker", "stale": True,
                                   "invalidatedBy": "decisionChanged", "expected": first["decisionsHash"], "actual": second["decisionsHash"]})
        self.assertEqual((spec, second), before)
        self.assertEqual(invalidate_message({**spec, "stale": True}, first)["code"], "AF_SPEC_STALE")

    def test_invalidation_rejects_forged_decision_hash_and_invalid_spec(self) -> None:
        _, actual = build()
        for spec in (None, {}, {"decisionsHash": "bad"}):
            with self.assertRaises(InputError):
                invalidate_message(spec, actual)
        actual["decisionsHash"] = canonical_hash("forged")
        with self.assertRaises(InputError):
            invalidate_message({"decisionsHash": actual["decisionsHash"]}, actual)

    def test_input_map_order_is_irrelevant_and_returned_metadata_has_no_shared_state(self) -> None:
        brief, _, choices, acks, metadata = requests()
        before = deepcopy((brief, choices, acks, metadata))
        first = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
        second = build_decisions(brief, choices=dict(reversed(list(choices.items()))),
                                 acknowledgements=dict(reversed(list(acks.items()))), decision_metadata=metadata)
        self.assertEqual(first, second)
        first["decisions"][0]["rationale"] = "changed"
        self.assertEqual((brief, choices, acks, metadata), before)
        self.assertNotEqual(first, second)

    def test_source_artifacts_and_mtimes_survive_build_validate_invalidate_without_network(self) -> None:
        paths = [ROOT / scenario / name for scenario in ("tp-fin", "tp-sales")
                 for name in ("wl3_brief.json", "wl3_decisions.json")]
        state = lambda: {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}
        before = state()
        brief, _, choices, acks, metadata = requests()
        with patch.object(socket, "socket", side_effect=AssertionError("WL4 không được gọi mạng")):
            actual = build_decisions(brief, choices=choices, acknowledgements=acks, decision_metadata=metadata)
            validate_decisions(brief, actual)
            self.assertFalse(freeze_blocked(brief, actual)["blocked"])
            self.assertIsNone(invalidate_message({"decisionsHash": actual["decisionsHash"]}, actual))
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
