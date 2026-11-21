"""Recovery journal behavior with real bounded files, not Excel mocks."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from pbip_assistant.coordinator.runtime import TempWorkspaceManager
from pbip_assistant.errors import InputError


def fingerprint(value):
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


class PreparationJournalTests(unittest.TestCase):
    def setUp(self):
        try:
            from pbip_assistant.sources.preparation.journal import RestoreJournal
            from pbip_assistant.sources.preparation.model import OperationScope
        except ModuleNotFoundError:
            self.fail("Recovery journal implementation unavailable")
        self.journal_class, self.scope_class = RestoreJournal, OperationScope
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manager = TempWorkspaceManager(root=self.root / "managed", system_temp_root=self.root, start_janitor=False)
        self.addCleanup(self.manager.close)
        self.now = 0.0
        self.journal = self.make_journal()

    def make_journal(self, **limits):
        journal = self.journal_class(self.manager, clock=lambda: self.now, **limits)
        self.addCleanup(journal.close)
        return journal

    def operation(self, before="before", after="after"):
        return self.scope_class("cleanup", ("sheet_01",), fingerprint(before), fingerprint(after))

    def test_current_head_read_follows_cursor_without_granting_restore(self):
        point, cursor = self.complete()
        self.assertEqual(self.journal.read_current_image("lineage_01"), b"after")
        prepared = self.journal.checkout_restore("lineage_01", point, "undo", cursor, fingerprint("after"))
        self.assertEqual(self.journal.read_current_image("lineage_01"), b"after")
        self.journal.mark_restore_started(prepared.attempt_id, fingerprint("after"))
        self.journal.finish_restore(prepared.attempt_id, {"phase": "verified", "observedFingerprint": fingerprint("before")})
        self.assertEqual(self.journal.read_current_image("lineage_01"), b"before")

    def test_shared_physical_budget_reserves_before_images_and_releases_abort(self):
        from pbip_assistant.sources.preparation.evidence import PhysicalBudget
        budget = PhysicalBudget(4096)
        journal = self.make_journal(physical_budget=budget)
        budget.replace_usage("native_evidence", 3000)
        with self.assertRaises(InputError) as caught:
            journal.reserve_restore_point("lineage_01", self.operation(), 2048)
        self.assertEqual(caught.exception.code, "DP_BACKUP_LIMIT")
        self.assertEqual(budget.usage, 3000)
        budget.replace_usage("native_evidence", 1000)
        reservation = journal.reserve_restore_point("lineage_01", self.operation(), 2048)
        self.assertEqual(budget.usage, 3048)
        journal.abort_attempt(reservation.reservation_id)
        self.assertEqual(budget.usage, 1000)

    def complete(self, journal=None, before="before", after="after", lineage="lineage_01"):
        journal = journal or self.journal
        reservation = journal.reserve_restore_point(lineage, self.operation(before, after), 2048)
        journal.store_image(reservation.reservation_id, "before", before.encode(), fingerprint(before))
        journal.mark_write_started(reservation.reservation_id, fingerprint(before))
        journal.store_image(reservation.reservation_id, "after", after.encode(), fingerprint(after))
        state = journal.complete_attempt(reservation.reservation_id,
            {"phase": "verified", "observedFingerprint": fingerprint(after)})
        return state["points"][-1]["pointId"], state["cursor"]

    def restore(self, point, cursor, direction, current, expected, journal=None):
        journal = journal or self.journal
        attempt = journal.checkout_restore("lineage_01", point, direction, cursor, fingerprint(current))
        self.assertEqual(journal.read_restore(attempt.attempt_id), expected.encode())
        journal.mark_restore_started(attempt.attempt_id, fingerprint(current))
        return journal.finish_restore(attempt.attempt_id,
            {"phase": "verified", "observedFingerprint": fingerprint(expected)})

    def test_no_write_before_verified_backup_and_wrong_hash_is_rejected(self):
        r = self.journal.reserve_restore_point("lineage_01", self.operation(), 2048)
        with self.assertRaises(InputError):
            self.journal.mark_write_started(r.reservation_id, fingerprint("before"))
        with self.assertRaises(InputError):
            self.journal.store_image(r.reservation_id, "before", b"tampered", fingerprint("before"))
        self.assertFalse(self.journal.state("lineage_01")["points"])

    def test_multi_undo_redo_and_new_edit_discards_redo(self):
        p1, _ = self.complete(before="a", after="b")
        p2, cursor = self.complete(before="b", after="c")
        state = self.restore(p2, cursor, "undo", "c", "b")
        state = self.restore(p1, state["cursor"], "undo", "b", "a")
        state = self.restore(p1, state["cursor"], "redo", "a", "b")
        _, cursor = self.complete(before="b", after="d")
        self.assertNotIn(p2, [p["pointId"] for p in self.journal.state("lineage_01")["points"]])
        with self.assertRaises(InputError):
            self.journal.checkout_restore("lineage_01", p2, "redo", cursor, fingerprint("d"))

    def test_manual_conflict_and_stale_cursor_do_not_move_history(self):
        point, cursor = self.complete()
        for version, current in ((cursor, "manual edit"), (cursor - 1, "after")):
            with self.assertRaises(InputError):
                self.journal.checkout_restore("lineage_01", point, "undo", version, fingerprint(current))
        self.assertEqual(self.journal.state("lineage_01")["cursor"], cursor)

    def test_fifo_keeps_remaining_points_restorable(self):
        journal = self.make_journal(max_points=2)
        old, _ = self.complete(journal, "a", "b")
        middle, _ = self.complete(journal, "b", "c")
        newest, cursor = self.complete(journal, "c", "d")
        state = journal.state("lineage_01")
        self.assertEqual([p["pointId"] for p in state["points"]], [middle, newest])
        self.assertEqual(state["evictedCount"], 1)
        state = self.restore(newest, cursor, "undo", "d", "c", journal)
        state = self.restore(middle, state["cursor"], "undo", "c", "b", journal)
        with self.assertRaises(InputError):
            journal.checkout_restore("lineage_01", old, "undo", state["cursor"], fingerprint("b"))

    def test_limits_include_pending_and_after_images(self):
        journal = self.make_journal(max_bytes=8192)
        r = journal.reserve_restore_point("lineage_01", self.operation(), 6144)
        with self.assertRaises(InputError):
            journal.reserve_restore_point("lineage_02", self.operation(), 6144)
        journal.store_image(r.reservation_id, "before", b"before", fingerprint("before"))
        journal.mark_write_started(r.reservation_id, fingerprint("before"))
        with self.assertRaises(InputError):
            journal.store_image(r.reservation_id, "after", b"x" * 6144, fingerprint("x" * 6144))
        self.assertFalse(journal.state("lineage_01")["points"])

    def test_pending_lineages_reserve_point_slots_before_either_write(self):
        journal = self.make_journal(max_points=1)
        first = journal.reserve_restore_point("lineage_01", self.operation(), 2048)
        with self.assertRaises(InputError) as caught:
            journal.reserve_restore_point("lineage_02", self.operation(), 2048)
        self.assertEqual(caught.exception.code, "DP_BACKUP_LIMIT")
        journal.store_image(first.reservation_id, "before", b"before", fingerprint("before"))
        journal.mark_write_started(first.reservation_id, fingerprint("before"))
        journal.store_image(first.reservation_id, "after", b"after", fingerprint("after"))
        journal.complete_attempt(first.reservation_id, {"phase": "verified", "observedFingerprint": fingerprint("after")})
        self.complete(journal, lineage="lineage_02")
        self.assertEqual(journal.state("lineage_01")["points"], [])
        self.assertEqual(len(journal.state("lineage_02")["points"]), 1)

    def test_oversize_and_backup_failure_zero_write(self):
        journal = self.make_journal(max_image_bytes=4)
        r = journal.reserve_restore_point("lineage_01", self.operation(), 2048)
        with self.assertRaises(InputError):
            journal.store_image(r.reservation_id, "before", b"before", fingerprint("before"))
        with self.assertRaises(InputError):
            journal.mark_write_started(r.reservation_id, fingerprint("before"))

    def test_unknown_preserves_cursor_and_blocks_replay(self):
        _, cursor = self.complete(before="a", after="b")
        r = self.journal.reserve_restore_point("lineage_01", self.operation("b", "c"), 2048)
        self.journal.store_image(r.reservation_id, "before", b"b", fingerprint("b"))
        self.journal.mark_write_started(r.reservation_id, fingerprint("b"))
        state = self.journal.complete_attempt(r.reservation_id, {"phase": "partial_unknown", "observedFingerprint": None})
        self.assertEqual(state["cursor"], cursor)
        self.assertEqual(state["status"], "partial_unknown")
        with self.assertRaises(InputError):
            self.journal.reserve_restore_point("lineage_01", self.operation("b", "c"), 2048)

    def test_expiry_pinned_job_and_old_lineage_cannot_revive(self):
        r = self.journal.reserve_restore_point("lineage_01", self.operation(), 2048)
        self.journal.store_image(r.reservation_id, "before", b"before", fingerprint("before"))
        self.journal.mark_write_started(r.reservation_id, fingerprint("before"))
        self.now = 1800
        self.journal.expire(self.now)
        self.assertTrue(list(self.root.rglob("*.image")))
        self.journal.store_image(r.reservation_id, "after", b"after", fingerprint("after"))
        state = self.journal.complete_attempt(r.reservation_id, {"phase": "verified", "observedFingerprint": fingerprint("after")})
        self.assertTrue(state["expired"])
        self.assertFalse(list(self.root.rglob("*.image")))
        with self.assertRaises(InputError):
            self.journal.reserve_restore_point("lineage_01", self.operation(), 2048)

    def test_absolute_expiry_despite_activity(self):
        self.complete(before="a", after="b")
        for now in range(1700, 28800, 1700):
            self.now = now
            self.complete(before="b", after="b")
        self.now = 28800
        self.journal.expire(self.now)
        self.assertTrue(self.journal.state("lineage_01")["expired"])
        self.assertFalse(list(self.root.rglob("*.image")))

    def test_corrupt_disk_image_never_returns_restore_bytes(self):
        point, cursor = self.complete()
        for path in self.root.rglob("*.image"):
            path.write_bytes(b"corrupt")
        attempt = self.journal.checkout_restore("lineage_01", point, "undo", cursor, fingerprint("after"))
        with self.assertRaises(InputError):
            self.journal.read_restore(attempt.attempt_id)
        self.assertEqual(self.journal.state("lineage_01")["cursor"], cursor)

    def test_expired_unstarted_restore_cannot_pin_images_or_read(self):
        point, cursor = self.complete()
        attempt = self.journal.checkout_restore("lineage_01", point, "undo", cursor, fingerprint("after"))
        self.now = 1800
        self.journal.expire(self.now)
        self.assertFalse(list(self.root.rglob("*.image")))
        with self.assertRaises(InputError):
            self.journal.read_restore(attempt.attempt_id)

    def test_prewrite_abort_releases_reserved_budget_and_before_image(self):
        r = self.journal.reserve_restore_point("lineage_01", self.operation(), 2048)
        self.journal.store_image(r.reservation_id, "before", b"before", fingerprint("before"))
        self.journal.abort_attempt(r.reservation_id)
        self.assertFalse(list(self.root.rglob("*.image")))
        self.complete()

    def test_corrupt_after_image_freezes_attempt_as_unknown(self):
        r = self.journal.reserve_restore_point("lineage_01", self.operation(), 2048)
        self.journal.store_image(r.reservation_id, "before", b"before", fingerprint("before"))
        self.journal.mark_write_started(r.reservation_id, fingerprint("before"))
        image = self.journal.store_image(r.reservation_id, "after", b"after", fingerprint("after"))
        path = next(p for p in self.root.rglob("*.image") if p.stem == image)
        path.write_bytes(b"corrupt")
        with self.assertRaises(InputError):
            self.journal.complete_attempt(r.reservation_id, {"phase": "verified", "observedFingerprint": fingerprint("after")})
        self.assertEqual(self.journal.state("lineage_01")["status"], "partial_unknown")

    def test_restoring_write_pins_until_verified_then_expires(self):
        point, cursor = self.complete()
        attempt = self.journal.checkout_restore("lineage_01", point, "undo", cursor, fingerprint("after"))
        self.journal.mark_restore_started(attempt.attempt_id, fingerprint("after"))
        self.now = 1800
        self.journal.expire(self.now)
        self.assertTrue(list(self.root.rglob("*.image")))
        state = self.journal.finish_restore(attempt.attempt_id, {"phase": "verified", "observedFingerprint": fingerprint("before")})
        self.assertTrue(state["expired"])
        self.assertFalse(list(self.root.rglob("*.image")))

    def test_native_sheet_identifier_is_preserved_in_operation_scope(self):
        native_id = "{00000000-0001-0000-0000-000000000000}"
        scope = self.scope_class("cleanup", (native_id,), fingerprint("before"), fingerprint("after"))
        self.assertEqual(scope.sheet_ids, (native_id,))
        with self.assertRaises(InputError):
            self.scope_class("cleanup", ("sheet\x00invalid",), fingerprint("before"), fingerprint("after"))

    def test_default_history_retains_ten_complete_points(self):
        for index in range(12):
            self.complete(before=str(index), after=str(index + 1))
        self.assertEqual(len(self.journal.state("lineage_01")["points"]), 10)
        self.assertEqual(self.journal.state("lineage_01")["evictedCount"], 2)


if __name__ == "__main__":
    unittest.main()
