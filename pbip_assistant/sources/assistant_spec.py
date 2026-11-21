"""Ghép ExecutionSpec WL4 tất định; không thực thi hoặc ghi nguồn."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re

from pbip_assistant.errors import InputError
from .assistant_decisions import freeze_blocked, validate_decisions
from .assistant_execution import compile_steps, verify_graph
from .assistant_ingest import canonical_hash


_BASIS = ("id", "snapshotHash", "decisionsHash", "briefHash", "steps", "labels",
          "unverifiedAssumptions", "createdAt", "stale", "variantOf", "variantReason")
_FIELDS = {"schemaVersion", "fingerprint", "hashBasis", *_BASIS}
_LABELS = {"assumed", "unverified", "out_of_scope", "stale"}
_HASH = re.compile(r"sha256:[a-f0-9]{64}")
_ASSUMPTION = re.compile(r"asm_[a-f0-9]{12}")


def _invalid(message: str, code: str = "AF_SPEC_INVALID") -> InputError:
    return InputError(code, "execution.spec", message)


def _timestamp(value) -> None:
    if not isinstance(value, str) or not value:
        raise _invalid("Caller phải cung cấp created_at tường minh, dạng ISO datetime có timezone.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("created_at phải là ISO datetime có timezone.") from exc
    if parsed.tzinfo is None:
        raise _invalid("created_at phải là ISO datetime có timezone.")


def _strings(value, allowed=None, pattern=None) -> bool:
    return (isinstance(value, list) and all(isinstance(item, str) and item and
            (allowed is None or item in allowed) and (pattern is None or pattern.fullmatch(item))
            for item in value) and len(value) == len(set(value)))


def spec_fingerprint(spec: dict) -> str:
    """Tính lại hash trên basis đóng; hash không thay thế cổng freeze hoặc freshness."""
    if (not isinstance(spec, dict) or set(spec) != _FIELDS or spec.get("schemaVersion") != "1.0"
            or spec.get("hashBasis") != list(_BASIS)):
        raise _invalid("Spec sai shape, phiên bản hoặc hash basis.")
    if (not isinstance(spec["id"], str) or re.fullmatch(r"spec_[a-f0-9]{24}", spec["id"]) is None
            or type(spec["stale"]) is not bool or spec["variantOf"] is not None
            or spec["variantReason"] is not None):
        raise _invalid("Định danh, stale hoặc metadata variant của Spec không hợp lệ.")
    for field in ("snapshotHash", "decisionsHash", "briefHash"):
        if not isinstance(spec[field], str) or _HASH.fullmatch(spec[field]) is None:
            raise _invalid("Spec thiếu hash tham chiếu hợp lệ.")
    if (not _strings(spec["labels"], allowed=_LABELS)
            or not _strings(spec["unverifiedAssumptions"], pattern=_ASSUMPTION)
            or spec["unverifiedAssumptions"] and "unverified" not in spec["labels"]):
        raise _invalid("Nhãn hoặc tham chiếu assumption của Spec không hợp lệ.")
    _timestamp(spec["createdAt"])
    verify_graph(spec["steps"])
    try:
        return canonical_hash({field: spec[field] for field in _BASIS})
    except (TypeError, ValueError) as exc:
        raise _invalid("Spec không thể hash canonical.") from exc


def build_spec(brief, decisions, pack, *, created_at=None) -> dict:
    """Đóng bản Spec mới từ quyết định đủ metadata; thiếu metadata chỉ giữ được draft."""
    _timestamp(created_at)
    if freeze_blocked(brief, decisions)["blocked"]:
        raise _invalid("Quyết định còn draft hoặc chưa đủ; chưa thể chốt Spec.", "AF_MISSING_DATA")
    validate_decisions(brief, decisions)
    labels = brief.get("labels")
    assumptions = brief.get("assumptions")
    if not _strings(labels, allowed=_LABELS) or not isinstance(assumptions, list):
        raise _invalid("Brief thiếu nhãn hoặc assumption ledger hợp lệ.")
    if "stale" in labels:
        raise _invalid("Brief đã stale; cần dựng lại từ revision hiện tại.", "AF_SPEC_STALE")
    identifiers = [entry.get("id") if isinstance(entry, dict) else None for entry in assumptions]
    if not _strings(identifiers, pattern=_ASSUMPTION):
        raise _invalid("Assumption phải có định danh duy nhất trong ledger của Brief.")
    # Decisions chốt policy, không tự cấp bằng chứng xác minh cho assumption ledger.
    result_labels = sorted(set(labels) | ({"unverified"} if identifiers else set()))
    steps = compile_steps(brief, decisions, pack)
    verify_graph(steps)
    if any(step["status"] != "ok" or step["guard"] is not None for step in steps):
        raise _invalid("Step pending hoặc blocked không thể thành Spec chính thức.", "AF_MISSING_DATA")
    choices = {entry["subProblemId"]: entry["optionId"] for entry in decisions["decisions"]}
    seen = set()
    for step in steps:
        expected = {identifier: choices[identifier] for identifier in step["decisionRefs"] if identifier in choices}
        if len(expected) != len(step["decisionRefs"]) or step["params"].get("chosenOptions") != expected:
            raise _invalid("Step không bind đúng lựa chọn đã chốt.")
        seen.update(expected)
    if seen != set(choices):
        raise _invalid("Có quyết định thực thi chưa được ánh xạ tới step.")
    result = {"schemaVersion": "1.0", "id": "", "snapshotHash": brief["snapshotHash"],
              "decisionsHash": decisions["decisionsHash"], "briefHash": brief["briefHash"],
              "steps": steps, "labels": result_labels, "unverifiedAssumptions": identifiers,
              "fingerprint": "", "createdAt": created_at, "stale": False,
              "variantOf": None, "variantReason": None, "hashBasis": list(_BASIS)}
    content = {field: result[field] for field in _BASIS if field != "id"}
    result["id"] = "spec_" + canonical_hash(content).split(":", 1)[1][:24]
    result["fingerprint"] = spec_fingerprint(result)
    return deepcopy(result)
