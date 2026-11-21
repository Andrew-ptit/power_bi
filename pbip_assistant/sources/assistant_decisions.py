"""Quyết định WL4 tất định, chỉ ghi nhận lựa chọn tường minh của caller."""

from __future__ import annotations

from datetime import datetime
import re

from pbip_assistant.errors import InputError
from .assistant_brief import brief_hash
from .assistant_ingest import canonical_hash


_BASIS = ("snapshotHash", "understandHash", "briefHash", "decisions",
          "acknowledgements", "freezeBlocked")
_HASH = re.compile(r"sha256:[a-f0-9]{64}")
_DECISION_FIELDS = {"subProblemId", "optionId", "decidedBy", "decidedAt", "rationale"}
_ACK_FIELDS = {"subProblemId", "acknowledged", "note"}
_TOP_FIELDS = {"schemaVersion", "hashBasis", "decisionsHash", "variantOf", "variantReason", *_BASIS}
_FIXTURE_BASIS = (*_BASIS, "variantOf", "variantReason")


def _invalid(detail: str, code: str = "AF_DECISIONS_INVALID") -> InputError:
    return InputError(code, "decisions", detail)


def _brief_problems(brief: dict) -> dict[str, dict]:
    if not isinstance(brief, dict):
        raise _invalid("Cần Brief hợp lệ trước khi chốt quyết định.")
    try:
        if brief.get("briefHash") != brief_hash(brief):
            raise _invalid("Brief đã thay đổi hoặc hash không hợp lệ.", "AF_SPEC_STALE")
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid("Không xác minh được nội dung Brief.") from exc
    for field in ("snapshotHash", "understandHash", "briefHash"):
        if not isinstance(brief.get(field), str) or _HASH.fullmatch(brief[field]) is None:
            raise _invalid("Brief thiếu tham chiếu hash hợp lệ.")
    problems = brief.get("subProblems")
    if not isinstance(problems, list) or not problems or len(problems) > 100:
        raise _invalid("Brief phải có danh sách sub-problem trong giới hạn hỗ trợ.")
    result = {}
    for problem in problems:
        if not isinstance(problem, dict):
            raise _invalid("Sub-problem phải là object.")
        identifier = problem.get("id")
        options = problem.get("options")
        if (not isinstance(identifier, str) or re.fullmatch(r"SP-[1-9][0-9]*", identifier) is None
                or identifier in result or type(problem.get("blocker")) is not bool
                or not isinstance(options, list) or not options
                or problem.get("status") not in {"verified", "inferred", "assumed", "unknown", "missing_data", "conflict"}):
            raise _invalid("Sub-problem thiếu định danh, option hoặc blocker hợp lệ.")
        option_ids = [option.get("id") if isinstance(option, dict) else None for option in options]
        if (any(not isinstance(option, str) or not option for option in option_ids)
                or len(option_ids) != len(set(option_ids))):
            raise _invalid("Option của sub-problem phải có định danh duy nhất.")
        result[identifier] = problem
    return result


def _shape(decisions: dict) -> tuple[list[dict], list[dict]]:
    if (not isinstance(decisions, dict) or set(decisions) != _TOP_FIELDS
            or decisions.get("schemaVersion") != "1.0"
            or decisions.get("hashBasis") not in (list(_BASIS), list(_FIXTURE_BASIS))
            or type(decisions.get("freezeBlocked")) is not bool
            or decisions.get("variantOf") is not None or decisions.get("variantReason") is not None):
        raise _invalid("Document quyết định không đúng shape hoặc hash basis.")
    for field in ("snapshotHash", "understandHash", "briefHash"):
        if not isinstance(decisions[field], str) or _HASH.fullmatch(decisions[field]) is None:
            raise _invalid("Document quyết định thiếu hash tham chiếu hợp lệ.")
    chosen, acknowledged = decisions["decisions"], decisions["acknowledgements"]
    if not isinstance(chosen, list) or not isinstance(acknowledged, list):
        raise _invalid("Quyết định và acknowledgement phải là array.")
    if len(chosen) + len(acknowledged) > 100:
        raise _invalid("Document quyết định vượt giới hạn sub-problem.")
    for entries, fields in ((chosen, _DECISION_FIELDS), (acknowledged, _ACK_FIELDS)):
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != fields:
                raise _invalid("Entry quyết định thiếu field hoặc sai kiểu.")
            for key, value in entry.items():
                nullable = key in {"decidedBy", "decidedAt", "rationale", "note"}
                if value is None and nullable:
                    continue
                if not isinstance(value, str) or not value or len(value) > 2000:
                    raise _invalid("Entry quyết định thiếu field hoặc sai kiểu.")
    if any(entry["decidedBy"] not in {None, "user"} for entry in chosen):
        raise _invalid("Không được tự cấp danh tính người chốt ngoài metadata tường minh.")
    for entry in chosen:
        if entry["decidedAt"] is not None:
            _timestamp(entry["decidedAt"])
    if any(entry["acknowledged"] not in {"out_of_scope", "risk"} for entry in acknowledged):
        raise _invalid("Acknowledgement chỉ nhận out_of_scope hoặc risk.")
    return chosen, acknowledged


