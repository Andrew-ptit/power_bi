"""Ghép Brief tất định từ câu chữ pack và số đo engine, không có quyền thực thi."""

from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext

from pbip_assistant.errors import InputError
from .assistant_findings import formulas, measure_set, number, scenario_fx_basis
from .assistant_ingest import canonical_hash
from .assistant_pack import select_pack, validate_pack
from .assistant_understand import understand_hash


_BASIS = ("snapshotHash", "understandHash", "prompt", "outputContract", "findings",
          "insightCases", "subProblems", "scenarios", "delta", "assumptions", "labels",
          "variantOf", "variantReason")
_DECISIONS_BASIS = ("briefHash", "decisions", "freezeBlocked", "blockers", "checklist")
_CONTEXT = Context(prec=300, rounding=ROUND_HALF_UP)
_RELATIONSHIP_CARDINALITIES = frozenset({"1:1", "1:N", "N:1", "N:N"})


def _invalid(detail: str) -> InputError:
    return InputError("AF_BRIEF_INVALID", "brief", detail)


def _identity(prefix: str, content: object) -> str:
    return prefix + canonical_hash(content)[7:19]


def _evidence(kind: str, *, value=None, ref=None, formula_id=None) -> dict:
    return {"kind": kind, "value": value, "ref": ref, "formulaId": formula_id}


def _period(raw_tables: list[dict], finance: bool) -> dict:
    field = "PostingDate" if finance else "OrderDate"
    candidates = [table for table in raw_tables if field in table["header"]]
    if len(candidates) != 1:
        raise _invalid("Không xác định duy nhất cột ngày của kỳ báo cáo.")
    table = candidates[0]
    index = table["header"].index(field)
    try:
        dates = [date.fromisoformat(row[index]) for row in table["rows"]]
        start, end = min(dates), max(dates)
    except (ValueError, TypeError) as exc:
        raise _invalid("Kỳ báo cáo cần ít nhất một ngày ISO hợp lệ.") from exc
    start = start.replace(day=1)
    end = end.replace(day=monthrange(end.year, end.month)[1])
    if (start.year, start.month) == (end.year, end.month):
        label = f"T{start.month}/{start.year}"
    elif start.year == end.year and start.month in (1, 4, 7, 10) and end.month == start.month + 2:
        label = f"Quý {(start.month - 1) // 3 + 1}/{start.year}"
    else:
        label = start.isoformat() + ".." + end.isoformat()
    return {"from": start.isoformat(), "to": end.isoformat(), "label": label}


def _output_contract(pack: dict, period: dict, override: dict | None, registry: dict) -> dict:
    result = deepcopy(pack["outputContract"])
    result["period"] = period
    result["filters"] = [{"field": "period", "operator": "between", "value": [period["from"], period["to"]]}]
    if override is None:
        return result
    if not isinstance(override, dict) or set(override) - set(result):
        raise _invalid("Override output contract có field không hỗ trợ.")
    candidate = {**deepcopy(result), **deepcopy(override)}
    grain = candidate["grain"]
    if (not isinstance(grain, list) or not grain or any(not isinstance(x, str) for x in grain)
            or len(grain) != len(set(grain)) or not set(grain) <= set(result["grain"])):
        raise _invalid("Override grain chỉ được chọn các chiều đã được pack hỗ trợ.")
    measures = candidate["measures"]
    if (not isinstance(measures, list) or not measures or any(not isinstance(x, dict) for x in measures)
            or any(x not in result["measures"] or x.get("formulaId") not in registry for x in measures)
            or len({x["name"] for x in measures}) != len(measures)):
        raise _invalid("Override measure chỉ được chọn số đã được engine hỗ trợ.")
    for field in ("currency", "period", "filters"):
        if candidate[field] != result[field]:
            raise _invalid("Chưa hỗ trợ đổi tiền tệ, kỳ hoặc filter mà chưa tính lại nguồn tương ứng.")
    return candidate


