"""Approval WL6 một lần trong bộ nhớ; artifact không thay chứng thực người dùng."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from threading import RLock
import weakref

from pbip_assistant.errors import InputError
from .assistant_ingest import canonical_hash
from .assistant_reconcile import _bindings


_FIELDS = {"approvalId", "approvedBy", "approvedAt", "boundTo", "consumed", "singleUse"}
_HASH = re.compile(r"sha256:[a-f0-9]{64}")
_LOCK = RLock()
# Chỉ giữ weakref tới capability còn sống, không ghi token hoặc state xuống đĩa.
_ISSUED: dict[int, tuple[weakref.ReferenceType, dict]] = {}
MAX_ISSUED_APPROVALS = 4096


class _Approval(dict):
    __slots__ = ("__weakref__",)


def _stale() -> InputError:
    return InputError("AF_SPEC_STALE", "approval",
                      "Approval cũ mất hiệu lực; phải preview lại và duyệt lại trước khi ghi.")


def _timestamp(value) -> None:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise _stale()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _stale() from exc
    if parsed.tzinfo is None:
        raise _stale()


def _identifier(bound_to: dict) -> str:
    return "apr_" + canonical_hash(bound_to).split(":", 1)[1][:12]


def _shape(approval) -> None:
    if (not isinstance(approval, dict) or set(approval) != _FIELDS
            or approval.get("approvedBy") != "user"
            or type(approval.get("singleUse")) is not bool or approval["singleUse"] is not True
            or type(approval.get("consumed")) is not bool):
        raise _stale()
    bound_to = approval["boundTo"]
    if (not isinstance(bound_to, dict) or set(bound_to) != {"specFingerprint", "previewHash"}
            or any(not isinstance(value, str) or _HASH.fullmatch(value) is None
                   for value in bound_to.values())):
        raise _stale()
    if approval["approvalId"] != _identifier(bound_to):
        raise _stale()
    _timestamp(approval["approvedAt"])


def _binding(spec, preview) -> dict:
    try:
        sheet = preview["target"]["sheet"]
        scenario = {"PnL_Preview": "tp-fin", "Sales_Preview": "tp-sales"}.get(sheet)
        if scenario is None:
            raise _stale()
        _bindings(preview, spec, scenario)
        return {"specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"]}
    except (InputError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise _stale() from exc


def _live(approval) -> dict:
    """Caller phải giữ chính capability đã issue, không phải bản JSON/copy."""
    _shape(approval)
    entry = _ISSUED.get(id(approval))
    if (not isinstance(approval, _Approval) or entry is None or entry[0]() is not approval
            or approval["consumed"] is not False or approval != entry[1]):
        raise _stale()
    return entry[1]


def issue_approval(spec, preview, *, approved_by="user", approved_at=None) -> dict:
    """Cấp capability mới từ hành động caller; bắt buộc timestamp tường minh."""
    if approved_by != "user":
        raise _stale()
    _timestamp(approved_at)
    bound_to = _binding(spec, preview)
    approval = _Approval({"approvalId": _identifier(bound_to), "approvedBy": approved_by,
                          "approvedAt": approved_at, "boundTo": bound_to,
                          "consumed": False, "singleUse": True})
    key = id(approval)

    def released(reference):
        with _LOCK:
            entry = _ISSUED.get(key)
            if entry is not None and entry[0] is reference:
                del _ISSUED[key]

    with _LOCK:
        if len(_ISSUED) >= MAX_ISSUED_APPROVALS:
            raise _stale()
        _ISSUED[key] = (weakref.ref(approval, released), deepcopy(dict(approval)))
    return approval


def validate_approval(approval, spec, preview) -> None:
    """Kiểm token chưa dùng, toàn vẹn và binding; không consume hoặc sửa input."""
    bound_to = _binding(spec, preview)
    with _LOCK:
        original = _live(approval)
        if original["boundTo"] != bound_to:
            raise _stale()


def consume_approval(approval) -> dict:
    """Consume atomic trước ghi; bản audit trả về không còn capability để replay."""
    with _LOCK:
        original = _live(approval)
        result = deepcopy(original)
        result["consumed"] = True
        approval["consumed"] = True
        del _ISSUED[id(approval)]
        return result


def approval_state(approval) -> dict:
    """Đọc state; consumed record chỉ là audit, không cấp lại quyền apply."""
    with _LOCK:
        _shape(approval)
        if approval["consumed"] is False:
            _live(approval)
        elif id(approval) in _ISSUED:
            raise _stale()
        return {"consumed": approval["consumed"], "singleUse": True}


def _binding_v2(spec, preview):
    # Separate validation preserves the closed recipe-bound v1 entry points.
    from .assistant_freeze import validate_frozen_spec
    try:
        validate_frozen_spec(spec, preview)
        return {"specFingerprint": spec["fingerprint"], "previewHash": preview["previewHash"]}
    except (InputError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise _stale() from exc


def issue_approval_v2(spec, preview, *, approved_by="user", approved_at=None):
    """Issue a generic v2 capability in the same process-affine one-use registry."""
    if approved_by != "user":
        raise _stale()
    _timestamp(approved_at)
    bound_to = _binding_v2(spec, preview)
    approval = _Approval({"approvalId": _identifier(bound_to), "approvedBy": approved_by,
        "approvedAt": approved_at, "boundTo": bound_to, "consumed": False, "singleUse": True})
    key = id(approval)
    def released(reference):
        with _LOCK:
            entry = _ISSUED.get(key)
            if entry is not None and entry[0] is reference:
                del _ISSUED[key]
    with _LOCK:
        if len(_ISSUED) >= MAX_ISSUED_APPROVALS:
            raise _stale()
        _ISSUED[key] = (weakref.ref(approval, released), deepcopy(dict(approval)))
    return approval


def validate_approval_v2(approval, spec, preview):
    bound_to = _binding_v2(spec, preview)
    with _LOCK:
        if _live(approval)["boundTo"] != bound_to:
            raise _stale()
