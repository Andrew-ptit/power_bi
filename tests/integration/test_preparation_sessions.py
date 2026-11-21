"""Authenticated transport ownership and local question state, no Excel IO."""
import unittest

from pbip_assistant.errors import InputError


class PreparationSessionTests(unittest.TestCase):
    def test_atomic_source_set_preserves_unchanged_answers_removes_deleted_and_checks_cas(self):
        state = self.scan(self.upload(self.attach()))
        question = state["questions"][0]
        state = self.store.answer_question("transport_01", state["preparationId"], question["questionId"],
            {"choice": "keep_text", "reason": None}, state["answerRevision"])
        first = {"sourceId": "source_01", "sheetId": "{sheet_01}", "headers": ["Date"], "rows": [["03/04/2026"]],
            "formulaCells": [], "columnKinds": ["unknown"], "numberFormats": [["General"]], "dateSystem": "1900", "rowOffset": 1, "columnOffset": 0}
        second = {**first, "sourceId": "source_02", "sheetId": "{sheet_02}"}
        self.assertTrue(hasattr(self.store, "put_source_set"), "Atomic reviewed source replacement is missing")
        updated = self.store.put_source_set("transport_01", state["preparationId"], [first, second], state["sourceRevision"])
        self.assertIn(question["questionId"], updated["answers"])
        with self.assertRaises(InputError):
            self.store.put_source_set("transport_01", state["preparationId"], [], state["sourceRevision"])
        self.assertEqual(len(self.store.state("transport_01", state["preparationId"])["sources"]), 2)
        updated = self.scan(updated)
        deleted = self.store.put_source_set("transport_01", state["preparationId"], [second], updated["sourceRevision"])
        self.assertEqual([s["sourceId"] for s in deleted["sources"]], ["source_02"])
        self.assertNotIn(question["questionId"], deleted["answers"])

    def setUp(self):
        try:
            from pbip_assistant.sources.preparation.store import PreparationStore
        except ModuleNotFoundError:
            self.fail("Preparation workflow store is unavailable")
        self.now = 0.0
        self.store = PreparationStore(clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.claim = {"marker": None, "semanticFingerprint": "sha256:" + "1" * 64,
                      "targetConfirmed": True, "expectedClaimVersion": 0,
                      "workbookName": "Synthetic", "locationHash": None}

    def attach(self, transport="transport_01", claim=None):
        return self.store.attach(transport, claim or dict(self.claim))

    def upload(self, state, transport="transport_01", value="03/04/2026"):
        return self.store.put_source_snapshot(transport, state["preparationId"], {
            "sourceId": "source_01", "sheetId": "{sheet_01}", "headers": ["Date"], "rows": [[value]],
            "formulaCells": [], "columnKinds": ["unknown"], "numberFormats": [["General"]], "dateSystem": "1900", "rowOffset": 1, "columnOffset": 0})

    def test_closed_store_cannot_create_new_attachments(self):
        self.store.close()
        with self.assertRaises(InputError):
            self.attach()

    def test_scan_budget_includes_number_formats_and_headers(self):
        state = self.attach()
        with self.assertRaises(InputError) as caught:
            self.store.put_source_snapshot("transport_01", state["preparationId"], {
                "sourceId": "large", "sheetId": "sheet", "headers": ["Date"], "rows": [[1]] * 34000,
                "formulaCells": [], "columnKinds": ["unknown"], "numberFormats": [["x" * 256]] * 34000,
                "dateSystem": "1900", "rowOffset": 1, "columnOffset": 0})
        self.assertEqual(caught.exception.code, "REQUEST_LIMIT")
        self.assertEqual(self.store.state("transport_01", state["preparationId"])["sources"], [])

    def scan(self, state, transport="transport_01"):
        return self.store.scan(transport, state["preparationId"], state["sourceRevision"], state["sourceHash"])

    def test_page_close_retires_transport_but_retains_reviewable_metadata(self):
        state = self.upload(self.attach())
        state = self.scan(state)
        marker = state["marker"]
        self.store.detach("transport_01", state["preparationId"], state["claimVersion"])
        self.store.transport_closed("transport_01", "closed")
        with self.assertRaises(InputError):
            self.store.state("transport_01", state["preparationId"])
        claim = {**self.claim, "marker": marker, "expectedClaimVersion": state["claimVersion"]}
        resumed = self.attach("transport_02", claim)
        self.assertEqual(resumed["preparationId"], state["preparationId"])
        self.assertEqual(resumed["status"], "needs_source_read")
        self.assertEqual(resumed["questions"], [])
        resumed = self.upload(resumed, "transport_02")
        self.assertTrue(self.scan(resumed, "transport_02")["questions"])
        self.assertFalse(resumed["writeEnabled"])

    def test_explicit_close_invalidates_recovery_and_expiry_cannot_revive(self):
        for cause in ("explicit", "idle", "absolute"):
            state = self.attach("transport_" + cause)
            claim = {**self.claim, "marker": state["marker"], "expectedClaimVersion": state["claimVersion"]}
            if cause == "explicit":
                self.store.transport_closed("transport_" + cause, "closed")
            else:
                self.store.detach("transport_" + cause, state["preparationId"], state["claimVersion"])
                self.store.transport_closed("transport_" + cause, "closed")
                self.now += 1800 if cause == "idle" else 28800
                self.store.expire()
            with self.assertRaises(InputError):
                self.attach("transport_new_" + cause, claim)

    def test_clone_location_and_concurrent_attachment_do_not_inherit_ownership(self):
        state = self.attach()
        claim = {**self.claim, "marker": state["marker"], "expectedClaimVersion": state["claimVersion"]}
        with self.assertRaises(InputError):
            self.attach("transport_02", claim)
        self.store.detach("transport_01", state["preparationId"], state["claimVersion"])
        self.store.transport_closed("transport_01", "closed")
        with self.assertRaises(InputError):
            self.attach("transport_02", {**claim, "locationHash": "sha256:" + "2" * 64})
        new = self.attach("transport_02")
        self.assertNotEqual(new["preparationId"], state["preparationId"])
        self.assertFalse(new["writeEnabled"])

    def test_answer_cas_and_edit_invalidate_previous_preview(self):
        state = self.scan(self.upload(self.attach()))
        qid = state["questions"][0]["questionId"]
        state = self.store.answer_question("transport_01", state["preparationId"], qid,
                                           {"choice": "DMY", "reason": None}, state["answerRevision"])
        preview = self.store.preview("transport_01", state["preparationId"], state["sourceHash"], state["answerRevision"])
        self.assertEqual(preview["preview"]["examples"][0]["after"], 46115)
        with self.assertRaises(InputError):
            self.store.answer_question("transport_01", state["preparationId"], qid,
                                       {"choice": "MDY", "reason": None}, state["answerRevision"] - 1)
        changed = self.store.answer_question("transport_01", state["preparationId"], qid,
                                             {"choice": "MDY", "reason": None}, state["answerRevision"])
        self.assertIsNone(changed["preview"])
        self.assertTrue(changed["needsReview"])

    def test_changed_sources_after_reattach_require_a_new_review(self):
        state = self.scan(self.upload(self.attach()))
        claim = {**self.claim, "marker": state["marker"], "expectedClaimVersion": state["claimVersion"]}
        self.store.detach("transport_01", state["preparationId"], state["claimVersion"])
        self.store.transport_closed("transport_01", "closed")
        state = self.attach("transport_02", claim)
        state = self.upload(state, "transport_02", "04/05/2026")
        with self.assertRaises(InputError):
            self.scan(state, "transport_02")

    def test_no_write_capability_can_be_activated_by_request_or_old_state(self):
        state = self.attach()
        with self.assertRaises(InputError) as caught:
            self.store.approve_preview(state["preparationId"], "sha256:" + "a" * 64)
        self.assertEqual(caught.exception.code, "DP_UNSUPPORTED_PRESERVATION")
        with self.assertRaises(InputError):
            self.store.state("other_transport", state["preparationId"])

class PreparationBindingRecoveryTests(unittest.TestCase):
    """Native IDs distinguish a retained target from a copied metadata claim."""
    setUp = PreparationSessionTests.setUp
    attach = PreparationSessionTests.attach
    def test_native_identity_change_cannot_reclaim_even_after_explicit_confirmation(self):
        claim = {**self.claim, "nativeIdentityHash": "sha256:" + "2" * 64, "locationHash": "sha256:" + "3" * 64}
        state = self.attach(claim=claim)
        self.store.detach("transport_01", state["preparationId"], state["claimVersion"])
        self.store.transport_closed("transport_01", "closed")
        stale = {**claim, "marker": state["marker"], "expectedClaimVersion": state["claimVersion"], "nativeIdentityHash": "sha256:" + "4" * 64}
        with self.assertRaises(InputError) as caught:
            self.attach("transport_02", stale)
        self.assertEqual(caught.exception.code, "DP_RESTORE_CONFLICT")
        resumed = self.attach("transport_02", {**stale, "nativeIdentityHash": claim["nativeIdentityHash"], "targetConfirmed": False})
        self.assertEqual(resumed["preparationId"], state["preparationId"])

    def test_detach_and_background_reattach_do_not_extend_original_idle_expiry(self):
        claim = {**self.claim, "nativeIdentityHash": "sha256:" + "2" * 64, "locationHash": "sha256:" + "3" * 64}
        state = self.attach(claim=claim)
        self.now = 1700
        self.store.detach("transport_01", state["preparationId"], state["claimVersion"])
        self.store.transport_closed("transport_01", "closed")
        resumed = self.attach("transport_02", {**claim, "marker": state["marker"], "expectedClaimVersion": state["claimVersion"], "targetConfirmed": False})
        self.assertEqual(resumed["idleExpiresAt"], 1800)
        self.assertEqual(resumed["absoluteExpiresAt"], 28800)
        self.now = 1800
        with self.assertRaises(InputError):
            self.store.state("transport_02", state["preparationId"])

    def test_unsaved_reopen_requires_explicit_current_target_confirmation(self):
        claim = {**self.claim, "nativeIdentityHash": "sha256:" + "2" * 64}
        state = self.attach(claim=claim)
        self.store.detach("transport_01", state["preparationId"], state["claimVersion"])
        self.store.transport_closed("transport_01", "closed")
        claim = {**claim, "marker": state["marker"], "expectedClaimVersion": state["claimVersion"], "targetConfirmed": False}
        self.assertEqual(self.attach("transport_02", claim)["status"], "needs_target_confirmation")
        resumed = self.attach("transport_02", {**claim, "targetConfirmed": True})
        self.assertEqual(resumed["importedSheetIds"], [])

    def test_an_active_attempt_cannot_be_orphaned_by_new_target_attach(self):
        state = self.attach()
        self.store._documents[state["preparationId"]]["attempt"] = {"phase": "writing"}
        with self.assertRaises(InputError) as caught:
            self.attach()
        self.assertEqual(caught.exception.code, "DP_PARTIAL_UNKNOWN")

    def test_same_marker_reattach_cannot_clear_active_attempt(self):
        state = self.attach()
        self.store._documents[state["preparationId"]]["attempt"] = {"phase": "writing"}
        with self.assertRaises(InputError) as caught:
            self.attach(claim={**self.claim, "marker": state["marker"], "expectedClaimVersion": state["claimVersion"]})
        self.assertEqual(caught.exception.code, "DP_PARTIAL_UNKNOWN")

    def test_absolute_deadline_is_not_extended_by_authenticated_activity(self):
        state = self.attach()
        for current in range(1700, 28800, 1700):
            self.now = current
            state = self.store.put_source_set("transport_01", state["preparationId"], [], state["sourceRevision"])
            self.assertEqual(state["absoluteExpiresAt"], 28800)
        self.now = 28800
        with self.assertRaises(InputError):
            self.store.state("transport_01", state["preparationId"])


if __name__ == "__main__":
    unittest.main()