def brief_hash(brief: dict) -> str:
    """Tính lại hash của toàn bộ nội dung Brief được khai báo."""
    if not isinstance(brief, dict) or brief.get("hashBasis") != list(_BASIS):
        raise _invalid("Hash basis Brief không đúng hợp đồng.")
    if set(brief) != {"schemaVersion", "hashBasis", "briefHash", *_BASIS}:
        raise _invalid("Brief thiếu field hoặc có nội dung ngoài hash basis.")
    try:
        return canonical_hash({key: brief[key] for key in _BASIS})
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid("Nội dung Brief không thể hash canonical.") from exc


def _build(raw_tables, snapshot, understand, pack, prompt, policy_unresolved, output_contract_override) -> dict:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20_000:
        raise _invalid("Prompt phải là chuỗi có nội dung trong giới hạn hỗ trợ.")
    if not isinstance(snapshot, dict):
        raise _invalid("Cần snapshot WL1 hợp lệ trước khi dựng Brief.")
    if not isinstance(understand, dict) or understand.get("snapshotHash") != snapshot.get("snapshotHash"):
        raise _invalid("Mô hình hiểu không thuộc snapshot được cung cấp.")
    if understand.get("understandHash") != understand_hash(understand):
        raise _invalid("Hash mô hình hiểu không khớp nội dung.")
    relationships = understand.get("relationships")
    if (not isinstance(relationships, list)
            or any(not isinstance(link, dict)
                   or not isinstance(link.get("cardinality"), str)
                   or link["cardinality"] not in _RELATIONSHIP_CARDINALITIES
                   for link in relationships)):
        raise _invalid("Cardinality quan hệ phải thuộc catalog được hỗ trợ.")
    validate_pack(pack)
    if pack["id"] != select_pack(understand):
        raise _invalid("DomainPack không khớp mô hình hiểu.")
    if not isinstance(policy_unresolved, (set, frozenset)):
        raise _invalid("Danh sách policy chưa chốt phải là tập identifier.")
    policies = {policy["subProblemId"]: policy for policy in pack["policies"]}
    if not policy_unresolved <= set(policies):
        raise _invalid("Policy chưa chốt không thuộc pack.")
    measures = measure_set(raw_tables, snapshot)
    registry = {formula["formulaId"]: formula for formula in formulas(measures)}
    for metric in pack["metrics"]:
        formula = registry.get(metric["formulaId"])
        if formula is None or metric["unit"] != formula["unit"]:
            raise _invalid("Pack tham chiếu công thức hoặc đơn vị chưa được engine hỗ trợ.")

    def value(formula_id: str) -> dict | None:
        if formula_id not in registry:
            raise _invalid("Tham chiếu công thức không tồn tại trong registry engine.")
        measured = measures.get(formula_id.removeprefix("fm_"))
        if measured is None:
            return None
        unit = registry[formula_id]["unit"]
        return {"formulaId": formula_id, "value": number(measured, unit), "unit": unit}

    findings = []
    for metric in pack["metrics"]:
        measured = value(metric["formulaId"])
        if measured is None:
            continue
        findings.append({"id": _identity("fd_", [pack["id"], metric["formulaId"]]),
                         "statement": metric["statement"], "value": measured,
                         "evidence": [_evidence("engine", value=measured["value"], formula_id=metric["formulaId"])],
                         "status": "inferred", "provenance": "pack"})
    subproblems = []
    for policy in pack["policies"]:
        measured = value(policy["consequenceMetric"]) if policy["consequenceMetric"] is not None else None
        if policy["consequenceMetric"] is not None and measured is None:
            raise _invalid("Chưa có số đo cho hệ quả policy; không xuất số giả.")
        evidence = ([_evidence("engine", value=measured["value"], formula_id=measured["formulaId"])]
                    if measured else [_evidence("missing_source", ref=policy["subProblemId"])])
        status = policy["status"]
        if policy["evaluationRule"] is not None:
            if (policy["evaluationRule"] != "measured_dedupe_sign" or policy["provenance"] != "data"
                    or measures["rows_raw"] - measures["rows_deduped"] != measures["exact_duplicates"]
                    or measures["exact_duplicates"] < 0 or measures["key_collisions"] < 0):
                raise _invalid("Không đủ bằng chứng số học để xác nhận luật dữ liệu.")
            status = "verified"
            for name in ("exact_duplicates", "key_collisions"):
                measured_check = value("fm_" + name)
                evidence.append(_evidence(name, value=measured_check["value"], formula_id=measured_check["formulaId"]))
        subproblems.append({"id": policy["subProblemId"], "question": policy["question"],
                            "whyItMatters": policy["whyItMatters"], "status": status,
                            "provenance": policy["provenance"], "evidence": evidence,
                            "options": [{"id": option["id"], "label": option["label"],
                                         "recommended": option["recommended"],
                                         "consequence": {"statement": option["consequenceStatement"], "value": deepcopy(measured)}}
                                        for option in policy["options"]],
                            "proposedOptionId": policy["proposedOptionId"], "chosenOptionId": None,
                            "blocker": policy["blocker"], "consequenceOfChoice": None,
                            "labels": deepcopy(policy["labels"])})
    insights = [{"id": _identity("ic_", [pack["id"], insight["kind"], insight["formulaId"]]),
                 "kind": insight["kind"], "statement": insight["statement"],
                 "evidence": [_evidence("measure", ref=insight["formulaId"], formula_id=insight["formulaId"])],
                 "status": "inferred" if value(insight["formulaId"]) is not None else "unknown", "provenance": "pack"}
                for insight in pack["insights"]]
    scenarios = scenario_fx_basis(measures)
    if scenarios["scenarios"]:
        labels = {option["id"]: option["label"] for option in policies["SP-2"]["options"]}
        for scenario in scenarios["scenarios"]:
            scenario["label"] = labels[scenario["id"]]
    assumptions = []
    for index, assumption in enumerate(pack["assumptions"]):
        entry = {**deepcopy(assumption), "confidence": 0.5,
                 "evidence": [_evidence("authored_pack", ref=pack["id"] + "@" + pack["version"])]}
        if assumption["source"] == "data":
            entry["evidence"].append(_evidence("source", ref=snapshot["snapshotHash"]))
        assumptions.append({"id": _identity("asm_", [pack["id"], index, entry]), **entry})
    result = {"schemaVersion": "1.0", "snapshotHash": snapshot["snapshotHash"],
              "understandHash": understand["understandHash"], "prompt": prompt,
              "outputContract": _output_contract(pack, _period(raw_tables, pack["id"] == "fin-pl-v1"), output_contract_override, registry),
              "findings": findings, "insightCases": insights, "subProblems": subproblems,
              "scenarios": scenarios["scenarios"], "delta": scenarios["delta"],
              "assumptions": assumptions, "labels": ["assumed", "unverified"],
              "variantOf": None, "variantReason": None, "hashBasis": list(_BASIS), "briefHash": ""}
    result["briefHash"] = brief_hash(result)
    return result


