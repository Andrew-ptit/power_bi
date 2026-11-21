"""One-use native preparation writes with transient semantic validation only."""
from copy import deepcopy
import re
from uuid import uuid4

from pbip_assistant.errors import InputError
from .packages import image_fingerprint


def _fail(code, detail):
    return InputError(code, "preparation", detail)


class PreparationDirectMutation:
    def _require_backup_mode(self):
        if not self._backup_enabled:
            raise _fail("DP_UNSUPPORTED_PRESERVATION", "Preparation backup and recovery are disabled")

    def _require_direct_mode(self):
        if self._backup_enabled:
            raise _fail("DP_UNSUPPORTED_PRESERVATION", "Attach a fresh no-backup preparation session")

    @staticmethod
    def _direct_fingerprint(image):
        if (not isinstance(image, dict) or set(image) - {"version", "sheets", "fingerprint"}
                or any("preservation" in s for s in image.get("sheets", []) if isinstance(s, dict))):
            raise _fail("INVALID_REQUEST", "Only transient semantic worksheet fields are accepted")
        return image_fingerprint(image)

    @staticmethod
    def _validate_direct_copies(before, copies):
        for copy in copies:
            sheet = next(s for s in before["sheets"] if s["sheetId"] == copy["sourceSheetId"])
            tokens = (sheet["name"], "'" + sheet["name"].replace("'", "''") + "'")
            for r, c in sheet["formulaCells"]:
                formula = sheet["formulas"][r][c]
                if (not isinstance(formula, str) or "[" in formula or "]" in formula or
                        any(re.search(re.escape(token) + r"\s*!", formula, re.IGNORECASE) for token in tokens)):
                    raise _fail("DP_UNSUPPORTED_PRESERVATION", "Personal copy contains a self-sheet or structured formula requiring native retargeting")

    def direct_begin(self, transport, preparation_id, grant_id, before_image):
        with self._lock:
            self._require_direct_mode()
            d = self._get(transport, preparation_id)
            self._require_native_write(d)
            if d.get("attempt"):
                raise _fail("DP_PARTIAL_UNKNOWN", "An existing write attempt cannot be replayed")
            before_hash = self._direct_fingerprint(before_image)
            if before_hash != d["claimFingerprint"] or self._native_identity(before_image) != d["nativeIdentityHash"]:
                raise _fail("DP_SOURCE_STALE", "Current semantic data or native sheet identities changed since attachment")
            g = d.get("grant")
            if (not g or g["grantId"] != grant_id or g["reviewHash"] != self._current_review(d, g["kind"])
                    or g["sourceRevision"] != d["sourceRevision"] or g["answerRevision"] != d["answerRevision"]):
                raise _fail("DP_REVIEW_STALE", "Approval is absent, consumed or stale")
            packages = self.packages(transport, preparation_id, g["reviewHash"])["packages"] if g["kind"] == "import" else []
            a = {"attemptId": uuid4().hex, "kind": g["kind"], "operation": g["kind"],
                "beforeFingerprint": before_hash, "writePermit": uuid4().hex, "phase": "prepared",
                "reviewHash": g["reviewHash"], "sourceRevision": d["sourceRevision"], "answerRevision": d["answerRevision"],
                "packages": packages, "changes": deepcopy(list(d["preview"].changes)) if g["kind"] == "cleanup" else [],
                "target": deepcopy(g["target"]), "targetCopies": [],
                "beforeIds": {s["name"]: s["sheetId"] for s in before_image["sheets"]}}
            for change in a["changes"]:
                source = next(s for s in d["scan"].sources if s.source_id == change["sourceId"])
                change["beforeNumberFormat"] = source.number_formats[change["row"]][change["column"]]
                change["row"] += source.row_offset
                change["column"] += source.column_offset
            expected = self._expected_image(d, a, before_image)
            self._validate_direct_copies(before_image, a["targetCopies"])
            a["expectedFingerprint"] = expected["fingerprint"]
            # Full before/expected images never enter a session, cache or journal.
            d.update(attempt=a, grant=None, status="write_pending")
            return deepcopy({"beforeSheetIds": list(a["beforeIds"].values()), **{k: a[k] for k in (
                "attemptId", "kind", "operation", "beforeFingerprint", "expectedFingerprint",
                "writePermit", "packages", "changes", "targetCopies")}})

    def direct_write_ready(self, transport, preparation_id, attempt_id, write_permit, current_fingerprint):
        with self._lock:
            self._require_direct_mode()
            d, a = self._attempt(transport, preparation_id, attempt_id)
            self._require_native_write(d)
            if a["phase"] != "prepared" or a["writePermit"] != write_permit:
                raise _fail("DP_REVIEW_STALE", "Write permit is invalid or already consumed")
            if current_fingerprint != a["beforeFingerprint"] or d["claimFingerprint"] != current_fingerprint:
                raise _fail("DP_SOURCE_STALE", "Workbook changed immediately before native write")
            if (a["reviewHash"] != self._current_review(d, a["kind"]) or a["sourceRevision"] != d["sourceRevision"]
                    or a["answerRevision"] != d["answerRevision"]):
                raise _fail("DP_REVIEW_STALE", "Review changed before native write")
            result = {"attemptId": attempt_id, "writePermit": write_permit, "currentFingerprint": current_fingerprint, "operation": a["operation"]}
            a["phase"] = "writing"
            # From this point only identifiers/hashes/identity metadata remain.
            for key in ("writePermit", "packages", "changes", "target", "targetCopies"):
                a.pop(key, None)
            d.update(status="writing", packageCache=None, preview=None, scan=None, sources={}, inventory=None, importReview=None)
            self._sync_metadata_budget()
            return result

    def direct_complete(self, transport, preparation_id, attempt_id, receipt, after_image=None):
        with self._lock:
            self._require_direct_mode()
            d, a = self._attempt(transport, preparation_id, attempt_id)
            if receipt.get("phase") == "prewrite_failed" and a["phase"] == "prepared":
                d.update(attempt=None, status="needs_review")
                self._sync_metadata_budget()
                return self._finished_state(d)
            if a["phase"] != "writing" and not (a["phase"] == "prepared" and receipt.get("phase") == "partial_unknown"):
                raise _fail("DP_REVIEW_STALE", "No native write is awaiting read-back")
            verified = False
            created = []
            if receipt.get("phase") == "verified" and receipt.get("imageId") is None and after_image is not None:
                try:
                    observed = self._direct_fingerprint(after_image)
                    after_ids = {s["name"]: s["sheetId"] for s in after_image["sheets"]}
                    created = [sid for name, sid in after_ids.items() if name not in a["beforeIds"]]
                    actual = receipt.get("actualSheetIds", [])
                    verified = (observed == receipt.get("observedFingerprint") == a["expectedFingerprint"]
                        and len(actual) == len(set(actual)) and set(created) == set(actual)
                        and all(after_ids.get(name) == sid for name, sid in a["beforeIds"].items()))
                except InputError:
                    pass
            if verified:
                if a["kind"] == "import":
                    d["importedSheetIds"] = sorted(set(d.get("importedSheetIds", [])) | set(created))
                d.update(attempt=None, status="verified", claimFingerprint=a["expectedFingerprint"],
                    nativeIdentityHash=self._native_identity(after_image), nativeSheetIds=after_ids, needsReview=True)
            else:
                # Failed/lost completion cannot yield a new permit or a replay.
                a["phase"] = d["status"] = "partial_unknown"
                for key in ("writePermit", "packages", "changes", "target", "targetCopies"):
                    a.pop(key, None)
            # Reads arriving while the native host worked are never retained as
            # operation evidence, on either success or uncertain completion.
            d.update(sources={}, scan=None, preview=None, inventory=None, importReview=None, packageCache=None, grant=None)
            self._sync_metadata_budget()
            return self._finished_state(d)
