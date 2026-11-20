"""Bounded local scan/review state, separated from transport token lifetime.

Native mutation and journal reattachment remain unavailable until their live
gates pass. A metadata marker never becomes a write grant in this service.
"""
from copy import deepcopy
import json
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash
from .cleaning import bind_sources, build_cleanup_preview, scan_sources
from .inventory import browse_folder, inventory_folder, inventory_selection, review_import
from .model import AnswerRevision, SourceSnapshot, require_hash, require_identifier
from .mutation import PreparationMutation


def _fail(code, detail):
    return InputError(code, "preparation", detail)


def source_from_wire(value):
    keys = {"sourceId", "sheetId", "headers", "rows", "formulaCells", "columnKinds", "numberFormats", "dateSystem", "rowOffset", "columnOffset"}
    if not isinstance(value, dict) or set(value) != keys or not isinstance(value["formulaCells"], list):
        raise _fail("INVALID_REQUEST", "Source snapshot fields do not match the closed contract")
    try:
        return SourceSnapshot(value["sourceId"], value["sheetId"], tuple(value["headers"]), tuple(tuple(r) for r in value["rows"]),
            formula_cells=frozenset(tuple(item) for item in value["formulaCells"]),
            column_kinds=tuple(value["columnKinds"]), number_formats=tuple(tuple(r) for r in value["numberFormats"]),
            date_system=value["dateSystem"], row_offset=value["rowOffset"], column_offset=value["columnOffset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _fail("INVALID_REQUEST", "Source snapshot has invalid dimensions or types") from exc


class PreparationStore(PreparationMutation):
    def __init__(self, *, clock=time.time, start_janitor=False, workspace_manager=None, native_write_enabled=False, backup_enabled=True):
        self._clock, self._lock = clock, RLock()
        self._documents, self._markers, self._transports = {}, {}, {}
        self._mutation_init(workspace_manager)
        self._native_write_enabled = native_write_enabled is True
        self._backup_enabled = backup_enabled is True
        self._closed = False
        self._stop = Event()
        self._janitor = None
        if start_janitor:
            self._janitor = Thread(target=self._cleanup_loop, name="preparation-cleanup", daemon=True)
            self._janitor.start()

    def _cleanup_loop(self):
        while not self._stop.wait(30):
            self.expire()

    def _drop(self, document):
        if self._journal is not None:
            self._journal.retire_lineage(document["id"])
        self._documents.pop(document["id"], None)
        self._sync_upload_budget()
        self._markers.pop(document["marker"], None)
        if self._transports.get(document["transport"]) == document["id"]:
            self._transports.pop(document["transport"], None)
        document["sources"].clear()
        document.update(scan=None, preview=None, inventory=None, grant=None, attempt=None, packageCache=None)
        self._points = {pid: point for pid, point in self._points.items() if point.get("lineage") != document["id"]}
        self._sync_metadata_budget()

    def expire(self):
        with self._lock:
            now = self._clock()
            for document in list(self._documents.values()):
                if now >= document["touched"] + 1800 or now >= document["issued"] + 28800:
                    if (document.get("attempt") or {}).get("phase") == "writing":
                        document["closing"] = True
                    else:
                        self._drop(document)
            if self._journal is not None:
                self._journal.expire(now)

    def _get(self, transport, preparation_id, *, touch=True, allow_closing=False):
        self.expire()
        document = self._documents.get(preparation_id)
        if self._closed or document is None:
            raise _fail("DP_POINT_EXPIRED", "Preparation session is unavailable or expired")
        if document.get("closing") and not allow_closing:
            raise _fail("DP_POINT_EXPIRED", "Preparation expired; only the active native receipt may finish")
        if document["transport"] != transport or document["detached"]:
            raise _fail("DP_BINDING_REQUIRED", "Fresh authenticated workbook attachment is required")
        if touch and not document.get("closing"):
            document["touched"] = self._clock()
        return document

    def attach(self, transport_session_id, claim):
        with self._lock:
            self.expire()
            if self._closed:
                raise _fail("DP_POINT_EXPIRED", "Preparation service is closed")
            require_identifier(transport_session_id)
            keys = {"marker", "semanticFingerprint", "targetConfirmed", "expectedClaimVersion", "workbookName", "locationHash"}
            if (not isinstance(claim, dict) or not keys <= set(claim) or set(claim) - keys - {"nativeIdentityHash", "preservationFingerprint"}
                    or type(claim["targetConfirmed"]) is not bool):
                raise _fail("INVALID_REQUEST", "Invalid workbook attachment claim")
            require_hash(claim["semanticFingerprint"])
            preservation_fingerprint = claim.get("preservationFingerprint")
            if not self._backup_enabled and preservation_fingerprint is not None:
                raise _fail("INVALID_REQUEST", "No-backup attachments use semantic and native identity claims only")
            if preservation_fingerprint is not None:
                require_hash(preservation_fingerprint)
            native_identity = claim.get("nativeIdentityHash")
            if native_identity is not None:
                require_hash(native_identity)
            if claim["locationHash"] is not None:
                require_hash(claim["locationHash"])
            if type(claim["expectedClaimVersion"]) is not int or claim["expectedClaimVersion"] < 0:
                raise _fail("INVALID_REQUEST", "Invalid attachment version")
            if not isinstance(claim["workbookName"], str) or not 0 < len(claim["workbookName"]) <= 255:
                raise _fail("INVALID_REQUEST", "A bounded workbook display name is required")
            marker = claim["marker"]
            # Background reopen may verify a saved native target. First target
            # selection and ambiguous/unsaved targets require an actual user action.
            if not claim["targetConfirmed"] and (marker is None or claim["locationHash"] is None or native_identity is None):
                return {"status": "needs_target_confirmation", "writeEnabled": False}
            if marker is not None:
                require_identifier(marker)
                document = self._documents.get(self._markers.get(marker))
                if document is None:
                    raise _fail("DP_POINT_EXPIRED", "Retained preparation metadata is no longer available")
                if document["transport"] is not None and document["transport"] != transport_session_id:
                    raise _fail("DP_BINDING_REQUIRED", "Another active pane owns this attachment")
                if (claim["expectedClaimVersion"] != document["claimVersion"]
                        or claim["semanticFingerprint"] != document["claimFingerprint"]
                        or claim["locationHash"] != document["locationHash"]
                        or native_identity != document.get("nativeIdentityHash")
                        or preservation_fingerprint != document.get("preservationFingerprint")):
                    raise _fail("DP_RESTORE_CONFLICT", "Workbook claim changed; start a separate reviewed preparation")
                if document.get("attempt"):
                    raise _fail("DP_PARTIAL_UNKNOWN", "Finish the active native attempt before reattaching")
                self._markers.pop(document["marker"], None)
                document["marker"] = uuid4().hex
                document["claimVersion"] += 1
                document["reattached"] = True
                # Explicitly claiming an ambiguous target is not proof a copied
                # marker is unique. Its imported-write ownership never transfers.
                if claim["locationHash"] is None or native_identity is None:
                    document["importedSheetIds"] = []
                document["sources"].clear()
                document.update(scan=None, preview=None, grant=None, attempt=None, status="needs_source_read")
            else:
                old = self._documents.get(self._transports.get(transport_session_id))
                retire = (old is not None and not self._backup_enabled and claim["targetConfirmed"] and native_identity is not None and
                          (old["status"] == "partial_unknown" or (old.get("attempt") or {}).get("phase") in {"prepared", "writing"}))
                if len(self._documents) >= 8 and not retire:
                    raise _fail("REQUEST_LIMIT", "Close or let older preparation sessions expire before opening another")
                if old is not None:
                    if old.get("attempt") and not retire:
                        raise _fail("DP_PARTIAL_UNKNOWN", "Finish the active native attempt before changing target")
                    if retire:
                        # A fresh explicit native capture abandons uncertainty.
                        # Drop the old binding so delayed ready/completion cannot
                        # authorize a write or overwrite the new current claim.
                        self._drop(old)
                    old["transport"] = None
                    old["detached"] = True
                    old["sources"].clear()
                    old.update(scan=None, preview=None, status="needs_source_read")
                now = self._clock()
                document = {"id": uuid4().hex, "marker": uuid4().hex, "claimVersion": 1,
                    "claimFingerprint": claim["semanticFingerprint"], "locationHash": claim["locationHash"], "nativeIdentityHash": native_identity, "preservationFingerprint": preservation_fingerprint,
                    "issued": now, "touched": now, "transport": transport_session_id, "detached": False,
                    "sources": {}, "sourceRevision": 0, "sourceHash": None, "retainedSourceHash": None,
                    "scan": None, "answers": {}, "answerRevision": 0, "preview": None, "inventory": None,
                    "needsReview": False, "status": "needs_source_read", "reattached": False}
                self._documents[document["id"]] = document
            document.update(transport=transport_session_id, detached=False)
            self._markers[document["marker"]] = document["id"]
            self._transports[transport_session_id] = document["id"]
            return self._public(document)

    def detach(self, transport, preparation_id, expected_claim_version):
        with self._lock:
            document = self._get(transport, preparation_id, touch=False)
            if expected_claim_version != document["claimVersion"]:
                raise _fail("DP_REVIEW_STALE", "Workbook attachment version changed")
            if document.get("attempt"):
                raise _fail("DP_PARTIAL_UNKNOWN", "Finish the active native attempt before detaching")
            document["detached"] = True
            # Teardown only retains bounded metadata; source cells and executable
            # previews must be read again after new authentication.
            document["sources"].clear()
            document.update(scan=None, preview=None, inventory=None, grant=None, packageCache=None, status="needs_source_read")
            self._sync_metadata_budget()
            return {"status": "detached", "preparationId": preparation_id}

    def transport_closed(self, transport, reason):
        with self._lock:
            preparation_id = self._transports.pop(transport, None)
            document = self._documents.get(preparation_id)
            if document is None:
                return
            if document["detached"] and reason == "closed":
                document["transport"] = None
            else:
                self._drop(document)
            self.expire()

    def put_source_snapshot(self, transport, preparation_id, value):
        with self._lock:
            document = self._get(transport, preparation_id)
            source = source_from_wire(value)
            candidate = {**document["sources"], source.source_id: source}
            if (len(candidate) > 200 or sum(len(s.rows) * len(s.headers) for s in candidate.values()) > 400000
                    or sum(len(json.dumps([s.headers, s.rows, s.number_formats, sorted(s.formula_cells)],
                                          ensure_ascii=False).encode()) for s in candidate.values()) > 8 * 1024 * 1024):
                raise _fail("REQUEST_LIMIT", "Selected source snapshots exceed the bounded local scan budget")
            old = document["sources"].get(source.source_id)
            if old is None or old.fingerprint != source.fingerprint:
                if document["scan"] is not None:
                    affected = {q["questionId"] for q in document["scan"].questions if q["sourceId"] == source.source_id}
                    document["answers"] = {k: v for k, v in document["answers"].items() if k not in affected}
                document["sourceRevision"] += 1
                document["answerRevision"] += 1
                document.update(scan=None, preview=None, needsReview=True)
            document["sources"] = candidate
            document["sourceHash"] = bind_sources(list(candidate.values())).semantic_fingerprint
            document["status"] = "needs_scan"
            return self._public(document)

    def put_source_set(self, transport, preparation_id, values, expected_source_revision):
        """Atomically replace selection; unaffected question answers retain their revision history."""
        with self._lock:
            document = self._get(transport, preparation_id)
            if document["sourceRevision"] != expected_source_revision:
                raise _fail("DP_SOURCE_STALE", "Source selection changed before replacement")
            if document.get("attempt"):
                raise _fail("DP_REVIEW_STALE", "Finish the active mutation before replacing source selection")
            if not isinstance(values, list) or len(values) > 200:
                raise _fail("REQUEST_LIMIT", "Select at most 200 source snapshots")
            sources = [source_from_wire(value) for value in values]
            candidate = {source.source_id: source for source in sources}
            if len(candidate) != len(sources):
                raise _fail("INVALID_REQUEST", "Duplicate source identifiers in replacement")
            if (sum(len(s.rows) * len(s.headers) for s in sources) > 400000
                    or sum(len(json.dumps([s.headers, s.rows, s.number_formats, sorted(s.formula_cells)], ensure_ascii=False).encode())
                           for s in sources) > 8 * 1024 * 1024):
                raise _fail("REQUEST_LIMIT", "Selected source snapshots exceed the bounded local scan budget")
            old = document["sources"]
            changed = {sid for sid in set(old) | set(candidate) if sid not in old or sid not in candidate or old[sid].fingerprint != candidate[sid].fingerprint}
            if changed:
                if document["scan"] is not None:
                    affected = {q["questionId"] for q in document["scan"].questions if q["sourceId"] in changed}
                    document["answers"] = {k: v for k, v in document["answers"].items() if k not in affected}
                document["sourceRevision"] += 1
                document["answerRevision"] += 1
                document.update(scan=None, preview=None, needsReview=True, grant=None)
            document["sources"] = candidate
            document["sourceHash"] = bind_sources(sources).semantic_fingerprint if sources else None
            document["status"] = "needs_scan" if sources else "needs_source_read"
            return self._public(document)

    def scan(self, transport, preparation_id, expected_source_revision, expected_fingerprint, source_ids=None):
        with self._lock:
            document = self._get(transport, preparation_id)
            if document["sourceRevision"] != expected_source_revision or document["sourceHash"] != expected_fingerprint:
                raise _fail("DP_SOURCE_STALE", "Source snapshots changed before scanning")
            ids = source_ids if source_ids is not None else list(document["sources"])
            if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or any(i not in document["sources"] for i in ids):
                raise _fail("INVALID_REQUEST", "Select reviewed source snapshots")
            sources = [document["sources"][i] for i in ids]
            binding = bind_sources(sources)
            if document["reattached"] and document["retainedSourceHash"] is not None and binding.semantic_fingerprint != document["retainedSourceHash"]:
                raise _fail("DP_RESTORE_CONFLICT", "Data changed after reopen; start a new reviewed preparation")
            document["scan"] = scan_sources(binding, sources)
            known = {q["questionId"] for q in document["scan"].questions}
            document["answers"] = {k: v for k, v in document["answers"].items() if k in known}
            document.update(sourceHash=binding.semantic_fingerprint, retainedSourceHash=binding.semantic_fingerprint,
                            preview=None, status="questions_pending", reattached=False)
            return self._public(document)

    def answer_question(self, transport, preparation_id, question_id, answer, expected_answer_revision):
        with self._lock:
            document = self._get(transport, preparation_id)
            if document["scan"] is None or document["answerRevision"] != expected_answer_revision:
                raise _fail("DP_REVIEW_STALE", "Question or answer revision changed")
            question = next((q for q in document["scan"].questions if q["questionId"] == question_id), None)
            if (question is None or not isinstance(answer, dict) or set(answer) != {"choice", "reason"}
                    or answer["choice"] not in question["choices"]
                    or answer["reason"] is not None and (not isinstance(answer["reason"], str) or len(answer["reason"]) > 4000)):
                raise _fail("INVALID_REQUEST", "Answer does not match the current question")
            if document["answers"].get(question_id) != answer:
                document["answers"][question_id] = deepcopy(answer)
                document["answerRevision"] += 1
                document.update(preview=None, needsReview=True)
            return self._public(document)

    def preview(self, transport, preparation_id, expected_fingerprint, expected_answer_revision):
        with self._lock:
            document = self._get(transport, preparation_id)
            if (document["scan"] is None or document["sourceHash"] != expected_fingerprint
                    or document["answerRevision"] != expected_answer_revision):
                raise _fail("DP_REVIEW_STALE", "Read current source/questions before previewing")
            document["preview"] = build_cleanup_preview(document["scan"], AnswerRevision(document["answerRevision"], document["answers"]))
            document.update(status="preview_ready", needsReview=False)
            return self._public(document)

    def browse(self, transport, preparation_id, root, relative_path, *, expected_claim_version):
        with self._lock:
            document = self._get(transport, preparation_id)
            if document["claimVersion"] != expected_claim_version:
                raise _fail("DP_REVIEW_STALE", "Workbook attachment changed")
            return browse_folder(root, relative_path)

    def inventory(self, transport, preparation_id, root, items, *, expected_claim_version=None):
        with self._lock:
            document = self._get(transport, preparation_id)
            if expected_claim_version is not None and document["claimVersion"] != expected_claim_version:
                raise _fail("DP_REVIEW_STALE", "Workbook attachment changed")
            document["inventory"] = (inventory_folder(root, items) if isinstance(items, str)
                                     else inventory_selection(root, items))
            document.update(importReview=None, grant=None, packageCache=None)
            self._sync_metadata_budget()
            return {**self._public(document), "inventory": document["inventory"].public()}

    def review_import(self, transport, preparation_id, inventory_hash, mappings, existing_names=()):
        with self._lock:
            document = self._get(transport, preparation_id)
            if document["inventory"] is None:
                raise _fail("DP_REVIEW_STALE", "Inventory the folder before reviewing its mapping")
            review = review_import(document["inventory"], inventory_hash, mappings, existing_names)
            # Each explicit review can allocate a fresh native XLSX namespace.
            review["reviewHash"] = canonical_hash({"mappingHash": review["reviewHash"], "reviewId": uuid4().hex})
            document["importReview"] = {**deepcopy(review), "mappingReviewHash": review["reviewHash"],
                                        "existingNames": list(existing_names)}
            document["grant"] = None
            document.pop("packageCache", None)
            self._sync_metadata_budget()
            return review

    def approve_preview(self, preparation_id, review_hash):
        raise _fail("DP_UNSUPPORTED_PRESERVATION", "Native preservation and recovery qualification have not passed; writes stay disabled")

    def state(self, transport, preparation_id):
        with self._lock:
            return self._public(self._get(transport, preparation_id, touch=False))

    def _public(self, document):
        bound = bool(document.get("nativeIdentityHash") and (not self._backup_enabled or
                     document.get("preservationFingerprint") and getattr(self, "_evidence", None)))
        enabled = self._native_write_enabled and bound and not document.get("closing") and not document.get("detached") and document["status"] != "partial_unknown"
        blocker = None if enabled else ("DP_UNSUPPORTED_PRESERVATION" if not self._native_write_enabled else "DP_PARTIAL_UNKNOWN" if document["status"] == "partial_unknown" else "DP_BINDING_REQUIRED")
        return deepcopy({"preparationId": document["id"], "marker": document["marker"], "claimVersion": document["claimVersion"],
            "status": document["status"], "claimFingerprint": document["claimFingerprint"], "preservationFingerprint": document.get("preservationFingerprint"), "sourceRevision": document["sourceRevision"], "sourceHash": document["sourceHash"],
            "answerRevision": document["answerRevision"], "answers": document["answers"], "needsReview": document["needsReview"],
            "questions": list(document["scan"].questions) if document["scan"] else [],
            "findings": list(document["scan"].findings) if document["scan"] else [],
            "sources": [{"sourceId": s.source_id, "sheetId": s.sheet_id, "fingerprint": s.fingerprint,
                         "rowCount": len(s.rows), "columnCount": len(s.headers)} for s in document["sources"].values()],
            "preview": document["preview"].public() if document["preview"] else None,
            "idleExpiresAt": document["touched"] + 1800, "absoluteExpiresAt": document["issued"] + 28800,
            "importedSheetIds": document.get("importedSheetIds", []),
            "journal": self._journal.state(document["id"]) if self._journal else None,
            "backupEnabled": self._backup_enabled,
            "writeEnabled": enabled, "nativeQualification": "user_pending",
            "writeBlocker": blocker})

    def close(self):
        self._stop.set()
        if self._janitor is not None:
            self._janitor.join(timeout=1)
        with self._lock:
            for document in list(self._documents.values()):
                self._drop(document)
            self._closed = True
            if self._journal is not None:
                self._journal.close()