def build_brief(raw_tables, snapshot, understand, pack, prompt, *, policy_unresolved=frozenset(),
                output_contract_override=None) -> dict:
    """Tạo Brief mới; override chỉ đổi chiều/measure đã hỗ trợ, không giả phép tính mới."""
    with localcontext(_CONTEXT):
        return _build(deepcopy(raw_tables), deepcopy(snapshot), deepcopy(understand), deepcopy(pack), prompt,
                      policy_unresolved, output_contract_override)


def build_unresolved_decisions(brief: dict) -> dict:
    """Chỉ tạo cổng chặn tối thiểu; không cấp approval, freeze hoặc step thực thi."""
    if not isinstance(brief, dict):
        raise _invalid("Cần Brief hợp lệ trước khi dựng cổng chưa chốt.")
    if brief.get("briefHash") != brief_hash(brief):
        raise _invalid("Brief đã đổi, cần dựng lại bản chốt chưa giải quyết.")
    questions = [problem["question"] for problem in brief["subProblems"]
                 if problem["chosenOptionId"] is None and problem["status"] != "missing_data"]
    if len(questions) < 3:
        raise _invalid("Cần ít nhất ba câu hỏi policy chưa chốt cho helper này.")
    result = {"briefHash": brief["briefHash"], "decisions": [], "freezeBlocked": True,
              "blockers": [{"code": "AF_MISSING_DATA", "severity": "warning",
                            "message": "Policy chưa được người dùng chốt; hệ thống không chọn hộ."}],
              "checklist": questions, "hashBasis": list(_DECISIONS_BASIS)}
    result["decisionsHash"] = canonical_hash({key: result[key] for key in _DECISIONS_BASIS})
    return result
