# Contract: browse, selection inventory và typed import

Mọi request là `POST /api/preparation/<action>` với `X-Local-Token` như hiện có, body đóng (closed keys) qua `pbip_assistant/sources/preparation/wire.py` + `pbip_assistant/schemas/preparation.schema.json`. Không thêm route ngoài danh sách này.

## 1. `browse` — duyệt cây thư mục, không đọc nội dung

**Request**

```json
{
  "action": "browse",
  "preparationId": "prep_…",
  "expectedClaimVersion": 3,
  "root": "C:\\Data\\dataset",
  "relativePath": "sales/2026"
}
```

- `root`: thư mục tuyệt đối người dùng chọn từ dialog (`pick-folder`), phải resolve được và là directory.
- `relativePath`: `""` = gốc; không tuyệt đối, không chứa `..`; đi vào chỉ bằng tên thư mục con.

**Response**

```json
{
  "rootName": "dataset",
  "relativePath": "sales/2026",
  "breadcrumb": [{"name": "dataset", "relativePath": ""}, {"name": "sales", "relativePath": "sales"}, {"name": "2026", "relativePath": "sales/2026"}],
  "parentRelativePath": "sales",
  "entries": [
    {"name": "archive", "kind": "folder"},
    {"name": "dim_locations.csv", "kind": "file", "extension": "csv", "size": 20480, "modified": "2026-11-18T08:00:00+07:00"}
  ],
  "truncated": false
}
```

Luật:

- Chỉ trả `kind: "folder"` và file có đuôi `.csv` / `.xlsx` (casefold). File khác và file ẩn hệ thống bị bỏ qua.
- Sắp xếp: folder trước, sau đó theo `name.casefold()`, hoà thì theo `name`.
- Tối đa 500 entry; vượt → `truncated: true` và vẫn trả 500 entry đầu.
- Không đọc/hash nội dung file, không ghi, không theo reparse point/symlink; thoát root → `DP_BROWSE_ESCAPE`.
- Không trả đường dẫn tuyệt đối của entry, không trả raw path trong lỗi.

**Lỗi**: `DP_BROWSE_ESCAPE`, `DP_BROWSE_LIMIT` (quá 500), `DP_SOURCE_STALE` (thư mục biến mất/đổi).

## 2. `inventory` — chỉ đọc các file đã tick

**Request**

```json
{
  "action": "inventory",
  "preparationId": "prep_…",
  "expectedClaimVersion": 3,
  "root": "C:\\Data\\dataset",
  "items": [
    {"relativePath": "", "fileName": "dim_products.csv"},
    {"relativePath": "sales/2026", "fileName": "orders.xlsx"}
  ]
}
```

- `items`: 1…200 phần tử; mỗi cặp phải tồn tại, đúng đuôi hỗ trợ, nằm trong root.
- Server chỉ đọc/hash những file này (không đọc cả thư mục). Tổng byte ≤ `MAX_BYTES_PER_SESSION` như hiện có.
- Lỗi của từng file được gom vào `errors[]` (không làm hỏng cả lô), trừ lỗi guard/limit toàn lô.
- Response giữ nguyên shape `SourceInventory.public()` hiện có: `inventoryHash`, `folderName`, `files[]` (`fileId`, `fileName`, `kind`, `byteLength`, `sourceHash`, `csvReading?`, `features?`, `definedNames?`, `tableNames?`, `fileSummary?`), `sheets[]` (`fileId`, `sourceSheetId`, `sourceName`, `proposedName`), `errors[]`.
- **Mới**: mỗi file có `fileSummary` cho UI hiển thị trước khi nhập: `{"columnCount": 8, "kinds": {"number": 5, "date": 2, "text": 1}, "encoding": "utf-8", "delimiter": ",", "headerRow": 1}`. Đây là *thống kê*, không phải preview giá trị.

## 3. `packages` — dựng frame đã định kiểu

**Request** bổ sung `dateSystem`:

```json
{"action": "packages", "preparationId": "prep_…", "reviewHash": "sha256:…", "dateSystem": "1900"}
```

- `dateSystem` ∈ `{"1900","1904"}`, bắt buộc khi có ít nhất một CSV có cột ngày. Client luôn gửi (probe `workbook.functions.date(1904,1,1)`: `0` → 1904, `1462` → 1900). Thiếu/không hợp lệ khi cần → `DP_DATE_SYSTEM_REQUIRED`. Khi lần nhập không có cột ngày, thiếu `dateSystem` được mặc định `"1900"` để các đường gọi cũ (ví dụ `direct.py`) không gãy.

**Response** thêm `importReport` (một lần cho cả lần nhập):