def decisions_hash(decisions: dict) -> str:
    """Hash sáu field nghiệp vụ; metadata variant bắt buộc null và không cấp quyền."""
    _shape(decisions)
    try:
        return canonical_hash({key: decisions[key] for key in decisions["hashBasis"]})
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid("Nội dung quyết định không thể hash canonical.") from exc


def _inspect(brief: dict, decisions: dict, *, complete: bool) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    problems = _brief_problems(brief)
    chosen, acknowledged = _shape(decisions)
    if decisions.get("decisionsHash") != decisions_hash(decisions):
        raise _invalid("Hash quyết định không khớp nội dung.")
    if any(decisions[field] != brief[field] for field in ("snapshotHash", "understandHash", "briefHash")):
        raise _invalid("Quyết định không thuộc đúng revision Brief.", "AF_SPEC_STALE")
    choice_map, ack_map = {}, {}
    for entry in chosen:
        identifier = entry["subProblemId"]
        if identifier not in problems or identifier in choice_map:
            raise _invalid("Có quyết định thừa hoặc trùng sub-problem.")
        if entry["optionId"] not in {option["id"] for option in problems[identifier]["options"]}:
            raise _invalid("Option được chọn không thuộc sub-problem.")
        choice_map[identifier] = entry
    for entry in acknowledged:
        identifier = entry["subProblemId"]
        if identifier not in problems or identifier in choice_map or identifier in ack_map:
            raise _invalid("Có acknowledgement thừa, trùng hoặc chồng quyết định.")
        ack_map[identifier] = entry
    if complete and set(choice_map) | set(ack_map) != set(problems):
        raise _invalid("Mỗi sub-problem phải có đúng một quyết định hoặc acknowledgement.")
    return problems, choice_map, ack_map


def _blockers(problems: dict, choices: dict, acknowledgements: dict) -> list[dict]:
    result = []
    for identifier, problem in problems.items():
        missing_data = problem.get("status") == "missing_data"
        out_of_scope = acknowledgements.get(identifier, {}).get("acknowledged") == "out_of_scope"
        unresolved = (missing_data and not out_of_scope) or (not missing_data and identifier not in choices)
        if unresolved:
            result.append({"code": "AF_MISSING_DATA", "severity": "warning",
                           "message": identifier + " chưa chốt lựa chọn; hệ thống không chọn hộ."})
    attested = bool(choices) and all(entry["decidedBy"] == "user" and entry["decidedAt"] is not None
                                    for entry in choices.values())
    if not attested:
        result.append({"code": "AF_MISSING_DATA", "severity": "warning",
                       "message": "Chưa chốt người quyết định và thời điểm tường minh cho bản quyết định."})
    return result


def freeze_blocked(brief, decisions) -> dict:
    """Cho phép xem trạng thái partial; acknowledgement không chọn thay option blocker."""
    problems, choices, acknowledgements = _inspect(brief, decisions, complete=False)
    blockers = _blockers(problems, choices, acknowledgements)
    if decisions["freezeBlocked"] != bool(blockers):
        raise _invalid("freezeBlocked không khớp quyết định thực tế.")
    return {"blocked": bool(blockers), "blockers": blockers}


def validate_decisions(brief, decisions) -> None:
    """Kiểm coverage 1:1, option, hash và đúng revision; không sửa Brief."""
    _inspect(brief, decisions, complete=True)
    freeze_blocked(brief, decisions)


def _timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid("Thời điểm chốt phải là ISO datetime có timezone.") from exc
    if parsed.tzinfo is None:
        raise _invalid("Thời điểm chốt phải là ISO datetime có timezone.")


