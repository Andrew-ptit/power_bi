"""Build deterministic, synthetic W-02 Excel/CSV fixtures without source rows.

The 17 column names match the supplied CSV header. This module never reads that
CSV; every record below is invented for parser and profiling tests.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_STORED, ZipFile, ZipInfo


ORDER_HEADERS = (
    "OrderID", "CustomerID", "OrderDate", "ProductID", "Quantity", "Discount",
    "PaymentMethod", "Status", "Age", "City", "SignupDate", "CustomerSegment",
    "ProductName", "Category", "UnitPrice", "Sales", "OrderValue",
)

# Dates are deliberately mixed in the CSV. The workbook stores dates as Excel
# serial numbers with a date style, so a reader must not silently treat them as
# ordinary numeric quantities.
ORDERS = (
    ("SYN-001", "C-SYN-01", "2026-09-01", "P-SYN-01", 2, 10, "Card", "Completed", 29, "South City", "2024-01-10", "Retail", "Sample A", "A", 100, 180, 180),
    ("SYN-002", "C-SYN-01", "03/09/2026", "P-SYN-02", 1, 0, "Cash", "Completed", 29, "South City", "2024-01-10", "Retail", "Sample, Premium", "B", 50, 50, 50),
    ("SYN-003", "C-SYN-02", "2026-09-04", "P-SYN-01", -1, 10, "Card", "Returned", 34, "North City", "2023-05-03", "Business", "Sample A", "A", 100, -90, -90),
    ("SYN-004", "C-SYN-03", "2026-09-05", "P-SYN-03", 0, 0, "Transfer", "Cancelled", 41, "Central City", "2022-08-20", "Retail", "Sample C", "C", 75, 0, 0),
    ("SYN-005", "C-SYN-02", "2026-09-06", "P-SYN-ORPHAN", 1, 30, "Card", "Completed", 34, None, "2023-05-03", "Business", "Sample Orphan", "D", 200, 140, 140),
    ("SYN-006", "C-SYN-04", "2026-09-07", "P-SYN-02", 3, 5, "Cash", "Completed", None, "West City", "2025-02-14", "Retail", "Sample\nBlend", "B", 50, 142.5, 142.5),
)

PRODUCTS = (
    ("ProductID", "ProductName", "Category", "UnitPrice"),
    ("P-SYN-01", "Sample A", "A", 100),
    ("P-SYN-02", "Sample, Premium", "B", 50),
    ("P-SYN-03", "Sample C", "C", 75),
)
CUSTOMERS = (
    ("CustomerID", "City", "CustomerSegment"),
    ("C-SYN-01", "South City", "Retail"),
    ("C-SYN-02", "North City", "Business"),
    ("C-SYN-03", "Central City", "Retail"),
    ("C-SYN-04", "West City", "Retail"),
)
CALENDAR = (
    ("Date", "Year", "Month"),
    *((f"2026-09-{day:02d}", 2026, 9) for day in range(1, 8)),
)

_FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _csv_bytes(rows: tuple[tuple[object, ...], ...], *, delimiter: str = ",", bom: bool = False) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\r\n")
    writer.writerows(rows)
    return (b"\xef\xbb\xbf" if bom else b"") + stream.getvalue().encode("utf-8")


def _excel_serial(value: str) -> int:
    if "/" in value:
        day, month, year = map(int, value.split("/"))
        parsed = date(year, month, day)
    else:
        parsed = date.fromisoformat(value)
    return (parsed - date(1899, 12, 30)).days


def _col(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(ref: str, value: object, *, date_cell: bool = False, formula: str | None = None, cache: bool = True) -> str:
    if value is None:
        return ""
    style = ' s="1"' if date_cell else ""
    if formula is not None:
        cached = f"<v>{value}</v>" if cache else "<v/>"
        return f'<c r="{ref}"{style}><f>{escape(formula)}</f>{cached}</c>'
    if date_cell:
        return f'<c r="{ref}"{style}><v>{_excel_serial(str(value))}</v></c>'
    if isinstance(value, (int, float, Decimal)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def _zip_write(archive: ZipFile, name: str, payload: str) -> None:
    info = ZipInfo(name, _FIXED_ZIP_TIME)
    info.compress_type = ZIP_STORED
    info.create_system = 0
    info.external_attr = 0
    archive.writestr(info, payload.encode("utf-8"))


def _xlsx_bytes(*, formula_cache: bool = True) -> bytes:
    rows = (ORDER_HEADERS, *ORDERS)
    sheet_rows = []
    for row_num, row in enumerate(rows, start=1):
        cells = []
        for col_num, value in enumerate(row, start=1):
            ref = f"{_col(col_num)}{row_num}"
            is_date = row_num > 1 and col_num in (3, 11)
            formula = "E2*O2*(1-F2/100)" if row_num == 2 and col_num == 16 else None
            cells.append(_cell(ref, value, date_cell=is_date, formula=formula, cache=formula_cache))
        sheet_rows.append(f'<row r="{row_num}">{"".join(cells)}</row>')
    table_ref = f"A1:Q{len(rows)}"
    table_columns = "".join(
        f'<tableColumn id="{index}" name="{escape(name)}"/>'
        for index, name in enumerate(ORDER_HEADERS, start=1)
    )
    members = (
        ("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
         '<Default Extension="xml" ContentType="application/xml"/>'
         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
         '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
         '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
         '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
         '</Types>'),
        ("_rels/.rels", f'<Relationships xmlns="{_PKG_REL_NS}"><Relationship Id="rId1" '
         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
         'Target="xl/workbook.xml"/></Relationships>'),
        ("xl/workbook.xml", f'<workbook xmlns="{_MAIN_NS}" xmlns:r="{_REL_NS}">'
         '<sheets><sheet name="Orders" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        ("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{_PKG_REL_NS}">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
         '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
         '</Relationships>'),
        ("xl/styles.xml", f'<styleSheet xmlns="{_MAIN_NS}"><numFmts count="1">'
         '<numFmt numFmtId="164" formatCode="yyyy-mm-dd"/></numFmts>'
         '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
         '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
         '<borders count="1"><border/></borders>'
         '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
         '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
         '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
         '</cellXfs></styleSheet>'),
        ("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{_MAIN_NS}" xmlns:r="{_REL_NS}">'
         f'<dimension ref="{table_ref}"/><sheetData>{"".join(sheet_rows)}</sheetData>'
         '<tableParts count="1"><tablePart r:id="rId1"/></tableParts></worksheet>'),
        ("xl/worksheets/_rels/sheet1.xml.rels", f'<Relationships xmlns="{_PKG_REL_NS}">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" '
         'Target="../tables/table1.xml"/></Relationships>'),
        ("xl/tables/table1.xml", f'<table xmlns="{_MAIN_NS}" id="1" name="OrdersTable" displayName="OrdersTable" '
         f'ref="{table_ref}" totalsRowShown="0"><autoFilter ref="{table_ref}"/>'
         f'<tableColumns count="{len(ORDER_HEADERS)}">{table_columns}</tableColumns>'
         '<tableStyleInfo name="TableStyleMedium2" showFirstColumn="0" showLastColumn="0" '
         'showRowStripes="1" showColumnStripes="0"/></table>'),
    )
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in members:
            _zip_write(archive, name, content)
    return buffer.getvalue()


def build_fixtures() -> dict[str, bytes]:
    """Return every artifact as bytes, with no filesystem reads or network I/O."""
    baseline = (ORDER_HEADERS, *ORDERS)
    drift_headers = tuple("DiscountPct" if h == "Discount" else h for h in ORDER_HEADERS[:-1]) + ("Region",)
    drift_row = list(ORDERS[0][:-1]) + ["South"]
    ambiguous = list(ORDERS[0])
    ambiguous[5] = "0,10"
    duplicate_headers = list(ORDER_HEADERS)
    duplicate_headers[16] = "Sales"
    return {
        "orders_synthetic.csv": _csv_bytes(baseline),
        "orders_utf8_bom.csv": _csv_bytes(baseline, bom=True),
        "orders_semicolon.csv": _csv_bytes(baseline, delimiter=";"),
        "orders_quoted_multiline.csv": _csv_bytes((ORDER_HEADERS, ORDERS[1], ORDERS[5])),
        "orders_short_row.csv": _csv_bytes((ORDER_HEADERS, ORDERS[0][:-1])),
        "orders_wide_row.csv": _csv_bytes((ORDER_HEADERS, (*ORDERS[0], "EXTRA"))),
        "orders_invalid_utf8.csv": _csv_bytes((ORDER_HEADERS, ORDERS[0])) + b"\xff\xfe",
        "orders_schema_drift.csv": _csv_bytes((drift_headers, tuple(drift_row))),
        "orders_duplicate_header.csv": _csv_bytes((tuple(duplicate_headers), ORDERS[0])),
        "orders_ambiguous_discount.csv": _csv_bytes((ORDER_HEADERS, ORDERS[0], tuple(ambiguous)), delimiter=";"),
        "orders_header_only.csv": _csv_bytes((ORDER_HEADERS,)),
        "products_synthetic.csv": _csv_bytes(PRODUCTS),
        "customers_synthetic.csv": _csv_bytes(CUSTOMERS),
        "calendar_synthetic.csv": _csv_bytes(CALENDAR),
        "orders_synthetic.xlsx": _xlsx_bytes(),
        "orders_formula_no_cache.xlsx": _xlsx_bytes(formula_cache=False),
    }


EXPECTED = {
    "orders_synthetic.csv": {"result": "accept_with_warnings", "records": 6, "statuses": {"Completed": 4, "Returned": 1, "Cancelled": 1}, "quantity_total": 6, "sales_total": "422.5", "nulls": {"Age": 1, "City": 1}, "orphan_product_ids": ["P-SYN-ORPHAN"], "notes": ["OrderDate includes ISO and DD/MM/YYYY; date interpretation requires review", "Sales is a sample source field, not confirmed Net Sales"]},
    "orders_utf8_bom.csv": {"result": "accept_with_warnings", "records": 6, "encoding": "utf-8-sig", "delimiter": ","},
    "orders_semicolon.csv": {"result": "accept_with_warnings", "records": 6, "encoding": "utf-8", "delimiter": ";"},
    "orders_quoted_multiline.csv": {"result": "accept", "records": 2, "physical_lines": 4},
    "orders_short_row.csv": {"result": "row_error", "records": 1, "bad_record": 2, "actual_columns": 16, "expected_columns": 17},
    "orders_wide_row.csv": {"result": "row_error", "records": 1, "bad_record": 2, "actual_columns": 18, "expected_columns": 17},
    "orders_invalid_utf8.csv": {"result": "encoding_error", "encoding": "utf-8"},
    "orders_schema_drift.csv": {"result": "schema_drift", "records": 1, "missing": ["Discount", "OrderValue"], "added": ["DiscountPct", "Region"]},
    "orders_duplicate_header.csv": {"result": "header_error", "duplicate": ["Sales"]},
    "orders_ambiguous_discount.csv": {"result": "needs_clarification", "records": 2, "values": ["10", "0,10"], "delimiter": ";"},
    "orders_header_only.csv": {"result": "accept", "records": 0},
    "products_synthetic.csv": {"result": "accept", "records": 3},
    "customers_synthetic.csv": {"result": "accept", "records": 4},
    "calendar_synthetic.csv": {"result": "accept", "records": 7},
    "orders_synthetic.xlsx": {"result": "accept_with_warnings", "records": 6, "table": "OrdersTable", "table_ref": "A1:Q7", "date_style_index": 1, "formula_cell": "P2", "formula_cached_value": "180"},
    "orders_formula_no_cache.xlsx": {"result": "formula_cache_warning", "records": 6, "formula_cell": "P2"},
}


def generate(root: Path) -> Path:
    """Regenerate only this dedicated fixture directory; never read user data."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    payloads = build_fixtures()
    for name, payload in sorted(payloads.items()):
        (root / name).write_bytes(payload)
    manifest = {
        "fixture_set": "W-02-source-v1",
        "provenance": {
            "schema_source": "clean_final_data.csv header names only",
            "source_rows_used": 0,
            "header_sha256": hashlib.sha256(",".join(ORDER_HEADERS).encode("utf-8")).hexdigest(),
            "synthetic_records": True,
        },
        "files": {
            name: {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "expected": EXPECTED[name]}
            for name, payload in sorted(payloads.items())
        },
        "limitations": [
            "Synthetic fixture only; no Power BI Desktop/runtime validation.",
            "Expected totals describe source values, not a validated business KPI.",
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=Path("tests/fixtures_source"))
    args = parser.parse_args()
    print(generate(args.output))
