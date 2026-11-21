"""Bounded operation images and cursor CAS; never grants Excel write authority.

Images are opaque validated-capture artifacts from the owning preparation
service. This layer proves byte integrity, quota and history transitions, not
that an image is an Excel workbook or can restore its semantic contents.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
from threading import RLock
import time
from uuid import uuid4

from pbip_assistant.coordinator.runtime import CoordinatorBusy
from pbip_assistant.errors import InputError
from .model import OperationScope, Reservation, RestoreAttempt, require_hash, require_identifier


RECEIPT_RESERVE = 1024


def _failure(code, detail):
    return InputError(code, "preparationRecovery", detail)


def _digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class RestoreJournal:
    def __init__(self, workspace_manager, *, clock=time.time, max_points=10,
                 max_bytes=256 * 1024 * 1024, max_image_bytes=64 * 1024 * 1024, physical_budget=None):
        if any(type(value) is not int or value <= 0 for value in (max_points, max_bytes, max_image_bytes)):
            raise ValueError("Journal budgets must be positive integers")
        self._manager, self._clock = workspace_manager, clock
        self._max_points, self._max_bytes, self._max_image = max_points, max_bytes, max_image_bytes
        self._physical_budget = physical_budget
        self._budget_key = "journal_" + uuid4().hex
        self._lock = RLock()
        self._context = workspace_manager.workspace()
        self._workspace = self._context.__enter__()
        self._root = Path(self._workspace).resolve()
        self._lineages, self._pending, self._restores = {}, {}, {}
        self._order = 0
        self._closed = False

    def _lineage(self, lineage_id):
        require_identifier(lineage_id)
        if self._closed:
            raise _failure("DP_POINT_EXPIRED", "Recovery storage is closed")
        if lineage_id not in self._lineages:
            now = self._clock()
            self._lineages[lineage_id] = {"issued": now, "touched": now, "expired": False,
                "closing": False, "points": [], "position": 0, "cursor": 0, "evicted": 0,
                "pending": None, "restore": None, "status": "ready"}
        return self._lineages[lineage_id]

    def _available(self, lineage_id):
        self.expire(self._clock())
        state = self._lineage(lineage_id)
        if state["expired"] or state["closing"]:
            raise _failure("DP_POINT_EXPIRED", "The preparation recovery session has expired")
        if state["pending"] or state["restore"]:
            if state["status"] == "partial_unknown":
                raise _failure("DP_PARTIAL_UNKNOWN", "Reconcile the previous attempt before another change")
            raise CoordinatorBusy("excel")
        return state

    def _usage(self):
        return sum(point["bytes"] for s in self._lineages.values() for point in s["points"]) + sum(
            pending["reserved"] for pending in self._pending.values())

    def _remove_image(self, image):
        path = self._root / image["file"]
        if path.parent != self._root or self._root.resolve() != self._root:
            raise _failure("DP_BACKUP_FAILED", "Invalid managed image location")
        path.unlink(missing_ok=True)

    def _remove_point(self, point):
        for image in point["images"].values():
            self._remove_image(image)
        self._remove_image({"file": point["receiptFile"]})

    def _room(self, required):
        while (sum(len(s["points"]) for s in self._lineages.values()) + len(self._pending) >= self._max_points
               or self._usage() + required > self._max_bytes
               or self._physical_budget is not None and not self._physical_budget.can_replace(self._budget_key, self._usage() + required)):
            choices = [(s["points"][0]["order"], s) for s in self._lineages.values()
                       if s["points"] and not s["restore"]]
            if not choices:
                raise _failure("DP_BACKUP_LIMIT", "No complete unpinned recovery point can free the required budget")
            _, state = min(choices, key=lambda item: item[0])
            # At the beginning of an undone chain, removing its first redo
            # would strand every later redo. Drop that entire dependent tail.
            removed = state["points"][:] if state["position"] == 0 else [state["points"][0]]
            for point in removed:
                self._remove_point(point)
                state["points"].remove(point)
            state["position"] = max(0, state["position"] - len(removed))
            state["cursor"] += 1
            state["evicted"] += len(removed)
            self._sync_budget()

    def _sync_budget(self, extra=0):
        if self._physical_budget is not None:
            self._physical_budget.replace_usage(self._budget_key, self._usage() + extra)

    def reserve_restore_point(self, lineage_id, operation: OperationScope, required_bytes):
        with self._lock:
            state = self._available(lineage_id)
            if not isinstance(operation, OperationScope) or type(required_bytes) is not int or not RECEIPT_RESERVE < required_bytes <= self._max_bytes:
                raise _failure("DP_BACKUP_LIMIT", "The complete before/after images and receipt do not fit the recovery budget")
            if state["points"]:
                expected = (state["points"][state["position"] - 1]["operation"].after_fingerprint
                            if state["position"] else state["points"][0]["operation"].before_fingerprint)
                if expected != operation.before_fingerprint:
                    raise _failure("DP_RESTORE_CONFLICT", "Current data does not match the journal head")
            self._room(required_bytes)
            self._sync_budget(required_bytes)
            reservation_id = uuid4().hex
            self._pending[reservation_id] = {"lineage": lineage_id, "operation": operation,
                "reserved": required_bytes, "images": {}, "status": "reserved"}
            state["pending"], state["touched"] = reservation_id, self._clock()
            self._workspace.heartbeat()
            return Reservation(reservation_id, required_bytes)

    def _pending_attempt(self, reservation_id):
        require_identifier(reservation_id)
        pending = self._pending.get(reservation_id)
        if pending is None:
            raise _failure("DP_POINT_EXPIRED", "The recovery reservation is unavailable")
        if pending["status"] == "partial_unknown":
            raise _failure("DP_PARTIAL_UNKNOWN", "The previous write has unknown state")
        return pending, self._lineages[pending["lineage"]]

    def store_image(self, reservation_id, purpose, payload, expected_hash):
        with self._lock:
            self.expire(self._clock())
            pending, state = self._pending_attempt(reservation_id)
            require_hash(expected_hash)
            if purpose not in {"before", "after"} or purpose in pending["images"]:
                raise _failure("DP_BACKUP_FAILED", "Unsupported or duplicate recovery image")
            if purpose == "after" and pending["status"] != "writing":
                raise _failure("DP_BACKUP_FAILED", "An after-image requires an active write")
            if purpose == "before" and pending["status"] != "reserved":
                raise _failure("DP_BACKUP_FAILED", "Before-image cannot replace an active backup")
            if not isinstance(payload, bytes) or len(payload) > self._max_image or not payload:
                raise _failure("DP_BACKUP_LIMIT", "The compressed recovery image exceeds its limit")
            image_bytes = sum(image["size"] for image in pending["images"].values())
            if image_bytes + len(payload) + RECEIPT_RESERVE > pending["reserved"]:
                raise _failure("DP_BACKUP_LIMIT", "The image exceeds the reserved before/after budget")
            if _digest(payload) != expected_hash:
                raise _failure("DP_BACKUP_FAILED", "The recovery image hash does not match")
            name = uuid4().hex + ".image"
            path = self._root / name
            try:
                with path.open("xb") as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                image = {"file": name, "size": len(payload), "hash": expected_hash}
                self._read_image(image)
            except (OSError, InputError) as exc:
                path.unlink(missing_ok=True)
                raise _failure("DP_BACKUP_FAILED", "Could not create and verify the recovery image") from exc
            pending["images"][purpose] = image
            if purpose == "before":
                pending["status"] = "before_verified"
            if not state["closing"]:
                state["touched"] = self._clock()
            return name.removesuffix(".image")

    def mark_write_started(self, reservation_id, expected_fingerprint):
        with self._lock:
            self.expire(self._clock())
            pending, state = self._pending_attempt(reservation_id)
            if state["closing"] or pending["status"] != "before_verified":
                raise _failure("DP_BACKUP_FAILED", "A verified before-image is required before a write")
            if expected_fingerprint != pending["operation"].before_fingerprint:
                raise _failure("DP_SOURCE_STALE", "Source changed before write")
            self._read_image(pending["images"]["before"])
            pending["status"] = "writing"

    def abort_attempt(self, reservation_id):
        with self._lock:
            pending, state = self._pending_attempt(reservation_id)
            if pending["status"] == "writing":
                pending["status"] = state["status"] = "partial_unknown"
            else:
                for image in pending["images"].values():
                    self._remove_image(image)
                state["pending"], state["status"] = None, "ready"
                del self._pending[reservation_id]
                self._sync_budget()

    def complete_attempt(self, reservation_id, receipt):
        with self._lock:
            self.expire(self._clock())
            pending, state = self._pending_attempt(reservation_id)
            if pending["status"] != "writing":
                raise _failure("DP_BACKUP_FAILED", "No write is awaiting completion")
            if (not isinstance(receipt, dict) or receipt.get("phase") != "verified"
                    or receipt.get("observedFingerprint") != pending["operation"].after_fingerprint
                    or "after" not in pending["images"]):
                pending["status"] = state["status"] = "partial_unknown"
                if state["closing"]:
                    self._purge(state)
                return self.state(pending["lineage"])
            try:
                self._read_image(pending["images"]["after"])
            except InputError:
                pending["status"] = state["status"] = "partial_unknown"
                raise
            if state["closing"]:
                self._purge(state)
                return self.state(pending["lineage"])
            point_id = uuid4().hex
            receipt_bytes = json.dumps({"pointId": point_id, "kind": pending["operation"].kind,
                "before": pending["operation"].before_fingerprint, "after": pending["operation"].after_fingerprint},
                sort_keys=True, separators=(",", ":")).encode()
            if len(receipt_bytes) > RECEIPT_RESERVE:
                pending["status"] = state["status"] = "partial_unknown"
                raise _failure("DP_BACKUP_LIMIT", "Recovery receipt exceeds its reserved budget")
            name = point_id + ".json"
            try:
                with (self._root / name).open("xb") as output:
                    output.write(receipt_bytes)
                    output.flush()
                    os.fsync(output.fileno())
            except OSError as exc:
                pending["status"] = state["status"] = "partial_unknown"
                raise _failure("DP_BACKUP_FAILED", "Could not commit the recovery receipt") from exc
            for point in state["points"][state["position"]:]:
                self._remove_point(point)
            state["points"] = state["points"][:state["position"]]
            self._order += 1
            state["points"].append({"pointId": point_id, "order": self._order,
                "operation": pending["operation"], "images": pending["images"], "receiptFile": name,
                "bytes": len(receipt_bytes) + sum(image["size"] for image in pending["images"].values())})
            state["position"] += 1
            state["cursor"] += 1
            state["pending"], state["status"], state["touched"] = None, "ready", self._clock()
            del self._pending[reservation_id]
            self._sync_budget()
            return self.state(pending["lineage"])

    def checkout_restore(self, lineage_id, point_id, direction, expected_cursor, expected_fingerprint):
        with self._lock:
            state = self._available(lineage_id)
            if direction not in {"undo", "redo"} or type(expected_cursor) is not int or state["cursor"] != expected_cursor:
                raise _failure("DP_REVIEW_STALE", "The recovery cursor changed")
            index = state["position"] - 1 if direction == "undo" else state["position"]
            if not 0 <= index < len(state["points"]) or state["points"][index]["pointId"] != point_id:
                raise _failure("DP_POINT_EXPIRED", "The requested recovery point is not reachable")
            point = state["points"][index]
            operation = point["operation"]
            expected = operation.after_fingerprint if direction == "undo" else operation.before_fingerprint
            if expected_fingerprint != expected:
                raise _failure("DP_RESTORE_CONFLICT", "Workbook changed since the recovery point")
            attempt_id = uuid4().hex
            self._restores[attempt_id] = {"lineage": lineage_id, "point": point, "direction": direction, "status": "prepared"}
            state["restore"], state["touched"] = attempt_id, self._clock()
            return RestoreAttempt(attempt_id, point_id, direction)

    def _read_image(self, image):
        path = self._root / image["file"]
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
                    or getattr(info, "st_file_attributes", 0) & 0x400
                    or path.resolve().parent != self._root or info.st_size != image["size"]
                    or not 0 < info.st_size <= self._max_image):
                raise OSError("Invalid managed image")
            with path.open("rb") as source:
                data = source.read(self._max_image + 1)
            if len(data) != image["size"] or _digest(data) != image["hash"]:
                raise OSError("Recovery image corruption")
            return data
        except OSError as exc:
            raise _failure("DP_BACKUP_FAILED", "Recovery image integrity check failed") from exc

    def read_restore(self, attempt_id):
        with self._lock:
            self.expire(self._clock())
            attempt = self._restores.get(attempt_id)
            if not attempt or attempt["status"] not in {"prepared", "writing"}:
                raise _failure("DP_POINT_EXPIRED", "Restore attempt is unavailable")
            purpose = "before" if attempt["direction"] == "undo" else "after"
            return self._read_image(attempt["point"]["images"][purpose])

    def mark_restore_started(self, attempt_id, expected_fingerprint):
        with self._lock:
            self.expire(self._clock())
            attempt = self._restores.get(attempt_id)
            if not attempt or attempt["status"] != "prepared":
                raise _failure("DP_POINT_EXPIRED", "Restore attempt is unavailable")
            operation = attempt["point"]["operation"]
            expected = operation.after_fingerprint if attempt["direction"] == "undo" else operation.before_fingerprint
            if expected_fingerprint != expected:
                raise _failure("DP_RESTORE_CONFLICT", "Workbook changed before restoring")
            self.read_restore(attempt_id)
            attempt["status"] = "writing"

    def abort_restore(self, attempt_id):
        with self._lock:
            attempt = self._restores.get(attempt_id)
            if not attempt or attempt["status"] != "prepared":
                raise _failure("DP_PARTIAL_UNKNOWN", "A started restore cannot be classified as a pre-write failure")
            state = self._lineages[attempt["lineage"]]
            state["restore"], state["status"] = None, "ready"
            del self._restores[attempt_id]

    def finish_restore(self, attempt_id, receipt):
        with self._lock:
            attempt = self._restores.get(attempt_id)
            if not attempt or attempt["status"] != "writing":
                raise _failure("DP_POINT_EXPIRED", "Restore attempt is unavailable")
            state = self._lineages[attempt["lineage"]]
            operation = attempt["point"]["operation"]
            expected = operation.before_fingerprint if attempt["direction"] == "undo" else operation.after_fingerprint
            if not isinstance(receipt, dict) or receipt.get("phase") != "verified" or receipt.get("observedFingerprint") != expected:
                state["status"], attempt["status"] = "partial_unknown", "partial_unknown"
                if state["closing"]:
                    self._purge(state)
                return self.state(attempt["lineage"])
            self.read_restore(attempt_id)
            state["position"] += -1 if attempt["direction"] == "undo" else 1
            state["cursor"] += 1
            state["restore"], state["status"], state["touched"] = None, "ready", self._clock()
            del self._restores[attempt_id]
            if state["closing"]:
                self._purge(state)
            return self.state(attempt["lineage"])

    def state(self, lineage_id):
        with self._lock:
            self.expire(self._clock())
            state = self._lineage(lineage_id)
            return deepcopy({"cursor": state["cursor"], "status": state["status"], "expired": state["expired"] or state["closing"],
                "evictedCount": state["evicted"], "retainedBytes": self._usage(),
                "undoCount": state["position"], "redoCount": len(state["points"]) - state["position"],
                "points": [{"pointId": point["pointId"], "kind": point["operation"].kind} for point in state["points"]]})

    def read_current_image(self, lineage_id):
        """Read verified committed head evidence; this grants no restore authority."""
        with self._lock:
            self.expire(self._clock())
            state = self._lineage(lineage_id)
            if state["expired"] or state["closing"] or state["status"] != "ready" or not state["points"]:
                raise _failure("DP_POINT_EXPIRED", "No verified committed recovery head is available")
            if state["position"]:
                image = state["points"][state["position"] - 1]["images"]["after"]
            else:
                image = state["points"][0]["images"]["before"]
            return self._read_image(image)

    def _purge(self, state):
        for point in state["points"]:
            self._remove_point(point)
        if state["pending"]:
            pending = self._pending.pop(state["pending"], None)
            if pending:
                for image in pending["images"].values():
                    self._remove_image(image)
        if state["restore"]:
            self._restores.pop(state["restore"], None)
        state.update(points=[], position=0, pending=None, restore=None, expired=True, closing=False, status="expired")
        state["cursor"] += 1
        self._sync_budget()

    def expire(self, now):
        with self._lock:
            for state in self._lineages.values():
                if state["expired"]:
                    continue
                if now >= state["touched"] + 1800 or now >= state["issued"] + 28800:
                    pending = self._pending.get(state["pending"])
                    restore = self._restores.get(state["restore"])
                    if ((pending and pending["status"] == "writing")
                            or (restore and restore["status"] == "writing")):
                        state["closing"] = True
                    else:
                        self._purge(state)

    def close(self):
        with self._lock:
            if not self._closed:
                for state in self._lineages.values():
                    self._purge(state)
                self._closed = True
                self._context.__exit__(None, None, None)

    def retire_lineage(self, lineage_id):
        """Retire transport authority without giving an abandoned write an infinite pin."""
        with self._lock:
            state = self._lineages.get(lineage_id)
            if state is None or state["expired"]:
                return
            pending = self._pending.get(state["pending"])
            restore = self._restores.get(state["restore"])
            if pending and pending["status"] == "writing":
                pending["status"] = state["status"] = "partial_unknown"
                state["closing"] = True
            elif restore and restore["status"] == "writing":
                restore["status"] = state["status"] = "partial_unknown"
                state["closing"] = True
            else:
                self._purge(state)