def _metadata(metadata: dict | None, acknowledgements: dict) -> dict:
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict) or set(metadata) - {"decidedAt", "decidedBy", "rationale", "acknowledgementNotes"}:
        raise _invalid("Metadata quyết định có field không hỗ trợ.")
    result = {"decidedAt": metadata.get("decidedAt"), "decidedBy": metadata.get("decidedBy"),
              "rationale": metadata.get("rationale"), "acknowledgementNotes": metadata.get("acknowledgementNotes", {})}
    for field in ("decidedAt", "decidedBy", "rationale"):
        value = result[field]
        if value is not None and (not isinstance(value, str) or not value or len(value) > 2000):
            raise _invalid("Metadata quyết định sai kiểu hoặc vượt giới hạn.")
    if result["decidedBy"] not in {None, "user"}:
        raise _invalid("Danh tính người chốt phải được caller khai báo tường minh.")
    if result["decidedAt"] is not None:
        _timestamp(result["decidedAt"])
    notes = result["acknowledgementNotes"]
    if (not isinstance(notes, dict) or set(notes) - set(acknowledgements)
            or any(not isinstance(value, str) or not value or len(value) > 2000 for value in notes.values())):
        raise _invalid("Ack note phải thuộc acknowledgement được caller gửi.")
    return result


def build_decisions(brief, *, choices: dict[str, str], acknowledgements: dict[str, str], decision_metadata=None) -> dict:
    """Tạo bản ghi mới; thiếu lựa chọn vẫn được giữ là partial để hiện cổng chặn."""
    problems = _brief_problems(brief)
    if not isinstance(choices, dict) or not isinstance(acknowledgements, dict):
        raise _invalid("Choices và acknowledgements phải là object.")
    if (any(not isinstance(key, str) or not isinstance(value, str) for mapping in (choices, acknowledgements)
            for key, value in mapping.items()) or set(choices) & set(acknowledgements)
            or (set(choices) | set(acknowledgements)) - set(problems)):
        raise _invalid("Có định danh thừa, sai kiểu hoặc chồng choice/acknowledgement.")
    metadata = _metadata(decision_metadata, acknowledgements)
    selected, acks = [], []
    for identifier, problem in problems.items():
        if identifier in choices:
            option = choices[identifier]
            if option not in {item["id"] for item in problem["options"]}:
                raise _invalid("Option được chọn không thuộc sub-problem.")
            selected.append({"subProblemId": identifier, "optionId": option,
                             **{field: metadata[field] for field in ("decidedBy", "decidedAt", "rationale")}})
        elif identifier in acknowledgements:
            value = acknowledgements[identifier]
            if value not in {"out_of_scope", "risk"}:
                raise _invalid("Acknowledgement không được hỗ trợ.")
            acks.append({"subProblemId": identifier, "acknowledged": value,
                         "note": metadata["acknowledgementNotes"].get(identifier)})
    result = {"schemaVersion": "1.0", **{field: brief[field] for field in ("snapshotHash", "understandHash", "briefHash")},
              "decisions": selected, "acknowledgements": acks,
              "freezeBlocked": bool(_blockers(problems, {x["subProblemId"]: x for x in selected},
                                                     {x["subProblemId"]: x for x in acks})),
              "variantOf": None, "variantReason": None, "hashBasis": list(_BASIS), "decisionsHash": ""}
    result["decisionsHash"] = decisions_hash(result)
    _inspect(brief, result, complete=False)
    return result


def invalidate_message(spec, decisions) -> dict | None:
    """Trả thông báo bất biến; không tái hợp thức hóa spec đã stale."""
    if not isinstance(spec, dict):
        raise _invalid("Cần Spec hợp lệ để kiểm tra invalidation.")
    actual = decisions_hash(decisions)
    if decisions.get("decisionsHash") != actual:
        raise _invalid("Hash quyết định không khớp nội dung.")
    expected = spec.get("decisionsHash")
    if not isinstance(expected, str) or _HASH.fullmatch(expected) is None:
        raise _invalid("Spec thiếu decisionsHash hợp lệ.")
    if expected == actual and spec.get("stale") is not True:
        return None
    return {"code": "AF_SPEC_STALE", "severity": "blocker", "stale": True, "invalidatedBy": "decisionChanged",
            "expected": expected, "actual": actual}
