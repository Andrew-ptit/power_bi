"""Small immutable preparation contracts, independent of Office transport."""
from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
import math
import re

from pbip_assistant.errors import InputError


def require_hash(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise InputError("INVALID_REQUEST", "fingerprint", "A canonical SHA-256 fingerprint is required")


def require_identifier(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise InputError("INVALID_REQUEST", "identifier", "A bounded opaque identifier is required")


@dataclass(frozen=True)
class OperationScope:
    kind: str
    sheet_ids: tuple[str, ...]
    before_fingerprint: str
    after_fingerprint: str

    def __post_init__(self):
        if self.kind not in {"import", "cleanup"} or type(self.sheet_ids) is not tuple or len(self.sheet_ids) > 200:
            raise InputError("INVALID_REQUEST", "operation", "Unsupported preparation operation scope")
        if self.kind == "cleanup" and not self.sheet_ids:
            raise InputError("INVALID_REQUEST", "operation", "Cleanup requires a reviewed sheet scope")
        for value in self.sheet_ids:
            if not isinstance(value, str) or not re.fullmatch(r"[^\x00-\x1f]{1,128}", value):
                raise InputError("INVALID_REQUEST", "sheetId", "A bounded native worksheet identifier is required")
        if len(set(self.sheet_ids)) != len(self.sheet_ids):
            raise InputError("INVALID_REQUEST", "operation", "Duplicate sheet identifiers")
        require_hash(self.before_fingerprint)
        require_hash(self.after_fingerprint)


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    required_bytes: int


@dataclass(frozen=True)
class RestoreAttempt:
    attempt_id: str
    point_id: str
    direction: str


@dataclass(frozen=True)
class SourceInventory:
    inventory_hash: str
    _root: Path
    _folder: Path
    _files: tuple[dict, ...]
    _sheets: tuple[dict, ...]
    _errors: tuple[dict, ...]
    _stamps: tuple[tuple, ...]
    session_bytes: int

    def public(self):
        return deepcopy({"inventoryHash": self.inventory_hash, "files": list(self._files),
                         "sheets": list(self._sheets), "errors": list(self._errors),
                         "sessionBytes": self.session_bytes})


@dataclass(frozen=True)
class SourceSnapshot:
    source_id: str
    sheet_id: str
    headers: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    formula_cells: frozenset[tuple[int, int]] = frozenset()
    column_kinds: tuple[str, ...] | None = None
    number_formats: tuple[tuple[str, ...], ...] | None = None
    date_system: str = "1900"
    row_offset: int = 1
    column_offset: int = 0

    def __post_init__(self):
        require_identifier(self.source_id)
        if not isinstance(self.sheet_id, str) or not re.fullmatch(r"[^\x00-\x1f]{1,128}", self.sheet_id):
            raise InputError("INVALID_REQUEST", "sheetId", "Invalid native worksheet identifier")
        headers, rows = tuple(self.headers), tuple(tuple(row) for row in self.rows)
        if not 0 < len(headers) <= 200 or len(rows) > 100000 or len(rows) * len(headers) > 400000:
            raise InputError("REQUEST_LIMIT", "sources", "Select at most 200 columns, 100000 rows and 400000 cells")
        if (type(self.row_offset) is not int or type(self.column_offset) is not int
                or self.row_offset < 0 or self.column_offset < 0
                or self.row_offset + len(rows) > 1048576 or self.column_offset + len(headers) > 16384):
            raise InputError("INVALID_REQUEST", "sourceOrigin", "Source frame is outside the worksheet")
        if (any(not isinstance(h, str) or not h or len(h) > 10000 for h in headers)
                or len({h.casefold() for h in headers}) != len(headers) or self.date_system not in {"1900", "1904"}):
            raise InputError("INVALID_REQUEST", "sources", "Reviewed unique headers and Excel date system are required")
        size = 0
        for row in rows:
            if len(row) != len(headers):
                raise InputError("INVALID_REQUEST", "rows", "Source row width does not match reviewed headers")
            for value in row:
                if value is not None and type(value) not in (str, int, float, bool):
                    raise InputError("INVALID_REQUEST", "rows", "Source contains an unsupported cell value")
                if isinstance(value, str) and len(value) > 10000 or isinstance(value, float) and not math.isfinite(value):
                    raise InputError("INVALID_REQUEST", "rows", "Source contains an invalid or unbounded cell")
                size += len(value.encode("utf-8")) if isinstance(value, str) else 32
                if size > 64 * 1024 * 1024:
                    raise InputError("REQUEST_LIMIT", "rows", "Source exceeds the existing per-source byte bound")
        formula_cells = frozenset(self.formula_cells)
        if any(type(r) is not int or type(c) is not int or not 0 <= r < len(rows) or not 0 <= c < len(headers) for r, c in formula_cells):
            raise InputError("INVALID_REQUEST", "formulaCells", "Formula scope is outside source data")
        kinds = tuple(self.column_kinds) if self.column_kinds is not None else ("unknown",) * len(headers)
        if len(kinds) != len(headers) or any(k not in {"unknown", "text", "identifier", "number", "date"} for k in kinds):
            raise InputError("INVALID_REQUEST", "columnKinds", "Unsupported source column kinds")
        formats = tuple(tuple(row) for row in self.number_formats) if self.number_formats is not None else tuple(
            ("General",) * len(headers) for _ in rows)
        if len(formats) != len(rows) or any(len(row) != len(headers) or any(not isinstance(f, str) or len(f) > 256 for f in row) for row in formats):
            raise InputError("INVALID_REQUEST", "numberFormats", "Source number-format scope is invalid")
        for name, value in (("headers", headers), ("rows", rows), ("formula_cells", formula_cells),
                            ("column_kinds", kinds), ("number_formats", formats)):
            object.__setattr__(self, name, value)

    @property
    def fingerprint(self):
        from pbip_assistant.sources.assistant_ingest import canonical_hash
        return canonical_hash({"sourceId": self.source_id, "sheetId": self.sheet_id,
            "headers": self.headers, "rows": self.rows, "formulas": sorted(self.formula_cells),
            "kinds": self.column_kinds, "formats": self.number_formats, "dateSystem": self.date_system,
            "rowOffset": self.row_offset, "columnOffset": self.column_offset})


@dataclass(frozen=True)
class WorkbookBinding:
    binding_id: str
    semantic_fingerprint: str


@dataclass(frozen=True)
class AnswerRevision:
    revision: int
    values: dict

    def __post_init__(self):
        if type(self.revision) is not int or self.revision < 0 or not isinstance(self.values, dict):
            raise InputError("INVALID_REQUEST", "answers", "Invalid answer revision")
        object.__setattr__(self, "values", deepcopy(self.values))


@dataclass(frozen=True)
class ScanResult:
    binding: WorkbookBinding
    sources: tuple[SourceSnapshot, ...]
    findings: tuple[dict, ...]
    questions: tuple[dict, ...]
    source_hash: str

    def public(self):
        return deepcopy({"sourceHash": self.source_hash, "findings": list(self.findings), "questions": list(self.questions),
            "sourceCount": len(self.sources), "rowCount": sum(len(s.rows) for s in self.sources)})


@dataclass(frozen=True)
class CleanupPreview:
    changes: tuple[dict, ...]
    source_hash: str
    answer_hash: str
    review_hash: str

    def public(self):
        examples = deepcopy(list(self.changes[:20]))
        for item in examples:
            item["displayTruncated"] = any(isinstance(item[key], str) and len(item[key]) > 256 for key in ("before", "after"))
            for key in ("before", "after"):
                if isinstance(item[key], str):
                    item[key] = item[key][:256]
        return deepcopy({"sourceHash": self.source_hash, "answerHash": self.answer_hash,
                         "reviewHash": self.review_hash, "changeCount": len(self.changes), "examples": examples})
