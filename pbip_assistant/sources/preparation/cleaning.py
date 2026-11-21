"""Deterministic local findings and exact reviewed cleanup diffs, no Excel IO."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import re

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash
from .model import AnswerRevision, CleanupPreview, ScanResult, SourceSnapshot, WorkbookBinding


_DATE = re.compile(r"(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})")
_NUMBER = re.compile(r"[+-]?[\d.,]+")
_ERRORS = {"#DIV/0!", "#VALUE!", "#REF!", "#N/A", "#NAME?", "#NUM!", "#SPILL!", "#CALC!"}


def _invalid(detail):
    return InputError("DP_AMBIGUOUS_FORMAT", "preparationCleanup", detail)


def bind_sources(sources):
    return WorkbookBinding("local_scan", canonical_hash([s.fingerprint for s in sources]))


def _address(source, row, column):
    label, ordinal = "", source.column_offset + column + 1
    while ordinal:
        ordinal, remainder = divmod(ordinal - 1, 26)
        label = chr(65 + remainder) + label
    return label + str(source.row_offset + row + 1)


def scan_sources(binding: WorkbookBinding, sources: list[SourceSnapshot]) -> ScanResult:
    if not sources or len(sources) > 200 or len({s.source_id for s in sources}) != len(sources):
        raise InputError("INVALID_REQUEST", "sources", "Select unique reviewed sources")
    if sum(len(s.rows) * len(s.headers) for s in sources) > 400000:
        raise InputError("REQUEST_LIMIT", "sources", "Selected workbook scan exceeds 400000 cells")
    source_hash = canonical_hash([s.fingerprint for s in sources])
    if binding.semantic_fingerprint != source_hash:
        raise InputError("DP_SOURCE_STALE", "sources", "Workbook binding does not match selected sources")
    grouped, questions, examples_used = {}, [], 0
    def finding(source, column, kind, row, before):
        nonlocal examples_used
        key = source.source_id, column, kind
        address = (_address(source, row, column) if column is not None else
                   _address(source, row, 0) + ":" + _address(source, row, len(source.headers) - 1))
        item = grouped.setdefault(key, {"sourceId": source.source_id, "sheetId": source.sheet_id,
            "column": column, "columnLabel": source.headers[column][:256] if column is not None else None,
            "firstAddress": address, "kind": kind,
            "count": 0, "coverage": "full", "examples": []})
        item["count"] += 1
        if examples_used < 20:
            item["examples"].append({"row": row, "address": address, "value": str(before)[:256] if before is not None else None})
            examples_used += 1
    for source in sources:
        dates, numbers, leading_zero = set(), set(), set()
        seen = set()
        for row_index, row in enumerate(source.rows):
            row_hash = canonical_hash(row)
            if row_hash in seen:
                finding(source, None, "duplicate_row", row_index, None)
            seen.add(row_hash)
            for column, value in enumerate(row):
                if (row_index, column) in source.formula_cells:
                    if isinstance(value, str) and value in _ERRORS:
                        finding(source, column, "formula_error", row_index, value)
                    continue
                if value is None or value == "":
                    finding(source, column, "missing", row_index, value)
                    continue
                if not isinstance(value, str):
                    continue
                cleaned = value.strip(" ")
                if cleaned != value:
                    finding(source, column, "trim", row_index, value)
                if "\u00a0" in value or any(character in value for character in "\t\r\n"):
                    finding(source, column, "invisible_character", row_index, value)
                if source.column_kinds[column] == "text":
                    continue
                if _DATE.fullmatch(cleaned):
                    dates.add(column)
                elif _NUMBER.fullmatch(cleaned) and any(char.isdigit() for char in cleaned):
                    numbers.add(column)
                    if re.match(r"[+-]?0\d", cleaned):
                        leading_zero.add(column)
        for column in sorted(dates | numbers):
            kind = "date" if column in dates else "number"
            question_id = "format_" + canonical_hash([source.source_id, column])[7:31]
            questions.append({"questionId": question_id, "group": "formats", "sourceId": source.source_id,
                "column": column, "label": source.headers[column], "kind": kind,
                "choices": ["keep_text", "DMY", "MDY", "YMD"] if kind == "date" else ["keep_text", "decimal_dot", "decimal_comma"],
                "leadingZeroWarning": column in leading_zero or source.column_kinds[column] == "identifier"})
        if len(questions) > 200:
            raise InputError("REQUEST_LIMIT", "questions", "Select fewer columns to keep clarification bounded")
    return ScanResult(binding, tuple(sources), tuple(grouped.values()), tuple(questions), source_hash)


def _date_serial(value, order, system):
    layouts = {"DMY": ("%d", "%m", "%Y"), "MDY": ("%m", "%d", "%Y"), "YMD": ("%Y", "%m", "%d")}
    parsed = None
    for separator in ("/", "-", "."):
        try:
            parsed = datetime.strptime(value, separator.join(layouts[order])).date()
            break
        except ValueError:
            pass
    if parsed is None or parsed < date(1900 if system == "1900" else 1904, 1, 1):
        raise _invalid("Some dates are invalid for the selected format; fix them or keep the column as text")
    if system == "1904":
        return (parsed - date(1904, 1, 1)).days
    origin = date(1899, 12, 31) if parsed < date(1900, 3, 1) else date(1899, 12, 30)
    return (parsed - origin).days


def _number_value(value, choice):
    decimal, group = (".", ",") if choice == "decimal_dot" else (",", ".")
    raw = value.lstrip("+-")
    sign = value[:1] if value[:1] in {"+", "-"} else ""
    if raw.count(decimal) > 1:
        raise _invalid("Numeric decimal separators are inconsistent")
    parts = raw.split(decimal)
    whole = parts[0] or "0"
    if group in whole and not re.fullmatch(r"\d{1,3}(?:" + re.escape(group) + r"\d{3})+", whole):
        raise _invalid("Numeric group separators are inconsistent")
    whole = whole.replace(group, "")
    if not whole.isascii() or not whole.isdigit() or len(parts) == 2 and (not parts[1].isascii() or not parts[1].isdigit()):
        raise _invalid("Some numeric cells do not match the selected format")
    try:
        number = Decimal(sign + whole + ("." + parts[1] if len(parts) == 2 else ""))
        digits = ''.join(str(d) for d in number.as_tuple().digits).rstrip("0") or "0"
        if (len(digits) > 15 or not math.isfinite(float(number))
                or number != 0 and abs(number) < Decimal("2.2250738585072014e-308")):
            raise _invalid("Numeric conversion would exceed Excel precision; keep this column as text")
        return int(number) if number == number.to_integral_value() else float(number)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise _invalid("Numeric conversion is unsupported") from exc


def build_cleanup_preview(scan: ScanResult, answers: AnswerRevision) -> CleanupPreview:
    known = {q["questionId"]: q for q in scan.questions}
    if set(answers.values) - set(known):
        raise InputError("INVALID_REQUEST", "answers", "Answer does not belong to this scan")
    choices = {}
    for question_id, question in known.items():
        answer = answers.values.get(question_id)
        if (not isinstance(answer, dict) or set(answer) != {"choice", "reason"}
                or answer["choice"] not in question["choices"]
                or answer["reason"] is not None and (not isinstance(answer["reason"], str) or len(answer["reason"]) > 4000)):
            raise _invalid("Answer every required format question before calculating this cleanup")
        choices[question["sourceId"], question["column"]] = question["kind"], answer["choice"]
    changes = []
    for source in scan.sources:
        for row_index, row in enumerate(source.rows):
            for column, before in enumerate(row):
                if (row_index, column) in source.formula_cells or not isinstance(before, str):
                    continue
                after, number_format = before.strip(" "), None
                kind, choice = choices.get((source.source_id, column), (None, "keep_text"))
                if after and choice != "keep_text":
                    if kind == "date":
                        after, number_format = _date_serial(after, choice, source.date_system), "yyyy-mm-dd"
                    elif kind == "number":
                        after, number_format = _number_value(after, choice), "General"
                if before != after or type(before) is not type(after):
                    changes.append({"sourceId": source.source_id, "sheetId": source.sheet_id, "row": row_index,
                        "column": column, "address": _address(source, row_index, column),
                        "before": before, "after": after, "numberFormat": number_format})
    answer_hash = canonical_hash({"revision": answers.revision, "values": answers.values})
    review_hash = canonical_hash({"sourceHash": scan.source_hash, "answerHash": answer_hash, "changes": changes})
    return CleanupPreview(tuple(changes), scan.source_hash, answer_hash, review_hash)
