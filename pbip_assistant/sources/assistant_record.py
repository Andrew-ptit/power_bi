"""Decision Record WL7 tất định, chỉ giữ artifact dẫn xuất và tham chiếu đã bind."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
import re

from pbip_assistant.errors import InputError
from .assistant_brief import brief_hash
from .assistant_decisions import decisions_hash, freeze_blocked, validate_decisions
from .assistant_execution import verify_graph
from .assistant_ingest import canonical_hash
from .assistant_preview import _snapshot_info, _supported_recipe, _validated_spec, _verified_source_fingerprint
from .assistant_profile import snapshot_hash
from .assistant_reconcile import _BASIS as _RECONCILE_BASIS, assert_approvable


_BASIS = ("id", "createdAt", "snapshot", "brief", "decisions", "assumptions", "steps",
          "reconciliations", "delta", "labels", "stale", "variantOf", "variantReason")
_FIELDS = {"schemaVersion", "hashBasis", "hash", *_BASIS}
_LABELS = {"unverified", "assumed", "out_of_scope", "stale"}
_HASH = re.compile(r"sha256:[a-f0-9]{64}")
_ID = re.compile(r"rec_[a-f0-9]{24}")
_ASSUMPTION = re.compile(r"asm_[a-f0-9]{12}")
_PROJECTION_DROP = {"hashBasis", "variantOf", "variantReason"}
_RAW_KEYS = {"rows", "cells", "samples", "sample", "raw", "rawcells", "raw_tables", "rawtables",
             "binary", "base64", "workbook", "workbook_bytes", "source_evidence"}
_DELTA_FIELDS = {"rowsIn", "rowsOut", "nullsBefore", "nullsAfter", "duplicatesBefore",
                 "duplicatesAfter", "changedColumns"}
_DECISION_FIELDS = {"subProblemId", "optionId", "decidedBy", "decidedAt", "rationale"}
_ASSUMPTION_FIELDS = {"id", "statement", "source", "risk", "confidence", "evidence"}
_EVIDENCE_FIELDS = {"kind", "value", "ref", "formulaId"}
_REASONS = {"sourceChanged", "decisionChanged"}
# Path-like token sau boundary, không nhầm slash toán học có khoảng trắng hoặc A/B.
# UNC có thể xuất hiện giữa prose; URL scheme:// không phải filesystem path.
_ABSOLUTE_PATH = re.compile(r"(?<![\w./\\)])/(?![\s/])|(?<![\w/:])//(?=\S)|\\\\(?=\S)")
MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_NODES = 50000


def _invalid(message, code="AF_RECORD_INVALID"):
    return InputError(code, "record", message)


def _timestamp(value):
    if not isinstance(value, str) or not value or len(value) > 64:
        raise _invalid("Caller phải cấp created_at ISO datetime có timezone tường minh.")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("created_at phải là ISO datetime có timezone.") from exc
    if stamp.tzinfo is None:
        raise _invalid("created_at phải là ISO datetime có timezone.")


def _hash(value):
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _identifier(snapshot_ref, brief_ref, decision_hash):
    return "rec_" + canonical_hash({"snapshotHash": snapshot_ref, "briefHash": brief_ref,
                                     "decisionsHash": decision_hash})[7:31]


def _safe(value):
    """Kiểm JSON nhỏ, nhãn và privacy; không in giá trị không hợp lệ vào lỗi."""
    nodes, size = 0, 0
    def visit(item, depth=0):
        nonlocal nodes, size
        nodes += 1
        if nodes > MAX_NODES or depth > 24:
            raise _invalid("Record vượt giới hạn cấu trúc.")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or key.casefold() in _RAW_KEYS:
                    raise _invalid("Record không nhận raw cell, binary hoặc material nguồn.")
                if key == "labels" and (not isinstance(child, list) or any(
                        not isinstance(label, str) or label not in _LABELS for label in child)):
                    raise _invalid("Nhãn kết quả không thuộc tập cho phép; không cấp verified.")
                if key in {"label", "status"} and isinstance(child, str) and child.strip().casefold() == "verified":
                    raise _invalid("Record không cấp nhãn hoặc status verified.")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, str):
            if (len(item) > 20000 or re.search(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]", item)
                    or item.startswith(("/", "\\\\")) or _ABSOLUTE_PATH.search(item)
                    or "file://" in item.casefold()
                    or ";base64," in item.casefold() or item.casefold().startswith("base64:")
                    or re.fullmatch(r"[A-Za-z0-9+/]{256,}={0,2}", item)
                    or any(ord(char) < 32 and char not in "\n\r\t" for char in item)):
                raise _invalid("Record không nhận đường dẫn tuyệt đối hoặc binary/base64.")
            try:
                size += len(item.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise _invalid("Record phải là JSON UTF-8 hợp lệ.") from exc
        elif item is None or type(item) in {bool, int}:
            if type(item) is int and not -(10 ** 100) <= item <= 10 ** 100:
                raise _invalid("Số metadata vượt giới hạn.")
        elif type(item) is float and math.isfinite(item):
            pass
        else:
            raise _invalid("Record chỉ nhận JSON metadata hữu hạn, không binary/raw.")
        if size > MAX_RECORD_BYTES:
            raise _invalid("Record vượt giới hạn byte.")
    visit(value)
    if len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")) > MAX_RECORD_BYTES:
        raise _invalid("Record vượt giới hạn byte JSON.")


def _delta_shape(delta):
    if not isinstance(delta, dict) or set(delta) != _DELTA_FIELDS:
        raise _invalid("Delta không đúng shape WL7.")
    for key in ("rowsIn", "rowsOut", "duplicatesBefore", "duplicatesAfter"):
        if type(delta[key]) is not int or not 0 <= delta[key] <= 100000:
            raise _invalid("Delta cần số đếm nguyên trong giới hạn.")
    before, after = delta["nullsBefore"], delta["nullsAfter"]
    if (not isinstance(before, dict) or not before or not isinstance(after, dict)
            or set(before) != set(after) or len(before) > 256):
        raise _invalid("Delta thiếu projection null trước/sau tương ứng.")
    for fields, maximum in ((before, delta["rowsIn"]), (after, delta["rowsOut"])):
        if any(not isinstance(key, str) or not key or type(value) is not int or
               not 0 <= value <= maximum for key, value in fields.items()):
            raise _invalid("Delta null profile sai kiểu hoặc số đếm.")
    changes = delta["changedColumns"]
    if (not isinstance(changes, list) or len(changes) > 64 or
            any(not isinstance(item, str) or "→" not in item or len(item) > 200 for item in changes)
            or len(changes) != len(set(changes))):
        raise _invalid("Lineage delta phải là danh sách biến đổi duy nhất.")


def _reconciliation(projected):
    if not isinstance(projected, dict) or _PROJECTION_DROP & set(projected):
        raise _invalid("Reconciliation trong record phải là projection đã công bố.")
    restored = {**projected, "hashBasis": list(_RECONCILE_BASIS), "variantOf": None, "variantReason": None}
    assert_approvable(restored)
    return restored


def _shape(record):
    if (not isinstance(record, dict) or set(record) != _FIELDS or record.get("schemaVersion") != "1.0"
            or record.get("hashBasis") != list(_BASIS) or not isinstance(record["id"], str)
            or _ID.fullmatch(record["id"]) is None or type(record["stale"]) is not bool):
        raise _invalid("Decision Record không đúng shape hoặc basis đóng.")
    _timestamp(record["createdAt"])
    for key, fields in (("snapshot", {"snapshotHash", "sourceFingerprint"}),
                        ("brief", {"briefHash", "prompt"})):
        if not isinstance(record[key], dict) or set(record[key]) != fields:
            raise _invalid("Record thiếu tham chiếu snapshot hoặc Brief.")
    if any(not _hash(record[key][field]) for key, field in (("snapshot", "snapshotHash"),
            ("snapshot", "sourceFingerprint"), ("brief", "briefHash"))):
        raise _invalid("Record có hash tham chiếu không hợp lệ.")
    if not isinstance(record["brief"]["prompt"], str) or not record["brief"]["prompt"].strip():
        raise _invalid("Record cần prompt runtime có nội dung.")
    labels = record["labels"]
    if (not isinstance(labels, list) or any(not isinstance(label, str) or label not in _LABELS for label in labels)
            or len(labels) != len(set(labels))):
        raise _invalid("Record không được cấp nhãn ngoài tập cho phép.")
    if record["variantOf"] is not None or (record["stale"] and (
            "stale" not in labels or not isinstance(record["variantReason"], str)
            or record["variantReason"] not in _REASONS)) or (not record["stale"] and (
            "stale" in labels or record["variantReason"] is not None)):
        raise _invalid("Nhãn stale và lý do không khớp trạng thái Record.")
    decisions = record["decisions"]
    if (not isinstance(decisions, list) or not 0 < len(decisions) <= 100 or
            any(not isinstance(entry, dict) or set(entry) != _DECISION_FIELDS for entry in decisions)):
        raise _invalid("Record cần mảng quyết định đã chốt đúng shape.")
    ids = []
    for entry in decisions:
        identifier = entry["subProblemId"]
        if (not isinstance(identifier, str) or re.fullmatch(r"SP-[1-9][0-9]*", identifier) is None
                or not isinstance(entry["optionId"], str) or entry["optionId"] not in {"A", "B"}
                or entry["decidedBy"] != "user"):
            raise _invalid("Quyết định record không đúng option hoặc caller metadata.")
        _timestamp(entry["decidedAt"])
        ids.append(identifier)
    if len(ids) != len(set(ids)):
        raise _invalid("Record có quyết định trùng.")
    assumptions = record["assumptions"]
    if not isinstance(assumptions, list) or len(assumptions) > 100:
        raise _invalid("Record cần Assumption Ledger trong giới hạn.")
    ids = []
    for entry in assumptions:
        if (not isinstance(entry, dict) or set(entry) != _ASSUMPTION_FIELDS or
                not isinstance(entry["id"], str) or _ASSUMPTION.fullmatch(entry["id"]) is None
                or not isinstance(entry["statement"], str) or not entry["statement"]
                or not isinstance(entry["source"], str) or entry["source"] not in {"data", "pack", "history", "user", "llm"}
                or not isinstance(entry["risk"], str) or entry["risk"] not in {"low", "medium", "high"}
                or type(entry["confidence"]) not in {float, int} or not 0 <= entry["confidence"] <= 1
                or not isinstance(entry["evidence"], list) or len(entry["evidence"]) > 100
                or any(not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_FIELDS
                       for evidence in entry["evidence"])):
            raise _invalid("Assumption Record không đúng metadata/reference shape.")
        ids.append(entry["id"])
    if len(ids) != len(set(ids)) or assumptions and "unverified" not in labels:
        raise _invalid("Assumption chưa có bằng chứng xác minh phải giữ unverified.")
    verify_graph(record["steps"])
    if any(step["status"] != "ok" or step["guard"] is not None for step in record["steps"]):
        raise _invalid("Record hoàn chỉnh không nhận step pending hoặc blocked.")
    reconciliations = record["reconciliations"]
    if not isinstance(reconciliations, list) or len(reconciliations) != 1:
        raise _invalid("Record cần đúng một artifact reconciliation.")
    reconciliation = _reconciliation(reconciliations[0])
    _delta_shape(record["delta"])
    if (record["delta"]["rowsIn"] != reconciliation["rowsIn"] or
            record["delta"]["rowsOut"] != reconciliation["rowsOut"] or
            record["delta"]["duplicatesBefore"] != reconciliation["rowsIn"] - reconciliation["rowsInDeduped"]
            or record["delta"]["duplicatesAfter"] != 0):
        raise _invalid("Delta không khớp số đếm đã reconciliation.")
    _safe(record)


def record_hash(record) -> str:
    """Recompute hash đầy đủ; hash không thay authentication hoặc freshness của caller."""
    _shape(record)
    return canonical_hash({key: record[key] for key in _BASIS})


def _checked(record):
    if not isinstance(record, dict) or record.get("hash") != record_hash(record):
        raise _invalid("Record đã thay đổi hoặc hash không khớp.")


def build_record(snapshot, brief, decisions, spec, reconciliation, delta, *, created_at=None,
                 source_evidence=None) -> dict:
    """Ghép bản audit mới, không mở nguồn hoặc cấp nhãn verified."""
    _timestamp(created_at)
    _validated_spec(spec)
    if not isinstance(brief, dict) or brief.get("briefHash") != brief_hash(brief):
        raise _invalid("Brief không khớp nội dung hoặc revision.", "AF_SPEC_STALE")
    validate_decisions(brief, decisions)
    if freeze_blocked(brief, decisions)["blocked"] or spec["decisionsHash"] != decisions["decisionsHash"]:
        raise _invalid("Quyết định chưa chốt hoặc không thuộc Spec.", "AF_SPEC_STALE")
    if any(spec[field] != brief[field] for field in ("snapshotHash", "briefHash")):
        raise _invalid("Spec không bind đúng Brief hiện tại.", "AF_SPEC_STALE")
    scenario = "tp-fin" if any(step["params"]["operation"] == "load" for step in spec["steps"]) else "tp-sales"
    _supported_recipe(spec, scenario)
    source, _ = _snapshot_info(snapshot, spec, scenario)
    source = _verified_source_fingerprint(snapshot, source_evidence, scenario, source)
    assert_approvable(reconciliation)
    if reconciliation["specFingerprint"] != spec["fingerprint"] or set(reconciliation["labels"]) != set(spec["labels"]):
        raise _invalid("Reconciliation không bind Spec hoặc nhãn hiện tại.", "AF_SPEC_STALE")
    from .assistant_delta import changed_columns
    _delta_shape(delta)
    if set(delta["changedColumns"]) != set(changed_columns(spec)):
        raise _invalid("Delta lineage không khớp các operation đã khai báo trong Spec.")
    projected = {key: deepcopy(value) for key, value in reconciliation.items() if key not in _PROJECTION_DROP}
    record = {"schemaVersion": "1.0", "id": _identifier(snapshot["snapshotHash"], brief["briefHash"], decisions["decisionsHash"]),
              "createdAt": created_at, "snapshot": {"snapshotHash": snapshot["snapshotHash"], "sourceFingerprint": source},
              "brief": {"briefHash": brief["briefHash"], "prompt": brief["prompt"]},
              "decisions": deepcopy(decisions["decisions"]), "assumptions": deepcopy(brief["assumptions"]),
              "steps": deepcopy(spec["steps"]), "reconciliations": [projected], "delta": deepcopy(delta),
              "labels": list(spec["labels"]), "stale": False, "variantOf": None, "variantReason": None,
              "hashBasis": list(_BASIS), "hash": ""}
    record["hash"] = record_hash(record)
    return record


def _stale(reason):
    return {"code": "AF_SPEC_STALE", "severity": "blocker", "reason": reason}


def detect_stale(record, *, current_snapshot=None, current_decisions=None, current_source_evidence=None):
    """So tham chiếu hiện tại; không đọc nguồn, không sửa Record hoặc khẳng định source live."""
    _checked(record)
    if record["stale"]:
        return _stale(record["variantReason"])
    if current_snapshot is not None:
        if not isinstance(current_snapshot, dict) or not _hash(current_snapshot.get("snapshotHash")):
            raise _invalid("Cần snapshot/reference hiện tại hợp lệ.")
        if current_snapshot["snapshotHash"] != record["snapshot"]["snapshotHash"]:
            return _stale("sourceChanged")
        explicit = current_snapshot.get("sourceFingerprint")
        if explicit is not None and (not _hash(explicit) or explicit != record["snapshot"]["sourceFingerprint"]):
            return _stale("sourceChanged")
        if "hashBasis" in current_snapshot:
            basis = current_snapshot["hashBasis"]
            if basis not in (["snapshot", "sources", "tables"],
                             ["snapshot", "sources", "tables", "variantOf", "variantReason"]):
                return _stale("sourceChanged")
            try:
                full = canonical_hash({key: current_snapshot[key] for key in basis})
                runtime = snapshot_hash(current_snapshot) if len(basis) == 3 else None
                if current_snapshot["snapshotHash"] not in {full, runtime}:
                    return _stale("sourceChanged")
                if current_source_evidence is not None:
                    scenario = "tp-fin" if any(step["params"]["operation"] == "load" for step in record["steps"]) else "tp-sales"
                    source = _verified_source_fingerprint(current_snapshot, current_source_evidence, scenario,
                        canonical_hash([entry["hash"] for entry in current_snapshot["sources"]]))
                    if source != record["snapshot"]["sourceFingerprint"]:
                        return _stale("sourceChanged")
            except (InputError, KeyError, TypeError, ValueError):
                return _stale("sourceChanged")
        elif current_source_evidence is not None:
            raise _invalid("Source evidence cần snapshot đầy đủ để kiểm chứng.")
    elif current_source_evidence is not None:
        raise _invalid("Source evidence cần current_snapshot tương ứng.")
    if current_decisions is not None:
        if not isinstance(current_decisions, dict) or not _hash(current_decisions.get("decisionsHash")):
            raise _invalid("Cần decisions/reference hiện tại hợp lệ.")
        if "hashBasis" in current_decisions:
            try:
                actual = decisions_hash(current_decisions)
            except (InputError, KeyError, TypeError, ValueError):
                return _stale("decisionChanged")
            if current_decisions["decisionsHash"] != actual:
                return _stale("decisionChanged")
        elif set(current_decisions) != {"decisionsHash"}:
            raise _invalid("Reference quyết định chỉ nhận decisionsHash.")
        current_id = _identifier(record["snapshot"]["snapshotHash"], record["brief"]["briefHash"], current_decisions["decisionsHash"])
        if current_id != record["id"]:
            return _stale("decisionChanged")
    return None


def mark_stale(record, reason):
    """Tạo bản copy stale và hash mới; bản gốc cùng artifact con giữ nguyên."""
    _checked(record)
    if not isinstance(reason, str) or reason not in _REASONS:
        raise _invalid("Lý do stale chỉ nhận sourceChanged hoặc decisionChanged.")
    result = deepcopy(record)
    result["stale"] = True
    result["labels"] = sorted(set(result["labels"]) | {"stale"})
    result["variantReason"] = reason
    result["hash"] = record_hash(result)
    return result
