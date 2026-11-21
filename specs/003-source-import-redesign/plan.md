# Implementation plan — một tab Nguồn, nhập file thành sheet đúng kiểu

**Spec**: [spec.md](spec.md). **Contract**: [contracts/source-import.md](contracts/source-import.md). **Data**: [data-model.md](data-model.md).
**Goal**: thay hai bước `Nguồn` + `Làm sạch` bằng một tab `Nguồn` có browser cây thư mục, nhập CSV thành sheet đúng kiểu dữ liệu (number/date/text), tự quyết định dạng và báo cáo ngoại lệ; bỏ preview và bỏ mọi câu hỏi định dạng.
**Ngày**: 2026-11-18. **Branch**: `main` (không reset/stash). **Không** đổi release metadata khi chỉ có plan.

## 1. Global constraints

- Python 3.13 stdlib; JS thuần cho task pane; không thêm dependency runtime.
- File nguồn read-only; chỉ đọc khi người dùng bấm nhập; mọi text render bằng `textContent`.
- Không gửi dữ liệu/đường dẫn sang AI/cloud; không log raw cell/binary/private path.
- Giữ nguyên cổng: `_guard`/`_unchanged`, approval/permit/read-back, caps 64 MiB/file, 100k dòng, 200 cột, 400k ô, 8 MiB session.
- Giữ 12 script taskpane hiện có trong gate; thêm script mới vào `tests/taskpane/test_taskpane_js.py`.
- Không xoá backend `cleaning.py`/`mutation.py`/`store.preview`; chỉ bỏ mount trong UI (xem spec §9).
- Typed/Problem Chain/Advanced không bị đụng tới.

## 2. Kiến trúc thay đổi

```
Trợ lý (tab)
└── assistant_entry.js  ── journey 2 bước, không còn step "clean"
    ├── assistant_browser.js (mới)  ── breadcrumb/tree/selection/report UI
    ├── preparation_bridge.js        ── browse(), inventorySelection(), importSelection()
    └── preparation_runtime.js       ── probeDateSystem(), importReviewedSources() (ghi frame đã định kiểu)

Python
├── sources/preparation/inventory.py   ── browse_folder(), inventory_selection()
├── sources/preparation/csv_typing.py  ── (mới) suy luận kiểu + dựng TypedSheetFrame + decisions
├── sources/preparation/packages.py    ── CSV branch dùng csv_typing (thay `[["@"]]`)
├── coordinator/endpoints/preparation.py ── action `browse`, `inventory` mới, `packages` + dateSystem
└── schemas/preparation.schema.json    ── contract mới (closed)
```

**Vì sao không đẩy typed conversion sang JS**: bảng luật §6 phải test được bằng oracle Python độc lập, tất định, chạy offline; JS chỉ ghi `values` + `numberFormats` đã tính.

**Vì sao date system phải do client gửi**: serial ngày phụ thuộc workbook; probe 1900/1904 chỉ có qua Office.js (`workbook.functions.date(1904,1,1)`), server không biết. Client probe một lần khi kết nối và gửi kèm `packages`.

## 3. Quyết định thiết kế (đã cân nhắc)

| # | Quyết định | Thay thế bị loại |
|---|---|---|
| K1 | Suy luận kiểu ở server, ghi ở client | Suy luận trong JS (khó oracle, khó test offline) |
| K2 | Parse 100% giá trị mới đổi kiểu cột | Ép từng ô rời (làm cột nửa số nửa chữ, không sort/lọc được) |
| K3 | Mơ hồ → chọn theo luật + ghi ngoại lệ | Hỏi từng cột (đúng điều người dùng muốn bỏ) |
| K4 | Ngày mặc định DMY (vi-VN) khi mơ hồ | Đoán MDY (sai với dữ liệu VN) |
| K5 | `numberFormat` cố định: number `General`, date `yyyy-mm-dd`, text `@` | Đoán format hiển thị (không tất định, khó assert) |
| K6 | Browser chỉ `stat`, đọc nội dung khi bấm nhập | Inventory cả thư mục mỗi lần điều hướng (chậm, đọc file không cần) |
| K7 | Selection theo `(relativePath, fileName)`, giữ qua điều hướng | Chỉ 1 thư mục 1 lần (không đúng yêu cầu) |
| K8 | Import report trả trong `packages` | Thêm endpoint mới (tăng bề mặt auth) |

## 4. Cấu trúc file

