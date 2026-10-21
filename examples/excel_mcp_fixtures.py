"""Deterministic synthetic workbook for the Excel MCP integration spike.

The data is invented and contains no user workbook content.  The input has no
formula cells: formulas and calculated values in the manifest are the expected
result of the future approved-copy workflow.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_STORED, ZipFile, ZipInfo


FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

SALES_HEADERS = (
    "SaleID",
    "EmployeeID",
    "Region",
    "SaleDate",
    "Gross Revenue",
    "Discount Value",
    "Return Value",
    "Total Sold Qty",
    "Total Return Qty",
)

SALES_ROWS = (
    ("S-001", "E-01", "South", "2026-09-01", 1000, 100, 50, 10, 1),
    ("S-002", "E-02", "North", "2026-09-02", 1500, 100, 50, 15, 0),
    ("S-003", "E-03", "South", "2026-09-03", 2250, 150, 100, 20, 2),
    ("S-004", "E-04", "Central", "2026-09-04", 700, 50, 50, 5, 1),
    ("S-005", "E-05", "South", "2026-09-05", 3000, 200, 100, 25, 1),
    ("S-006", "E-06", "North", "2026-09-06", 1400, 100, 100, 12, 3),
)

COMMISSION_HEADERS = ("Min Net Revenue", "Commission Rate")
COMMISSION_ROWS = ((0, 0.05), (1000, 0.07), (2000, 0.10))

EXPECTED_ROWS = (
    {"SaleID": "S-001", "Net Revenue": 850, "Return Rate": 0.10, "Commission Value": 42.5, "Sales Rank": "Bottom"},
    {"SaleID": "S-002", "Net Revenue": 1350, "Return Rate": 0.00, "Commission Value": 94.5, "Sales Rank": "Bottom"},
    {"SaleID": "S-003", "Net Revenue": 2000, "Return Rate": 0.10, "Commission Value": 200.0, "Sales Rank": "Top 20%"},
    {"SaleID": "S-004", "Net Revenue": 600, "Return Rate": 0.20, "Commission Value": 30.0, "Sales Rank": "Bottom"},
    {"SaleID": "S-005", "Net Revenue": 2700, "Return Rate": 0.04, "Commission Value": 270.0, "Sales Rank": "Top 10%"},
    {"SaleID": "S-006", "Net Revenue": 1200, "Return Rate": 0.25, "Commission Value": 84.0, "Sales Rank": "Bottom"},
)

PROMPT = """Trong SalesTable:
1. Tạo Net Revenue = Gross Revenue - Discount Value - Return Value.
2. Tạo Return Rate = Total Return Qty / Total Sold Qty; nếu mẫu số bằng 0 thì trả 0.
3. Tạo Commission Value bằng XLOOKUP gần đúng theo Min Net Revenue ở Dim_Commission.
4. Xếp Sales Rank theo Net Revenue: percentile >= 90% là Top 10%, >= 80% là Top 20%, còn lại là Bottom."""


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(reference: str, value: object) -> str:
    if isinstance(value, (int, float)):
        return f'<c r="{reference}"><v>{value}</v></c>'
    return f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def _sheet_xml(headers: tuple[str, ...], rows: tuple[tuple[object, ...], ...], table_ref: str) -> str:
    xml_rows: list[str] = []
    for row_number, row in enumerate((headers, *rows), start=1):
        cells = "".join(
            _cell(f"{_column_name(column_number)}{row_number}", value)
            for column_number, value in enumerate(row, start=1)
        )
        xml_rows.append(f'<row r="{row_number}">{cells}</row>')
    return (
        f'<worksheet xmlns="{MAIN}" xmlns:r="{REL}">'
        f'<dimension ref="{table_ref}"/><sheetData>{"".join(xml_rows)}</sheetData>'
        '<tableParts count="1"><tablePart r:id="rId1"/></tableParts></worksheet>'
    )


def _table_xml(table_id: int, name: str, headers: tuple[str, ...], ref: str) -> str:
    columns = "".join(
        f'<tableColumn id="{index}" name="{escape(header)}"/>'
        for index, header in enumerate(headers, start=1)
    )
    return (
        f'<table xmlns="{MAIN}" id="{table_id}" name="{name}" displayName="{name}" '
        f'ref="{ref}" totalsRowShown="0"><autoFilter ref="{ref}"/>'
        f'<tableColumns count="{len(headers)}">{columns}</tableColumns>'
        '<tableStyleInfo name="TableStyleMedium2" showFirstColumn="0" showLastColumn="0" '
        'showRowStripes="1" showColumnStripes="0"/></table>'
    )


def _write_member(archive: ZipFile, name: str, payload: str) -> None:
    info = ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = ZIP_STORED
    info.create_system = 0
    info.external_attr = 0
    archive.writestr(info, payload.encode("utf-8"))


def build_workbook() -> bytes:
    sales_ref = f"A1:I{len(SALES_ROWS) + 1}"
    commission_ref = f"A1:B{len(COMMISSION_ROWS) + 1}"
    members = (
        (
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
            '<Override PartName="/xl/tables/table2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
            '</Types>',
        ),
        (
            "_rels/.rels",
            f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>',
        ),
        (
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
            '<sheet name="Sales" sheetId="1" r:id="rId1"/>'
            '<sheet name="Dim_Commission" sheetId="2" r:id="rId2"/>'
            '</sheets><calcPr calcId="0" fullCalcOnLoad="1"/></workbook>',
        ),
        (
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PKG_REL}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>',
        ),
        (
            "xl/styles.xml",
            f'<styleSheet xmlns="{MAIN}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            '</styleSheet>',
        ),
        ("xl/worksheets/sheet1.xml", _sheet_xml(SALES_HEADERS, SALES_ROWS, sales_ref)),
        ("xl/worksheets/sheet2.xml", _sheet_xml(COMMISSION_HEADERS, COMMISSION_ROWS, commission_ref)),
        (
            "xl/worksheets/_rels/sheet1.xml.rels",
            f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" '
            'Target="../tables/table1.xml"/></Relationships>',
        ),
        (
            "xl/worksheets/_rels/sheet2.xml.rels",
            f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" '
            'Target="../tables/table2.xml"/></Relationships>',
        ),
        ("xl/tables/table1.xml", _table_xml(1, "SalesTable", SALES_HEADERS, sales_ref)),
        ("xl/tables/table2.xml", _table_xml(2, "CommissionTable", COMMISSION_HEADERS, commission_ref)),
    )
    from io import BytesIO

    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, payload in members:
            _write_member(archive, name, payload)
    return buffer.getvalue()


def build_manifest(workbook: bytes) -> dict[str, object]:
    return {
        "fixture_set": "EXCEL-MCP-v1",
        "synthetic": True,
        "workbook": {
            "name": "excel_mcp_sales_input.xlsx",
            "sha256": hashlib.sha256(workbook).hexdigest(),
            "bytes": len(workbook),
            "source_formula_cells": 0,
            "sheets": {
                "Sales": {"table": "SalesTable", "rows": len(SALES_ROWS), "columns": list(SALES_HEADERS)},
                "Dim_Commission": {"table": "CommissionTable", "rows": len(COMMISSION_ROWS), "columns": list(COMMISSION_HEADERS)},
            },
        },
        "prompt": PROMPT,
        "business_rules": {
            "commission_match": "largest Min Net Revenue less than or equal to Net Revenue",
            "zero_denominator": "Return Rate is 0",
            "rank": "PERCENTRANK.INC >= 0.9 Top 10%; >= 0.8 Top 20%; otherwise Bottom",
        },
        "expected_operations": [
            "excel.formula_column.add:SalesTable[Net Revenue]",
            "excel.formula_column.add:SalesTable[Return Rate]",
            "excel.formula_column.add:SalesTable[Commission Value]",
            "excel.formula_column.add:SalesTable[Sales Rank]",
        ],
        "formula_templates": {
            "Net Revenue": "=[@[Gross Revenue]]-[@[Discount Value]]-[@[Return Value]]",
            "Return Rate": "=IFERROR([@[Total Return Qty]]/[@[Total Sold Qty]],0)",
            "Commission Value": "=[@[Net Revenue]]*XLOOKUP([@[Net Revenue]],CommissionTable[Min Net Revenue],CommissionTable[Commission Rate],0,-1)",
            "Sales Rank": "=LET(p,PERCENTRANK.INC(SalesTable[Net Revenue],[@[Net Revenue]]),IFS(p>=0.9,\"Top 10%\",p>=0.8,\"Top 20%\",TRUE,\"Bottom\"))",
        },
        "expected_rows": list(EXPECTED_ROWS),
        "limitations": [
            "Synthetic data only; no business truth is implied.",
            "Fixture generation and parser tests do not prove that Excel MCP or Excel calculation has run.",
        ],
    }


def generate(root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    workbook = build_workbook()
    workbook_path = root / "excel_mcp_sales_input.xlsx"
    workbook_path.write_bytes(workbook)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(build_manifest(workbook), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=Path("tests/fixtures/excel"))
    arguments = parser.parse_args()
    print(generate(arguments.output))
