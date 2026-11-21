"""Adversarial HTTP error classification around one-shot Assistant handoff.

These synthetic journeys assert coordinator authority, not an Office.js write.
"""

from pathlib import Path
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from tests.integration import test_assistant_v2_journey as journey


class AssistantApplyQualityTests(unittest.TestCase):
    setUp = journey.AssistantV2JourneyTests.setUp
    tearDown = journey.AssistantV2JourneyTests.tearDown
    request = journey.AssistantV2JourneyTests.request
    auth = journey.AssistantV2JourneyTests.auth
    post = journey.AssistantV2JourneyTests.post
    draft = journey.AssistantV2JourneyTests.draft
    compute = journey.AssistantV2JourneyTests.compute
    freeze = journey.AssistantV2JourneyTests.freeze
    approval_body = journey.AssistantV2JourneyTests.approval_body
    apply_body = journey.AssistantV2JourneyTests.apply_body

    def test_source_change_before_handoff_reports_unconsumed_and_allows_explicit_recovery(self):
        self.freeze()
        self.post("approvals", self.approval_body())
        source = Path(self.temp.name, "Transactions.csv")
        source.write_text("ID,Amount\nA,11\nB,-3\nC,5\n", encoding="utf-8")
        changed = source.read_bytes()

        error = self.post("apply", self.apply_body(), expected=409)["error"]
        self.assertEqual(error["code"], "AF_SPEC_STALE")
        self.assertIs(error.get("approvalConsumed"), False)
        self.assertFalse(self.post("state")["approvalConsumed"])
        self.assertEqual(self.post("state")["stage"], "approved")
        self.assertEqual(source.read_bytes(), changed)
        self.post("record", expected=409)

        # Recovery explicitly reloads/plans/previews/freezes and approves again.
        self.freeze()
        self.post("approvals", self.approval_body())
        before = source.read_bytes()
        handoff = self.post("apply", self.apply_body())
        self.assertEqual(handoff["stage"], "handoff")
        self.assertTrue(handoff["apply"]["approval"]["consumed"])
        self.assertEqual(source.read_bytes(), before)

    def test_consumed_replay_keeps_postconsume_truth_when_store_resets_before_error_response(self):
        self.freeze()
        self.post("approvals", self.approval_body())
        self.post("apply", self.apply_body())
        store = self.server.app.assistant
        original_apply = store.apply

        def reset_after_rejection(*args, **kwargs):
            try:
                return original_apply(*args, **kwargs)
            except InputError:
                # Deterministic interleaving: another request resets the store
                # after the guarded rejection, before HTTP maps its error.
                store.reset()
                raise

        with patch.object(store, "apply", side_effect=reset_after_rejection):
            error = self.post("apply", self.apply_body(), expected=500)["error"]
        self.assertEqual(error["code"], "AF_WRITE_PARTIAL")
        self.assertIs(error.get("approvalConsumed"), True)
        self.assertIsNone(error["written"])
        self.assertFalse(error["retryable"])
        self.assertEqual(self.post("state")["stage"], "new")

    def test_invalid_package_is_proven_preconsume_and_keeps_source_and_approval(self):
        self.freeze()
        self.post("approvals", self.approval_body())
        source = Path(self.temp.name, "Transactions.csv")
        before = source.read_bytes()
        body = {**self.apply_body(), "workbookBase64": "not-base64"}
        error = self.post("apply", body, expected=500)["error"]
        self.assertEqual(error["code"], "AF_WRITE_PARTIAL")
        self.assertIs(error.get("approvalConsumed"), False)
        self.assertIs(error["written"], False)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.post("state")["stage"], "approved")
        self.assertFalse(self.post("state")["approvalConsumed"])

    def test_unknown_partial_failure_does_not_claim_preconsume_from_current_store(self):
        self.freeze()
        self.post("approvals", self.approval_body())
        failure = InputError("AF_WRITE_PARTIAL", "apply", "Unknown synthetic adapter failure")
        with patch.object(self.server.app.assistant, "apply", side_effect=failure):
            error = self.post("apply", self.apply_body(), expected=500)["error"]
        self.assertNotIn("approvalConsumed", error)
        self.assertIsNone(error["written"])
        self.assertFalse(error["retryable"])

    def test_unknown_stale_failure_does_not_invent_an_authority_flag(self):
        self.freeze()
        self.post("approvals", self.approval_body())
        failure = InputError("AF_SPEC_STALE", "apply", "Unknown synthetic adapter failure")
        with patch.object(self.server.app.assistant, "apply", side_effect=failure):
            error = self.post("apply", self.apply_body(), expected=409)["error"]
        self.assertNotIn("approvalConsumed", error)

    def test_bad_receipt_retains_consumed_truth_and_blocks_record_and_repeat_handoff(self):
        self.freeze()
        self.post("approvals", self.approval_body())
        source = Path(self.temp.name, "Transactions.csv")
        before = source.read_bytes()
        handoff = self.post("apply", self.apply_body())
        wrong = {**handoff["receiptBinding"], "verified": True, "rowCount": 999}
        error = self.post("apply", {"receipt": wrong, "appliedAt": "2026-10-31T03:00:00.000Z"}, expected=500)["error"]
        self.assertEqual(error["code"], "AF_WRITE_PARTIAL")
        self.assertIs(error.get("approvalConsumed"), True)
        self.assertIsNone(error["written"])
        self.assertFalse(error["retryable"])
        self.assertEqual(self.post("state")["stage"], "partial")
        self.post("record", expected=409)
        replay = self.post("apply", self.apply_body(), expected=500)["error"]
        self.assertIs(replay.get("approvalConsumed"), True)
        self.assertEqual(source.read_bytes(), before)

    def test_receipt_after_store_reset_cannot_prove_that_original_handoff_was_unconsumed(self):
        self.freeze()
        self.post("approvals", self.approval_body())
        handoff = self.post("apply", self.apply_body())
        self.server.app.assistant.reset()
        receipt = {**handoff["receiptBinding"], "verified": True}
        error = self.post("apply", {"receipt": receipt, "appliedAt": "2026-10-31T03:00:00.000Z"}, expected=409)["error"]
        self.assertEqual(error["code"], "AF_SPEC_STALE")
        self.assertNotIn("approvalConsumed", error)


if __name__ == "__main__":
    unittest.main()
