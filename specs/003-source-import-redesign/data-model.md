# Data model — feature 003

Không tạo document type mới cho persistence; các cấu trúc dưới đây là DTO trong request/response của preparation (không lưu xuống đĩa, không vào Custom XML).

| Entity | Fields | Owner |
|---|---|---|
| `BrowseRequest` | preparationId, expectedClaimVersion, root, relativePath | coordinator endpoint |
| `BrowseEntry` | name, kind (`folder`/`file`), extension?, size?, modified? | `sources/preparation/inventory.py` |
| `BrowseResult` | rootName, relativePath, breadcrumb[], parentRelativePath?, entries[], truncated | inventory |
| `SelectionItem` | relativePath, fileName | UI → `store.inventory` |
| `SourceInventory` (đã có) | inventoryHash, root, folder, files[], sheets[], errors[], stamps, totalBytes | store |
| `FileSummary` | columnCount, kinds{number,date,text}, encoding, delimiter, headerRow | inventory (thêm vào mỗi file) |
| `ColumnDecision` | column, columnIndex, kind (`number`/`date`/`text`), numberFormat, reasonCode, affectedRows, samples[≤2] | `csv_typing.py` |
| `FileImportReport` | fileId, fileName, status (`imported`/`skipped`), reading, sheets[], decisions[], issues[] | `packages.py` |
| `ImportReport` | totals{files,sheets,skipped,decisions}, files[] | `packages.py` |
| `TypedSheetFrame` | values[][], formulas[][], formulaCells[][], numberFormats[][] | `csv_typing.py` → `packages.py` |
| `DateProbe` | dateSystem (`1900`/`1904`) | `excel_addin/preparation_runtime.js` |

## Quan hệ

```
BrowseResult.entries ──(tick)──> SelectionItem
SelectionItem[] ──(inventory)──> SourceInventory.files/sheets
SourceInventory ──(review-import)──> reviewHash
reviewHash + dateSystem ──(packages)──> TypedSheetFrame[] + ImportReport
TypedSheetFrame[] ──(runtime write)──> sheet mới trong workbook + receipt
```

## Vòng đời (UI)

```
idle → browsing → selected → importing → reported → ready
                         ↘ skipped_file (per file, không rời trạng thái)
importing → partial_unknown (chỉ khi write/read-back thất bại giữa lúc ghi)
```

- `browsing`: chưa tick gì, nút `Nhập vào workbook` tắt.
- `selected`: ≥ 1 file hợp lệ; footer đếm `N file · M sheet dự kiến`.
- `importing`: khoá toàn bộ điều khiển; tiến độ theo file.
- `reported`: hiện tổng + mapping + ngoại lệ + file bỏ qua; `Tiếp tục: Đề bài` bật nếu ≥ 1 sheet verified.
- `partial_unknown`: khoá nhập, hiện "không nhập lại tự động", yêu cầu kiểm tra workbook (giữ hành vi 002).

## Ràng buộc

- `SourceInventory.files[]` chỉ chứa file đã tick; `stamps` dùng cho `verify_inventory` như hiện tại.
- `ImportReport` không chứa đường dẫn tuyệt đối; `samples` ≤ 2 × 40 ký tự.
- `dateSystem` không lưu vào inventory; chỉ truyền vào `packages` để tính serial.
- Mọi trường mới phải khai báo trong `pbip_assistant/schemas/preparation.schema.json` và `wire.py` sẽ từ chối key lạ.
