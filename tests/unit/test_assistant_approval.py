"""Hợp đồng approval WL6 synthetic; không chứng thực danh tính ngoài caller."""

from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
import gc
import hashlib
import json
from pathlib import Path
import socket
from threading import Barrier
import unittest
from unittest.mock import patch
import weakref

from pbip_assistant.errors import InputError
from pbip_assistant.sources import assistant_approval as module
from pbip_assistant.sources.assistant_approval import (
    approval_state, consume_approval, issue_approval, validate_approval,
)
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_preview import build_preview
from pbip_assistant.sources.assistant_spec import spec_fingerprint
from tests.support.paths import FIXTURES
from tests.unit.test_assistant_preview import marker, pipeline


STAMP = "2026-10-29T15:00:00+07:00"  # Metadata synthetic do test caller truyền.


class AssistantApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {scenario: pipeline(scenario) for scenario in ("tp-fin", "tp-sales")}
        cls.previews = {}
        for scenario, data in cls.models.items():
            sheet = "PnL_Preview" if scenario == "tp-fin" else "Sales_Preview"
            cls.previews[scenario] = build_preview(data[-1], data[1], data[0][1],
                                                  sheet=sheet, marker=marker(data[1], sheet))

    def issue(self, scenario="tp-fin"):
        return issue_approval(self.models[scenario][1], self.previews[scenario], approved_at=STAMP)

    def assert_stale(self, callback):
        with self.assertRaises(InputError) as caught:
            callback()
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
        self.assertIn("preview lại", str(caught.exception))

    def test_issue_shape_metadata_binding_and_initial_state_fin_and_sales(self):
        for scenario in self.models:
            approval = self.issue(scenario)
            self.assertEqual(set(approval), {"approvalId", "approvedBy", "approvedAt", "boundTo", "consumed", "singleUse"})
            self.assertRegex(approval["approvalId"], r"^apr_[a-f0-9]{12}$")
            self.assertEqual(approval["approvedAt"], STAMP)
            self.assertEqual(approval["approvedBy"], "user")
            self.assertEqual(approval["boundTo"], {"specFingerprint": self.models[scenario][1]["fingerprint"],
                                                  "previewHash": self.previews[scenario]["previewHash"]})
            self.assertEqual(approval_state(approval), {"consumed": False, "singleUse": True})

    def test_fresh_issues_are_equal_artifacts_with_independent_one_use_capabilities(self):
        first, second = self.issue(), self.issue()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertEqual(json.loads(json.dumps(first)), dict(first))
        consume_approval(first)
        self.assertEqual(approval_state(second), {"consumed": False, "singleUse": True})
        validate_approval(second, self.models["tp-fin"][1], self.previews["tp-fin"])
        self.assertTrue(consume_approval(second)["consumed"])

    def test_validate_does_not_consume_or_mutate_artifacts(self):
        spec, preview = self.models["tp-fin"][1], self.previews["tp-fin"]
        before = deepcopy((spec, preview))
        approval = self.issue()
        token_before = deepcopy(dict(approval))
        validate_approval(approval, spec, preview)
        validate_approval(approval, spec, preview)
        self.assertEqual(approval, token_before)
        self.assertEqual((spec, preview), before)

    def test_consume_marks_original_and_returns_plain_consumed_audit_record(self):
        approval = self.issue()
        record = consume_approval(approval)
        self.assertIs(type(record), dict)
        self.assertTrue(approval["consumed"])
        self.assertTrue(record["consumed"])
        self.assertEqual(approval_state(approval), {"consumed": True, "singleUse": True})
        self.assertEqual(approval_state(record), {"consumed": True, "singleUse": True})
        self.assert_stale(lambda: consume_approval(approval))
        self.assert_stale(lambda: consume_approval(record))
        self.assert_stale(lambda: validate_approval(approval, self.models["tp-fin"][1], self.previews["tp-fin"]))

    def test_copy_deepcopy_and_json_reconstruction_never_become_issued_capabilities(self):
        approval = self.issue()
        candidates = (copy(approval), deepcopy(approval), dict(approval), json.loads(json.dumps(approval)))
        for candidate in candidates:
            with self.subTest(kind=type(candidate).__name__):
                self.assertEqual(candidate, approval)
                self.assert_stale(lambda: validate_approval(candidate, self.models["tp-fin"][1], self.previews["tp-fin"]))
                self.assert_stale(lambda: consume_approval(candidate))
        validate_approval(approval, self.models["tp-fin"][1], self.previews["tp-fin"])

    def test_resetting_consumed_flag_cannot_replay_original_or_preconsume_copy(self):
        approval = self.issue()
        saved = deepcopy(approval)
        record = consume_approval(approval)
        for candidate in (approval, saved, record):
            candidate["consumed"] = False
            self.assert_stale(lambda: consume_approval(candidate))
            self.assert_stale(lambda: approval_state(candidate))

    def test_metadata_and_bound_hash_tampering_are_rejected_even_with_recomputed_id(self):
        mutations = (
            lambda a: a.update(approvedAt="2026-10-29T16:00:00+07:00"),
            lambda a: a.update(approvedBy="llm"),
            lambda a: a.update(singleUse=False),
            lambda a: a.update(hiddenPolicy="allow"),
            lambda a: a["boundTo"].update(previewHash=canonical_hash("different preview")),
        )
        for index, mutate in enumerate(mutations):
            approval = self.issue()
            mutate(approval)
            approval["approvalId"] = "apr_" + canonical_hash(approval["boundTo"]).split(":", 1)[1][:12]
            with self.subTest(mutation=index):
                self.assert_stale(lambda: consume_approval(approval))
                self.assert_stale(lambda: validate_approval(approval, self.models["tp-fin"][1], self.previews["tp-fin"]))

    def test_preview_change_with_valid_recomputed_hash_invalidates_old_binding(self):
        data, spec, _, _, result = self.models["tp-fin"]
        changed = deepcopy(result)
        changed["rows"][0][4] += 1
        current = build_preview(changed, spec, data[1], sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
        approval = self.issue()
        self.assertNotEqual(current["previewHash"], self.previews["tp-fin"]["previewHash"])
        self.assert_stale(lambda: validate_approval(approval, spec, current))
        self.assertFalse(approval["consumed"])

    def test_spec_revision_change_with_matching_new_preview_invalidates_old_binding(self):
        data, old_spec, _, _, result = self.models["tp-fin"]
        spec = deepcopy(old_spec)
        spec["steps"][0]["label"] = "Revision synthetic mới"
        spec["fingerprint"] = spec_fingerprint(spec)
        preview = build_preview(result, spec, data[1], sheet="PnL_Preview", marker=marker(spec, "PnL_Preview"))
        self.assert_stale(lambda: validate_approval(self.issue(), spec, preview))

    def test_stale_or_malformed_spec_and_preview_cannot_issue_approval(self):
        spec, preview = self.models["tp-fin"][1], self.previews["tp-fin"]
        stale = deepcopy(spec)
        stale["stale"] = True
        stale["fingerprint"] = spec_fingerprint(stale)
        bad_preview = deepcopy(preview)
        bad_preview["counts"]["formulaCount"] = 1
        bad_preview["previewHash"] = canonical_hash({key: bad_preview[key] for key in bad_preview["hashBasis"]})
        for candidate_spec, candidate_preview in ((stale, preview), (None, preview), (spec, None),
                                                   (spec, bad_preview), ({"fingerprint": spec["fingerprint"]}, preview)):
            with self.assertRaises(InputError) as caught:
                issue_approval(candidate_spec, candidate_preview, approved_at=STAMP)
            self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_missing_actor_or_explicit_timezone_timestamp_fails_closed(self):
        spec, preview = self.models["tp-fin"][1], self.previews["tp-fin"]
        for actor in (None, "llm", "admin", "", []):
            self.assert_stale(lambda: issue_approval(spec, preview, approved_by=actor, approved_at=STAMP))
        for timestamp in (None, "", 0, "invalid", "2026-10-29", "2026-10-29T15:00:00", "x" * 65):
            self.assert_stale(lambda: issue_approval(spec, preview, approved_at=timestamp))
        self.assert_stale(lambda: issue_approval(spec, preview))

    def test_malformed_approval_fields_fail_without_python_type_errors(self):
        source = dict(self.issue())
        candidates = (None, {}, {**source, "boundTo": []}, {**source, "boundTo": {"previewHash": []}},
                      {**source, "consumed": 0}, {**source, "singleUse": 1},
                      {**source, "approvalId": []}, {**source, "approvedAt": []})
        for candidate in candidates:
            with self.subTest(shape=type(candidate).__name__):
                self.assert_stale(lambda: consume_approval(candidate))
                self.assert_stale(lambda: approval_state(candidate))

    def test_fake_consumed_flag_on_live_capability_does_not_hide_unspent_state(self):
        approval = self.issue()
        approval["consumed"] = True
        self.assert_stale(lambda: approval_state(approval))
        self.assert_stale(lambda: consume_approval(approval))

    def test_concurrent_consume_has_exactly_one_successful_caller(self):
        approval = self.issue()
        barrier = Barrier(8)
        def consume(_):
            barrier.wait(timeout=5)
            try:
                return consume_approval(approval)
            except InputError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(consume, range(8)))
        records = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["consumed"])
        self.assertEqual(results.count("AF_SPEC_STALE"), 7)

    def test_returned_consumed_record_has_no_shared_mutable_state(self):
        approval = self.issue()
        record = consume_approval(approval)
        before = deepcopy(dict(approval))
        record["boundTo"]["previewHash"] = canonical_hash("tampered audit only")
        self.assertEqual(approval, before)
        self.assert_stale(lambda: consume_approval(record))

    def test_weak_registry_releases_abandoned_capability_without_persisting_it(self):
        approval = self.issue()
        key = id(approval)
        reference = weakref.ref(approval)
        self.assertIn(key, module._ISSUED)
        del approval
        gc.collect()
        self.assertIsNone(reference())
        self.assertNotIn(key, module._ISSUED)

    def test_live_approval_limit_fails_closed_without_evicting_replay_guards(self):
        existing = len(module._ISSUED)
        with patch.object(module, "MAX_ISSUED_APPROVALS", existing + 1):
            approval = self.issue()
            self.assert_stale(lambda: self.issue())
            self.assertFalse(approval_state(approval)["consumed"])
            consume_approval(approval)
            fresh = self.issue()
            self.assertFalse(approval_state(fresh)["consumed"])

    def test_engine_operations_do_not_open_files_or_connect_network_and_sources_stay_identical(self):
        paths = [path for scenario in self.models for path in (FIXTURES / "assistant" / scenario / "source").rglob("*.csv")]
        paths += [FIXTURES / "assistant" / scenario / "wl1_snapshot.json" for scenario in self.models]
        state = lambda: {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}
        before = state()
        with patch("builtins.open", side_effect=AssertionError("Approval không được mở file")):
            with patch.object(Path, "open", side_effect=AssertionError("Approval không được mở file")):
                with patch.object(socket.socket, "connect", side_effect=AssertionError("Approval không được gọi network")):
                    for scenario in self.models:
                        approval = self.issue(scenario)
                        validate_approval(approval, self.models[scenario][1], self.previews[scenario])
                        consume_approval(approval)
                        self.assertTrue(approval_state(approval)["consumed"])
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