| Đường dẫn | Trách nhiệm | Task |
|---|---|---|
| `pbip_assistant/sources/preparation/csv_typing.py` | Luật kiểu, frame, decisions | T302 |
| `pbip_assistant/sources/preparation/inventory.py` | `browse_folder`, `inventory_selection`, `FileSummary` | T303 |
| `pbip_assistant/sources/preparation/packages.py` | Nối typed frame + report | T304 |
| `pbip_assistant/sources/preparation/mutation.py` | `packages()` nhận `date_system` | T304 |
| `pbip_assistant/sources/preparation/store.py` | `browse`, `inventory(items)`, `packages(dateSystem)` | T303/T304 |
| `pbip_assistant/coordinator/endpoints/preparation.py` | route `browse`, body mới | T303 |
| `pbip_assistant/schemas/preparation.schema.json`, `wire.py` | contract đóng | T301 |
| `pbip_assistant/excel_addin/assistant_browser.js` (mới) | UI browser + report | T305 |
| `pbip_assistant/excel_addin/assistant_entry.js` | journey 2 bước, wiring | T305/T306 |
| `pbip_assistant/excel_addin/preparation_bridge.js` | `browse`, `inventory(items)`, `import(dateSystem)` | T305 |
| `pbip_assistant/excel_addin/preparation_runtime.js` | `probeDateSystem`, ghi frame | T305 |
| `pbip_assistant/excel_addin/taskpane.{html,css}` | markup/style browser, bỏ wizard | T305/T306 |
| `tests/support/csv_typing_oracle.py` | oracle độc lập | T302 |
| `tests/unit/test_csv_typing.py` | luật §6 | T302 |
| `tests/unit/test_preparation_browse.py` | browse/inventory | T303 |
| `tests/unit/test_preparation_packages.py`, `tests/integration/test_preparation_api.py` | packages + report | T304 |
| `tests/taskpane/taskpane_assistant_browser.js` | UI browser/report | T305 |
| `tests/taskpane/taskpane_assistant_journey.js` | journey 2 bước, không preview | T306 |
| `docs/current/{TASKPANE_UI,SPEC}.md`, `specs/003-source-import-redesign/acceptance.md` | owner docs + evidence | T301/T307 |

## 5. Constitution check

- Đúng module canonical: `sources/preparation`, `coordinator/endpoints`, `excel_addin` — không tạo package mới.
- Source read-only, local-only, bounded — giữ.
- Không mở Typed/Advanced, không đổi baseline 001 hay release metadata.
- Thay đổi hành vi người dùng (bỏ bước Làm sạch, bỏ câu hỏi) đã được người dùng duyệt ngày 2026-11-18 và ghi vào spec §2; owner docs phải cập nhật cùng task T301/T307.
- **Ngoại lệ cần ghi nhận**: FR-023 yêu cầu hỏi khi CSV mơ hồ. Với đường *nhập sheet Excel*, spec 003 thay bằng "hiển thị metadata đọc + tự quyết + ngoại lệ"; đường *lập patch PBIP* vẫn giữ nguyên câu hỏi. T301 phải thêm ghi chú phạm vi vào `docs/current/SPEC.md` trước khi code UI.

## 6. Batches

| Wave | Task | Nội dung | Phụ thuộc |
|---|---|---|---|
| 1 | T301 | Contract + owner docs + schema | — |
| 2 (song song) | T302 | `csv_typing` + oracle | T301 |
| 2 (song song) | T305 | UI browser + report + bridge + probe | T301 |
| 3 | T303 | browse + inventory selection + endpoint | T302 (dùng `describe_columns`) |
| 4 | T304 | packages typed frame + report | T303 |
| 5 | T306 | Bỏ bước Làm sạch, journey 2 bước, vệ sinh DOM/wiring | T304, T305 |
| 6 | T307 | Regression, acceptance matrix, owner docs lần cuối | T306 |
| 7 | T308 | Live synthetic (Not run/Blocked nếu thiếu Excel) | T307 |

Không task nào chạm cùng file với task khác trong cùng wave (kiểm ở cột "Files" trong tasks.md).

## 7. Rủi ro và cách chặn

| Rủi ro | Ảnh hưởng | Cách chặn |
|---|---|---|
| Luật đoán dấu thập phân sai với dữ liệu thật | số bị hiểu sai 1000× | Cột mơ hồ được liệt kê; thêm test với fixture thật ẩn danh ở T302; người dùng xem report |
| `values` number làm mất số 0 đầu | mã SKU hỏng | Luật identifier thắng luật number; test `00123` |
| Ngày DMY/MDY lệch | sai ngày | ưu tiên bằng chứng >12; mặc định DMY; ghi report; test cả 3 thứ tự |
| Serial ngày sai hệ | lệch 1462 ngày | `dateSystem` bắt buộc, test cả 1900/1904 |
| Ghi text `@` lên số | quay lại lỗi cũ | assert `typeof value === "number"` + `numberFormat === "General"` |
| Bỏ bước Làm sạch làm hỏng binding Đề bài | không phân tích được | `scan()` vẫn chạy ngầm sau nhập/chọn workbook (T306), test journey |
| Nhiều agent sửa cùng file | conflict | phân quyền file theo bảng §4, T305/T306 cùng một agent |

## 8. Execution handoff

- Mỗi task chạy TDD: viết test đỏ → chạy thấy đỏ đúng lý do → implement tối thiểu → xanh → commit chỉ file thuộc task.
- Agent chỉ sửa file trong cột "Files" của task mình; cần đổi file khác thì dừng và báo.
- Không chạy `git reset/stash/checkout` toàn repo; không commit file rác `.artifacts`.
- Báo cáo cuối task theo mẫu ở tasks.md §"Định dạng báo cáo".