```json
{
  "importReport": {
    "totals": {"files": 8, "sheets": 8, "skipped": 0, "decisions": 12},
    "files": [
      {
        "fileId": "file_…",
        "fileName": "dim_products.csv",
        "status": "imported",
        "reading": {"encoding": "utf-8", "delimiter": ",", "headerRow": 1, "columns": 8},
        "sheets": [{"sourceSheetId": "sheet_…", "targetName": "dim_products"}],
        "decisions": [
          {"column": "unit_price", "columnIndex": 3, "kind": "number", "numberFormat": "General",
           "reasonCode": "DECIMAL_DOT", "affectedRows": 1480, "samples": ["1234.56", "0.99"]}
        ],
        "issues": []
      },
      {
        "fileId": "file_…", "fileName": "broken.csv", "status": "skipped",
        "reading": {"encoding": "utf-8", "delimiter": ",", "headerRow": 1, "columns": 4},
        "sheets": [], "decisions": [],
        "issues": [{"code": "CSV_COLUMN_COUNT", "message": "3 dòng lệch số cột — chưa nhập"}]
      }
    ]
  },
  "packages": [{"fileId": "…", "base64": "…", "sheets": [{"sourceSheetId": "…", "targetName": "…", "values": [[…]], "formulas": [[…]], "formulaCells": [], "numberFormats": [["General", …]]}]}]
}
```

Luật frame CSV:

| Loại cột | Giá trị trong `values` | `numberFormats` | Ghi chú |
|---|---|---|---|
| number | JS number (int nếu nguyên) | `"General"` | không bao giờ là chuỗi |
| date | serial số theo `dateSystem` | `"yyyy-mm-dd"` | 1900: gốc 1899-12-31 (trước 1900-03-01) / 1899-12-30; 1904: gốc 1904-01-01 |
| text / identifier / formula-like / header / empty | string | `"@"` | giữ nguyên sau trim |

- `formulas` = bản sao `values` (CSV không có công thức); `formulaCells` rỗng.
- Tổng ô ≤ `MAX_CELLS` hiện có; nếu vượt, file thành `skipped` với `REQUEST_LIMIT`, không cắt bớt.
- `decisions` ≤ 200/file; `samples` ≤ 2 phần tử, mỗi phần tử ≤ 40 ký tự, không chứa PII log.
- Report chỉ chứa metadata; không chứa giá trị ô ngoài `samples`.

## 4. `reasonCode` (đóng)

`DECIMAL_DOT`, `DECIMAL_COMMA`, `GROUP_SEPARATOR`, `DATE_ORDER_DETECTED`, `DATE_DMY_DEFAULT`, `INVALID_DATE_TEXT`, `DATE_UNSUPPORTED_TEXT`, `LEADING_ZERO_TEXT`, `MIXED_TYPE_TEXT`, `PRECISION_TEXT`, `FORMULA_LIKE_TEXT`, `EMPTY_COLUMN`, `ENCODING_FALLBACK`, `DELIMITER_INFERRED`.

Nhãn hiển thị (UI dùng đúng chuỗi này):

| reasonCode | Nhãn |
|---|---|
| `DECIMAL_DOT` | `số · dấu chấm thập phân` |
| `DECIMAL_COMMA` | `số · dấu phẩy thập phân` |
| `GROUP_SEPARATOR` | `số · dấu phân cách nghìn` |
| `DATE_ORDER_DETECTED` | `ngày · thứ tự tự nhận` |
| `DATE_DMY_DEFAULT` | `ngày · mặc định ngày/tháng/năm` |
| `INVALID_DATE_TEXT` | `ngày không hợp lệ · giữ chữ` |
| `DATE_UNSUPPORTED_TEXT` | `ngày chưa hỗ trợ · giữ chữ` |
| `LEADING_ZERO_TEXT` | `mã có số 0 đầu · giữ chữ` |
| `MIXED_TYPE_TEXT` | `cột trộn kiểu · giữ chữ` |
| `PRECISION_TEXT` | `số vượt độ chính xác · giữ chữ` |
| `FORMULA_LIKE_TEXT` | `giống công thức · giữ chữ` |
| `EMPTY_COLUMN` | `cột rỗng` |
| `ENCODING_FALLBACK` | `đã tự chọn bảng mã` |
| `DELIMITER_INFERRED` | `đã tự chọn dấu phân cách` |

## 5. Bất biến

- Không đọc file ngoài `items`; không ghi file nguồn (chỉ `_unchanged` xác nhận).
- Không thêm route ghi mới; import vẫn đi qua approval/permit/read-back hiện có.
- Không log raw cell/value/path; report là metadata do server trả, không ghi xuống log.
