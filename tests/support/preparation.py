"""Invented small OOXML packages and hand-derived preservation expectations."""
from io import BytesIO
import json
from pathlib import Path
import re
from xml.sax.saxutils import escape
from zipfile import ZipFile

from examples.excel_mcp_fixtures import MAIN, REL, PKG_REL, _write_member


ORACLE = {"sourceTotal": 11, "targetTotal": 2, "sourceFormula": "=B2*Rates!$B$2+TaxRate",
          "dateSerial": 46340, "dateFormat": "yyyy-mm-dd", "merged": "A4:B4",
          "literalId": " 00123 ", "sourceSheets": ["Orders", "Rates"]}


def _cell(address, text):
    return f'<c r="{address}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def preparation_workbook(*, run_id=None, source=True, delta_probe=False, import_probe=False):
    if run_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", run_id):
        raise ValueError("Invalid synthetic run ID")
    header = ''.join(_cell(f'{column}1', name) for column, name in zip('ABCD', ('Key', 'Amount', 'Date', 'Total')))
    rows = (f'<row r="1">{header}</row><row r="2">{_cell("A2", " 00123 ")}'
            '<c r="B2" s="2"><v>5</v></c><c r="C2" s="1"><v>46340</v></c>'
            '<c r="D2"><f>B2*Rates!$B$2+TaxRate</f><v>11</v></c></row>'
            f'<row r="4">{_cell("A4", "Synthetic note")}</row>') if source else (
            f'<row r="1">{_cell("A1", "Key")}{_cell("B1", "Result")}</row>'
            f'<row r="2">{_cell("A2", " Personal ")}<c r="B2" s="2"><f>1+1</f><v>2</v></c></row>')
    names = '<definedName name="TaxRate">'+('1' if source else '100')+'</definedName>'
    if source:
        names += '<definedName name="LocalRate" localSheetId="1">Rates!$B$2</definedName>'
    if run_id:
        names += f'<definedName name="Gate_Run_Id">"{run_id}"</definedName>'
    if delta_probe:
        if not source or not run_id:
            raise ValueError("Delta probe requires a marked synthetic source group")
        names += '<definedName name="Gate_Delta_Probe">1</definedName>'
    if import_probe:
        if source or not run_id:
            raise ValueError("Import probe requires a marked synthetic personal target")
        names += '<definedName name="Gate_Import_Probe">1</definedName>'
    sheets = '<sheet name="Orders" sheetId="1" r:id="rId1"/>'
    if source:
        sheets += '<sheet name="Rates" sheetId="2" r:id="rId2"/>'
    members = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            + ('<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' if source else '')
            + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/></Types>',
        '_rels/.rels': f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{sheets}</sheets>'
            f'<definedNames>{names}</definedNames><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>',
        'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{PKG_REL}">'
            f'<Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>'
            + (f'<Relationship Id="rId2" Type="{REL}/worksheet" Target="worksheets/sheet2.xml"/>' if source else '')
            + f'<Relationship Id="rId3" Type="{REL}/styles" Target="styles.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{MAIN}" xmlns:r="{REL}">'
            f'<dimension ref="A1:{"D4" if source else "B2"}"/><sheetData>{rows}</sheetData>'
            + ('<mergeCells count="1"><mergeCell ref="A4:B4"/></mergeCells>' if source else '')
            + '<tableParts count="1"><tablePart r:id="rId1"/></tableParts></worksheet>',
        'xl/worksheets/_rels/sheet1.xml.rels': f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{REL}/table" Target="../tables/table1.xml"/></Relationships>',
        'xl/styles.xml': f'<styleSheet xmlns="{MAIN}"><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/></numFmts>'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/><bgColor indexed="64"/></patternFill></fill></fills>'
            '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
    }
    headers = ('Key', 'Amount', 'Date', 'Total') if source else ('Key', 'Result')
    ref = 'A1:D2' if source else 'A1:B2'
    columns = ''.join(f'<tableColumn id="{i}" name="{name}"/>' for i, name in enumerate(headers, 1))
    members['xl/tables/table1.xml'] = f'<table xmlns="{MAIN}" id="1" name="OrdersTable" displayName="OrdersTable" ref="{ref}" totalsRowShown="0">'
    members['xl/tables/table1.xml'] += f'<autoFilter ref="{ref}"/><tableColumns count="{len(headers)}">{columns}</tableColumns></table>'
    if source:
        rate_rows = f'<row r="1">{_cell("A1", "Class")}{_cell("B1", "Rate")}</row><row r="2">{_cell("A2", "Base")}<c r="B2"><v>2</v></c></row>'
        members['xl/worksheets/sheet2.xml'] = f'<worksheet xmlns="{MAIN}"><dimension ref="A1:B2"/><sheetData>{rate_rows}</sheetData></worksheet>'
    stream = BytesIO()
    with ZipFile(stream, 'w') as archive:
        for name, payload in members.items():
            _write_member(archive, name, payload)
    return stream.getvalue()


def create_preparation_fixture(output: Path, run_id: str) -> Path:
    paths = [output / name for name in ('preparation_target.xlsx', 'preparation_source.xlsx', 'preparation_oracle.json')]
    if any(path.exists() for path in paths):
        raise FileExistsError('Synthetic preparation fixture already exists')
    target = preparation_workbook(run_id=run_id, source=False)
    source = preparation_workbook(source=True)
    output.mkdir(parents=True, exist_ok=True)
    paths[0].write_bytes(target)
    paths[1].write_bytes(source)
    paths[2].write_text(json.dumps(ORACLE, indent=2) + '\n', encoding='utf-8')
    return paths[0]
