"""Máy kiểm traceability Assistant; discovery chỉ lập suite, không chạy runtime."""

from collections import Counter
from copy import deepcopy
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs/current/ASSISTANT_FLOW_SPEC.md"
TRACEABILITY = ROOT / "docs/current/ASSISTANT_TRACEABILITY.md"
STATUSES = {"covered", "partial", "not-implemented"}
CASE_ID = re.compile(r"tests(?:\.[A-Za-z_][A-Za-z_0-9]*){3,}")


class TraceabilityError(ValueError):
    """Tài liệu không đáp ứng hợp đồng kiểm chứng, không tự sửa hoặc bỏ dòng."""


def section(text, number):
    found = re.search(r"^## " + str(number) + r"\..*?(?=^## |\Z)", text, re.M | re.S)
    if found is None:
        raise TraceabilityError("Thiếu mục spec: " + str(number))
    return found.group(0)


def spec_ids(text):
    # 47 FR là các hàng yêu cầu trong bảng mục 6; BR/PR có namespace riêng.
    fr = re.findall(r"^\| (AF-[A-Z]+-\d+) \|", section(text, 6), re.M)
    cases = re.findall(r"^\| (T-(?:WL\d+-\d+|E2E-[A-Z]+)) \|", section(text, 13), re.M)
    if len(fr) != len(set(fr)) or len(cases) != len(set(cases)):
        raise TraceabilityError("Spec có ID trùng.")
    return {identifier: "FR" for identifier in fr} | {identifier: "test" for identifier in cases}


def traceability_rows(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if not cells or not cells[0].startswith(("AF-", "T-WL", "T-E2E-")):
            continue
        if len(cells) != 5:
            raise TraceabilityError("Sai số cột ở ID: " + cells[0])
        identifier, kind, case_text, status, reason = cells
        refs = [] if case_text == "—" else [item.strip().strip("`") for item in case_text.split(";")]
        rows.append({"id": identifier, "kind": kind, "cases": refs, "status": status,
                     "reason": reason, "caseText": case_text})
    return rows


def validate_traceability(rows, expected, discovered):
    counts = Counter(row["id"] for row in rows)
    duplicates = sorted(identifier for identifier, count in counts.items() if count != 1)
    if duplicates:
        raise TraceabilityError("ID trùng: " + ", ".join(duplicates))
    ghost = sorted(set(counts) - set(expected))
    missing = sorted(set(expected) - set(counts))
    if ghost:
        raise TraceabilityError("ID ghost: " + ", ".join(ghost))
    if missing:
        raise TraceabilityError("Thiếu ID: " + ", ".join(missing))
    for row in rows:
        identifier = row["id"]
        if row["kind"] != expected[identifier]:
            raise TraceabilityError("Sai loại ID: " + identifier)
        if row["status"] not in STATUSES:
            raise TraceabilityError("Sai trạng thái: " + identifier)
        if not row["reason"]:
            raise TraceabilityError("Thiếu lý do/phạm vi: " + identifier)
        if row["status"] == "not-implemented":
            if row["caseText"] != "—" or row["cases"]:
                raise TraceabilityError("Chưa triển khai phải dùng —: " + identifier)
            continue
        if not row["cases"] or len(row["cases"]) != len(set(row["cases"])):
            raise TraceabilityError("Thiếu hoặc trùng case bảo vệ: " + identifier)
        for reference in row["cases"]:
            if CASE_ID.fullmatch(reference) is None or reference not in discovered:
                raise TraceabilityError("Case không tồn tại: " + reference)


def cases_in(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases_in(item)
        else:
            yield item


class AssistantTraceabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected = spec_ids(SPEC.read_text(encoding="utf-8"))
        cls.rows = traceability_rows(TRACEABILITY.read_text(encoding="utf-8"))
        # Đây chỉ là discovery, không TextTestRunner.run hoặc TestCase.run.
        loader = unittest.TestLoader()
        suite = loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        if loader.errors:
            raise TraceabilityError("Discovery không import đủ module kiểm thử.")
        cls.discovered = {case.id() for case in cases_in(suite)}

    def test_spec_has_exactly_47_fr_and_45_test_ids_without_business_rule_ghosts(self):
        self.assertEqual(Counter(self.expected.values()), {"FR": 47, "test": 45})
        self.assertFalse(any("-BR-" in identifier or identifier.startswith("AF-PR-")
                             for identifier in self.expected))
        self.assertEqual(Counter(row["kind"] for row in self.rows), {"FR": 47, "test": 45})

    def test_every_spec_id_occurs_once_with_real_discovered_case_or_explicit_gap(self):
        validate_traceability(self.rows, self.expected, self.discovered)
        self.assertEqual(len(self.rows), len(self.expected))

    def test_partial_and_not_implemented_rows_explain_remaining_scope(self):
        for row in self.rows:
            if row["status"] in {"partial", "not-implemented"}:
                with self.subTest(identifier=row["id"]):
                    self.assertTrue(row["reason"].strip())
                    self.assertGreaterEqual(len(row["reason"]), 20)
                    if row["status"] == "not-implemented":
                        self.assertEqual(row["caseText"], "—")
                        self.assertEqual(row["cases"], [])

    def test_guard_rejects_removed_spec_row(self):
        with self.assertRaisesRegex(TraceabilityError, "Thiếu ID"):
            validate_traceability(self.rows[1:], self.expected, self.discovered)

    def test_guard_rejects_duplicate_id_even_with_valid_case(self):
        with self.assertRaisesRegex(TraceabilityError, "ID trùng"):
            validate_traceability(self.rows + [deepcopy(self.rows[0])], self.expected, self.discovered)

    def test_guard_rejects_ghost_requirement(self):
        changed = deepcopy(self.rows)
        changed[0]["id"] = "AF-GHOST-999"
        with self.assertRaisesRegex(TraceabilityError, "ID ghost"):
            validate_traceability(changed, self.expected, self.discovered)

    def test_guard_rejects_nonexistent_case_id(self):
        changed = deepcopy(self.rows)
        changed[0]["cases"] = ["tests.contracts.test_absent.AbsentTests.test_absent"]
        with self.assertRaisesRegex(TraceabilityError, "Case không tồn tại"):
            validate_traceability(changed, self.expected, self.discovered)

    def test_guard_rejects_invalid_status_or_mislabeled_fr(self):
        for field, value, diagnostic in (("status", "complete", "Sai trạng thái"),
                                         ("kind", "test", "Sai loại ID")):
            changed = deepcopy(self.rows)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(TraceabilityError, diagnostic):
                validate_traceability(changed, self.expected, self.discovered)

    def test_guard_rejects_gap_without_reason_or_fake_not_implemented_evidence(self):
        for change, diagnostic in (({"status": "partial", "reason": ""}, "Thiếu lý do"),
                                    ({"status": "not-implemented"}, "Chưa triển khai"),
                                    ({"cases": []}, "Thiếu hoặc trùng case")):
            changed = deepcopy(self.rows)
            changed[0].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(TraceabilityError, diagnostic):
                validate_traceability(changed, self.expected, self.discovered)

    def test_markdown_parser_rejects_missing_columns_instead_of_ignoring_row(self):
        with self.assertRaisesRegex(TraceabilityError, "Sai số cột"):
            traceability_rows("| AF-GD-001 | FR | covered |")


if __name__ == "__main__":
    unittest.main()
