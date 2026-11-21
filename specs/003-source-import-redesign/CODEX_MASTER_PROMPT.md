# CODEX MASTER PROMPT — feature 003 (một tab Nguồn)

Tài liệu **tự chứa**: dán toàn bộ cho Codex một lần, Codex tự chia subagent theo §7. Các file canonical vẫn là nguồn sự thật cuối cùng; khi mâu thuẫn, file canonical thắng.

| File canonical | Dùng khi |
|---|---|
| [spec.md](spec.md) | hành vi, yêu cầu SI01–SI15, success criteria |
| [contracts/source-import.md](contracts/source-import.md) | shape request/response, reasonCode |
| [plan.md](plan.md) | kiến trúc, quyết định K1–K8, rủi ro |
| [tasks.md](tasks.md) | task list, test bắt buộc, lệnh kiểm chứng |
| [CODEX_HANDOFF.md](CODEX_HANDOFF.md) | quy trình 5 bước + 4 lớp QC |
| [data-model.md](data-model.md) | DTO, vòng đời UI |
| `AGENTS.md` | luật dự án bắt buộc |

---

## §0. Cách dùng

1. Dán từ §1 đến hết §12 cho Codex (một phiên orchestrator).
2. Codex đọc §6, chia subagent theo §7, mỗi subagent nhận **một** task.
3. Sau mỗi sóng, Codex tự chạy cổng ở §7 (không tin báo cáo subagent).
4. Dừng và báo nếu gặp điều kiện ở §10.

---

## §1. Bối cảnh & nhiệm vụ

Repo `C:\Users\COLAIG\Downloads\power_bi` — Excel add-in "Reqwise", Python 3.13 stdlib + Office.js task pane, không thêm dependency.

Feature 003 (đang dở): gộp hai bước `1. Nguồn` + `2. Làm sạch` thành **một tab `Nguồn`**; người dùng duyệt cây thư mục, tick file, nhập CSV thành sheet **đúng kiểu dữ liệu** (number/date/text), hệ thống **tự quyết định dạng** và liệt kê **ngoại lệ đã tự xử lý**; bỏ preview và bỏ mọi câu hỏi định dạng.

Trạng thái hiện tại: T302 đã xong (`csv_typing.py` + 19 test). Đường nhập **vẫn ghi text** vì `packages.py` chưa nối `csv_typing`. Task pane vẫn 3 bước. Live Excel `Not run`.

---

## §2. Luật cứng

1. **Một task = một subagent = một lượt.** Subagent chỉ sửa file trong mục `Files` của task.
2. TDD: viết test đỏ trước (đỏ đúng lý do), rồi implement tối thiểu, rồi xanh.
3. Không skip/xfail, không `except: pass`, không `assert True`, không TODO để lại.
4. Không đổi `pyproject`/manifest/release version; không thêm dependency; không `git reset/stash/checkout .`.
5. Không xoá backend cũ: `sources/preparation/{cleaning,mutation,journal}.py`, `store.preview/answer`. Chỉ bỏ mount UI.
6. Không log raw cell, đường dẫn cá nhân, token, binary. UI render bằng `textContent`.
7. Không sửa `spec.md`/`tasks.md` cho khớp code. Mâu thuẫn → dừng, báo (§10).
8. Mỗi subagent báo cáo: `Task / Status / Tests (lệnh + output thật) / Files / Deviations / Open`.

---

## §3. Hành vi sản phẩm (đích cuối)

**Journey**: `1. Nguồn` → `2. Đề bài`. Không còn bước/tab `Làm sạch`.

**Tab Nguồn**
1. Hai nút: `Chọn thư mục` (primary) và `Dùng dữ liệu trong workbook` (ghost).
2. Chọn thư mục mở **dialog native một lần**; sau đó panel tự duyệt: breadcrumb, `↑ Lên cấp trên`, danh sách thư mục con + file `.csv`/`.xlsx`, tick từng file, `Chọn tất cả thư mục này`.
3. Footer: `Đã chọn N file · M sheet sẽ được tạo` + `Nhập vào workbook`.
4. Nhập: mỗi CSV → 1 sheet; mỗi XLSX → cả nhóm sheet như hiện tại. Không đè sheet có sẵn.
5. Sau nhập: `Đã nhập N file → M sheet`, khối `Ngoại lệ đã tự xử lý (k)`, khối `Bỏ qua (j)` kèm lý do.
6. `Tiếp tục: Đề bài` bật khi có ≥1 sheet verified (hoặc workbook có dữ liệu hợp lệ).
7. Nhánh workbook: **không sửa một ô nào**; chỉ validate header + đọc lại nguồn.

**Bị bỏ khỏi UI**: preview dữ liệu, preview làm sạch, câu hỏi `Giữ dạng chữ / Dấu chấm thập phân / Dấu phẩy thập phân / DMY-MDY-YMD`, select `Hệ ngày của workbook`.

---

## §4. Luật kiểu (bắt buộc, tất định)

Xét từng cột sau khi trim; chỉ ô không rỗng.

1. **Formula-like** (`=`, `+`, `@`, hoặc `-` không phải số) → text `@`, reason `FORMULA_LIKE_TEXT`.
2. **Identifier** (`^0\d+$`) → text `@`, `LEADING_ZERO_TEXT`. Luật này **thắng** luật số.
3. **Number** (100% giá trị không rỗng parse được theo một cách):
   - dot: `^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$`
   - comma: `^[+-]?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$`
   - Nếu mọi giá trị đều là nhóm 3 chữ số và có ít nhất một dấu phân cách → hiểu là phân cách nghìn → `GROUP_SEPARATOR`; ngược lại theo dấu tương ứng (`DECIMAL_DOT`/`DECIMAL_COMMA`).
   - >15 chữ số có nghĩa, hoặc `0 < |x| < 2.2250738585072014e-308` → text `@`, `PRECISION_TEXT`.
4. **Date** (100% khớp `^(\d{1,4})[/.-](\d{1,2})[/.-](\d{1,4})$`, là ngày hợp lệ):
   - token đầu 4 chữ số → `YMD`; có token đầu >12 → `DMY`; có token thứ hai >12 → `MDY`; còn lại → `DMY` mặc định, `DATE_DMY_DEFAULT`.
   - Trộn >12 ở cả hai vị trí / ngày không tồn tại → text `@`, `INVALID_DATE_TEXT`; năm 2 chữ số → `DATE_UNSUPPORTED_TEXT`.
   - Ghi serial theo hệ ngày workbook, numberFormat `yyyy-mm-dd`:
     1900: gốc `1899-12-30`, trừ ngày < `1900-03-01` dùng gốc `1899-12-31`; 1904: gốc `1904-01-01`.
5. **Text**: mặc định, `@`.
6. **Empty**: giữ `""`, `@`; cột toàn rỗng → `EMPTY_COLUMN`.
7. **Header row**: luôn text `@`, không suy luận.

**numberFormat**: number → `General`; date → `yyyy-mm-dd`; còn lại → `@`.

**Delimiter thắng dấu thập phân** (đã chốt 2026-11-19): tách ô trước, suy luận kiểu sau.

| Header | Dòng | Kết quả |
|---|---|---|
| `Code;Price` | `A01;00123,2` | `Code` text `A01`; `Price` number `123.2` |
| `Code,Qty` | `00123,2` | `,` là delimiter → `Code` text `00123`, `Qty` number `2` |

**reasonCode (đóng)**: `DECIMAL_DOT`, `DECIMAL_COMMA`, `GROUP_SEPARATOR`, `DATE_ORDER_DETECTED`, `DATE_DMY_DEFAULT`, `INVALID_DATE_TEXT`, `DATE_UNSUPPORTED_TEXT`, `LEADING_ZERO_TEXT`, `MIXED_TYPE_TEXT`, `PRECISION_TEXT`, `FORMULA_LIKE_TEXT`, `EMPTY_COLUMN`, `ENCODING_FALLBACK`, `DELIMITER_INFERRED`.

**Nhãn UI**: `số · dấu chấm thập phân`, `số · dấu phẩy thập phân`, `số · dấu phân cách nghìn`, `ngày · thứ tự tự nhận`, `ngày · mặc định ngày/tháng/năm`, `ngày không hợp lệ · giữ chữ`, `ngày chưa hỗ trợ · giữ chữ`, `mã có số 0 đầu · giữ chữ`, `cột trộn kiểu · giữ chữ`, `số vượt độ chính xác · giữ chữ`, `giống công thức · giữ chữ`, `cột rỗng`, `đã tự chọn bảng mã`, `đã tự chọn dấu phân cách`.

**importReport** (chỉ metadata, không raw row/không path tuyệt đối):

```json
{"totals": {"files": 3, "sheets": 3, "skipped": 0, "decisions": 4},
 "files": [{"fileId": "file_…", "fileName": "dim_products.csv", "status": "imported",
            "reading": {"encoding": "utf-8", "delimiter": ",", "headerRow": 1, "columns": 8},
            "sheets": [{"sourceSheetId": "sheet_…", "targetName": "dim_products"}],
            "decisions": [{"column": "unit_price", "columnIndex": 3, "kind": "number",
                           "numberFormat": "General", "reasonCode": "DECIMAL_DOT",
                           "affectedRows": 1480, "samples": ["1234.56", "0.99"]}],
            "issues": []}]}
```

Giới hạn: ≤200 decisions/file; `samples` ≤2 phần tử, mỗi phần tử ≤40 ký tự; file lỗi → `status: "skipped"` + `issues[{code,message}]`, không tạo package.

**browse response** (không đọc nội dung file, không trả path tuyệt đối):

```json
{"rootName": "dataset", "relativePath": "sales/2026",
 "breadcrumb": [{"name": "dataset", "relativePath": ""}, {"name": "sales", "relativePath": "sales"}],
 "parentRelativePath": "sales",
 "entries": [{"name": "archive", "kind": "folder"},
             {"name": "orders.xlsx", "kind": "file", "extension": "xlsx", "size": 20480, "modified": "2026-11-18T08:00:00+07:00"}],
 "truncated": false}
```

**inventory request**: `{root, items:[{relativePath, fileName}]}`, 1..200; chỉ đọc đúng các file này; lỗi từng file vào `errors[]`; mỗi file có thêm `fileSummary {columnCount, kinds{number,date,text}, encoding, delimiter, headerRow}`.

**Giữ nguyên cổng chặn**: ragged rows (mỗi file bị skip riêng, không chặn file khác), 64 MiB/file, 100.000 dòng, 200 cột, 400.000 ô, đường dẫn thoát root, source đổi giữa review và write.

---

## §5. Kiến trúc & quyết định

```
assistant_entry.js ── journey 2 bước
  ├── assistant_browser.js (mới)  breadcrumb/tree/selection/report
  ├── preparation_bridge.js        browse(), inventorySelection(), importSelection()
  └── preparation_runtime.js       probeDateSystem(), ghi frame đã định kiểu

Python
  sources/preparation/inventory.py   browse_folder(), inventory_selection(), fileSummary
  sources/preparation/csv_typing.py  ✅ đã có
  sources/preparation/packages.py    CSV branch dùng csv_typing
  coordinator/endpoints/preparation.py  action browse, inventory(items), packages+dateSystem
  schemas/preparation.schema.json    contract đóng
```

| # | Quyết định | Lý do |
|---|---|---|
| K1 | Suy luận kiểu ở Python, ghi ở JS | test được bằng oracle độc lập, tất định |
| K2 | 100% giá trị mới đổi kiểu cột | không ép nửa vời, không làm mất dữ liệu |
| K3 | Mơ hồ → chọn theo luật + ghi ngoại lệ | đúng yêu cầu người dùng, không hỏi từng cột |
| K4 | Ngày mơ hồ mặc định DMY (vi-VN) | dữ liệu người dùng là VN |
| K5 | `dateSystem` do client gửi (probe `DATE(1904,1,1)`) | server không biết workbook; thiếu khi có cột ngày → `DP_DATE_SYSTEM_REQUIRED`; không có cột ngày → mặc định `"1900"` để `direct.py` không gãy |
| K6 | Browser chỉ `stat`, đọc nội dung khi bấm nhập | nhanh, không đọc file không cần |
| K7 | Selection theo `(relativePath, fileName)`, giữ qua điều hướng | nhiều thư mục trong một lượt |
| K8 | Report trả trong `packages`, không thêm endpoint | giảm bề mặt auth |

---

## §6. Task

> T302 **đã xong** — chỉ đọc `csv_typing.py` để hiểu API, không làm lại.

### T301 — contract đóng + owner docs

**Files**: `pbip_assistant/schemas/preparation.schema.json`, `pbip_assistant/sources/preparation/wire.py` (nếu cần), `tests/contracts/test_source_import_contracts.py`, `tests/contracts/test_preparation_contracts.py`, `docs/current/TASKPANE_UI.md`, `docs/current/SPEC.md`.

**Làm**
1. action `browse`: `{preparationId, expectedClaimVersion, root, relativePath}`.
2. action `inventory`: `{root, items:[{relativePath, fileName}]}` (1..200).
3. action `packages`: thêm `dateSystem` enum `["1900","1904"]`.
4. Từ chối key lạ, action lạ, path tuyệt đối/`..`.
5. `TASKPANE_UI.md`: journey 2 bước, browser, report; ghi rõ bỏ preview/câu hỏi/hệ ngày; nhánh workbook không đổi dữ liệu.
6. `SPEC.md`: 3–5 dòng ghi phạm vi "nhập sheet CSV trong task pane tự quyết định dạng + báo ngoại lệ; FR-023 vẫn áp cho đường lập patch PBIP".

**Test**: `test_browse_rejects_extra_keys`, `test_inventory_requires_items_within_limit`, `test_inventory_rejects_absolute_or_parent_path`, `test_packages_rejects_unknown_date_system`, `test_legacy_actions_unchanged`.

**Cổng**: `py -m unittest tests.contracts.test_source_import_contracts tests.contracts.test_preparation_contracts tests.contracts.test_coordinator_dispatch -v`

### T302 — ✅ xong (không làm)

**Files** (đã tồn tại, chỉ đọc): `pbip_assistant/sources/preparation/csv_typing.py`, `tests/support/csv_typing_oracle.py`, `tests/unit/test_csv_typing.py`.

### T303 — browse + inventory theo lựa chọn

**Files**: `pbip_assistant/sources/preparation/inventory.py`, `pbip_assistant/sources/preparation/store.py`, `pbip_assistant/coordinator/endpoints/preparation.py`, `tests/unit/test_preparation_browse.py`, `tests/unit/test_preparation_inventory.py`.

**Làm**
1. `browse_folder(root, relative_path)` → `{rootName, relativePath, breadcrumb[], parentRelativePath, entries[], truncated}`; chỉ folder + `.csv`/`.xlsx`; folder trước, sau đó `name.casefold()`; tối đa 500 + `truncated`; chặn `..`/absolute/reparse; **không đọc nội dung file**.
2. `inventory_selection(root, items)` → đọc đúng các cặp đã tick; giữ `_guard/_bounded_bytes/_unchanged/verify_inventory`; lỗi từng file vào `errors[]`; thêm `fileSummary` bằng `csv_typing.describe_columns` (**không** viết bảng map kiểu thứ hai).
3. `store.browse`, `store.inventory(..., items)`, endpoint action `browse`; giữ `expectedClaimVersion`.

**Test**: 9 case — browse sort/skip/hidden/escape/truncate/empty; inventory chỉ đọc file tick; lỗi từng file không hỏng lô; trùng item/quá 200; phát hiện source change.

**Cổng**: `py -m unittest tests.unit.test_preparation_browse tests.unit.test_preparation_inventory -v` + contract tests.

### T304 — typed CSV frame + import report

**Files**: `pbip_assistant/sources/preparation/packages.py`, `pbip_assistant/sources/preparation/mutation.py` (**chỉ** method `packages`), `pbip_assistant/sources/preparation/store.py`, `tests/unit/test_preparation_packages.py`, `tests/integration/test_preparation_api.py`, `tests/integration/test_preparation_direct.py` (duyệt 2026-11-19: payload `inventory` theo `items[]` + kỳ vọng kiểu ô).

**Làm**
1. CSV branch: `csv.reader` → `csv_typing.build_typed_frame(headers, rows, date_system=...)` → `values/formulas/formulaCells/numberFormats`. Giữ guard cũ.
2. `importReport` đúng §4; file lỗi → `skipped` + `issues`, không có package.
3. `packages(..., date_system=None)`: thiếu khi có cột ngày → `DP_DATE_SYSTEM_REQUIRED`; không có cột ngày → `"1900"`.
4. XLSX branch **không đổi**.

**Test**: number `typeof`/`General`; serial 1900 & 1904; mã 0 đầu `@`; report có reasonCode; ragged skip nhưng file khác vẫn nhập; report không chứa path tuyệt đối/raw row; dateSystem bắt buộc; XLSX unchanged.

**Cổng**: `py -m unittest tests.unit.test_preparation_packages tests.integration.test_preparation_api -v`

### T305 — UI browser + report (phần 1)

**Files**: `pbip_assistant/excel_addin/assistant_browser.js` (mới), `pbip_assistant/excel_addin/assistant_entry.js` (chỉ điểm nối `onImported`), `pbip_assistant/excel_addin/preparation_bridge.js`, `pbip_assistant/excel_addin/preparation_runtime.js` (`probeDateSystem`), `pbip_assistant/excel_addin/taskpane.html`, `pbip_assistant/excel_addin/taskpane.css`, `tests/taskpane/taskpane_assistant_browser.js` (mới), `tests/taskpane/test_taskpane_js.py`.

**Markup/chuỗi bắt buộc**
- `#assistant-browser`: `#assistant-browser-path`, `#assistant-browser-up` (`↑ Lên cấp trên`), `#assistant-browser-list`, `#assistant-browser-status`.
- `#assistant-selected-summary` (`Đã chọn N file · M sheet sẽ được tạo`), `#assistant-import-selected` (`Nhập vào workbook`), `#assistant-select-all` (`Chọn tất cả thư mục này`).
- Dòng file khi tick: `8 cột · 5 số · 2 ngày · 1 chữ` (từ `fileSummary`, **không** hiện giá trị ô).
- Tiến độ: `Đang nhập 3/8: dim_products.csv…` (aria-live).
- `#assistant-import-summary` (`Đã nhập 8 file → 8 sheet`), `#assistant-import-exceptions` (`Ngoại lệ đã tự xử lý (12)`, mỗi dòng đúng dạng `dim_products.csv · unit_price: số · dấu chấm thập phân → Number · 1.480 ô`), `#assistant-import-skipped` (`Bỏ qua (1)` + lý do).
- Trạng thái rỗng: `Thư mục này không có file .csv hoặc .xlsx.`; huỷ: `Chưa chọn thư mục.`
- **Không được tồn tại** chuỗi/nút `Xem trước` trong tab Trợ lý.

**Test (node)**: 9 case — render folder/file + breadcrumb; đi vào/lên giữ selection; chọn tất cả theo thư mục; đếm đúng; post đúng items + dateSystem; render ngoại lệ/skipped; không có DOM preview/câu hỏi; chuỗi tiếng Việt; render bằng text.

**Cổng**: `node tests/taskpane/taskpane_assistant_browser.js` + `py -m unittest tests.taskpane.test_taskpane_js -v`

### T306 — bỏ bước Làm sạch, journey 2 bước (phần 2, cùng agent với T305)

**Files**: `pbip_assistant/excel_addin/assistant_entry.js`, `pbip_assistant/excel_addin/taskpane.html`, `pbip_assistant/excel_addin/taskpane.css`, `pbip_assistant/excel_addin/taskpane.js` (chỉ mount/gate), `tests/taskpane/taskpane_assistant_journey.js` (mới), `tests/taskpane/test_taskpane_js.py`, `tests/taskpane/taskpane_assistant_entry.js` (duyệt 2026-11-19: Đề bài chỉ bật sau khi đọc lại nguồn thành công), `tests/taskpane/taskpane_preparation_wizard.js` (chỉ bỏ assert DOM đã xoá, ghi lý do).

**Làm**
1. Xoá `#assistant-step-clean`; `#assistant-step-problem` = `2. Đề bài`; bỏ state `clean`.
2. Xoá `#preparation-wizard` (select hệ ngày, `#preparation-scan`, `#preparation-inventory`, `#preparation-panel`). Trong `taskpane.js` bỏ `showCleaning/applyCleanup/undo/redo/onApplied`, **giữ** `window.ReqwisePreparation.mount(...)` (bridge/`wizard.state`/`scanWorkbook` phụ thuộc).
3. Sau nhập/chọn workbook: `scan()` ngầm (`Đang đọc lại nguồn…`) → success `canProblem = true`; fail thì báo lỗi, `Đề bài` tắt.
4. `+ Thêm nguồn` mở lại browser.

**Test**: 6 case — journey 2 bước; không còn DOM wizard; sau nhập mới bật Đề bài; workbook không ghi ô; scan fail tắt Đề bài; add source quay lại browser.

**Cổng**: `node tests/taskpane/taskpane_assistant_journey.js && node tests/taskpane/taskpane_assistant_entry.js && node tests/taskpane/taskpane_preparation_wizard.js` + `py -m unittest tests.taskpane.test_taskpane_js -v`

### T307 — tích hợp + acceptance

**Files**: `specs/003-source-import-redesign/acceptance.md` (mới), `docs/current/TASKPANE_UI.md`, `docs/current/CURRENT_STATUS.md`, `tests/required_cases.json` (chỉ thêm).

**Làm**: bảng S01–S13 / SI01–SI15 / SC01–SC08 ↔ test/evidence, trạng thái `Pass/Fail/Blocked/Not run`; chạy `py tools/run_checks.py fast`, `runtime`, `py -m unittest discover -s tests -v`; ghi CURRENT_STATUS: automated pass, live `Not run`, không bump version.

### T308 — live synthetic

**Files**: `specs/003-source-import-redesign/acceptance.md`, `tests/live/README.md` (chỉ khi thêm scenario).

Có Excel + harness: fixture CSV (số/ngày/mã 0 đầu + 1 file lỗi), chạy browse 2 cấp → tick → nhập → đọc lại `numberFormat` + `typeof` từ Excel thật. Không có: ghi `Not run` + lý do. Không dùng workbook của người dùng.

---

## §7. Sóng & điều phối

```
Wave A  T301                        (1 agent)
Wave B  T303                        (1 agent)   ← sau A
Wave C  T304                        (1 agent)   ← sau B (cùng store.py)
Wave D  T305                        (1 agent UI) ← sau C
Wave E  T306                        (cùng agent D, tiếp luôn)
Wave F  T307                        (1 agent)   ← sau E
Wave G  T308                        (1 agent)   ← sau F
```

Không mở sóng sau khi sóng trước chưa qua cổng. Nếu muốn tăng tốc: T301 và T305 **không** chạy song song được vì T305 cần contract `browse` đã chốt — nhưng có thể bắt đầu T305 bằng cách đọc `contracts/source-import.md` (đã có sẵn) và chỉ test với fake bridge.

**Sau mỗi sóng, orchestrator tự kiểm** (không tin báo cáo):

```powershell
py tools/review_003.py --task T304        # allowlist + red flags (so với baseline)
py -m unittest ...                        # chạy lại đúng lệnh cổng
git status --short
git diff -- <file>                        # đọc diff, không chỉ xem số dòng
```

`py tools/review_003.py --snapshot` chụp mốc trước khi giao mỗi sóng.

---

## §8. Mẫu prompt cho subagent (orchestrator tự điền)

```text
Repo: C:\Users\COLAIG\Downloads\power_bi.

Bạn làm task <T3xx> của feature 003. Đọc theo thứ tự:
specs/003-source-import-redesign/{spec.md, contracts/source-import.md, tasks.md → <T3xx>}, AGENTS.md.

Luật: chỉ sửa file trong mục **Files**; TDD; không skip/assert rỗng/TODO; không thêm dependency;
không đổi version/manifest; không xoá backend cũ; mâu thuẫn spec → DỪNG và báo.

Làm đúng mục "Việc phải làm" của task. Xong: chạy đúng lệnh **Kiểm chứng** và báo:
Task / Status / Tests (lệnh + output thật) / Files / Deviations / Open.
```

**Reviewer (agent thứ hai, cấm sửa file):**

```text
Bạn là reviewer độc lập cho task <T3xx>. KHÔNG sửa file.

Đọc spec §6, tasks.md <T3xx>, contracts/source-import.md và `git diff` của các file trong allowlist.

Trả lời 6 câu, mỗi câu kèm file:dòng:
1. Hành vi nào trong spec/task mà code KHÔNG làm?
2. Có test nào pass dù code sai (test tự chứng minh)?
3. Case biên nào trong spec §6/Edge Cases chưa được test?
4. Chỗ nào nới lỏng cổng an toàn (skip, except rỗng, ghi ngoài allowlist, log dữ liệu thô)?
5. Thay đổi nào ngoài phạm vi task?
6. Nếu phải bác bỏ, lý do duy nhất là gì?

Kết luận: ACCEPT | REJECT + 3 việc phải sửa, xếp theo mức nghiêm trọng.
```

---

## §9. Bằng chứng

Mỗi task xong phải có một dòng trong `acceptance.md`:

| Task | Status | Command | Output (tóm tắt thật) | Revision |
|---|---|---|---|---|

Không có output = chưa xong. Không ghi `Passed` cho live khi chưa chạy Excel thật.

---

## §10. Dừng và báo

Dừng ngay, không tự chọn, khi:

1. Spec và code mâu thuẫn ở hành vi người dùng thấy được.
2. Cần sửa file ngoài allowlist của task.
3. Test cũ fail vì thay đổi của mình mà không rõ nguyên nhân.
4. `packages`/write path cần nới cổng an toàn để test xanh.
5. Live Excel không có sẵn (ghi `Not run`, không giả lập).

Báo: `Task / Lý do / 2 phương án / Đề xuất / Bằng chứng`.

---

## §11. Ngoài phạm vi

- Đề bài/KPI/Codex/PBIP patch, Advanced M.
- Undo/Redo, backup/restore, sửa dữ liệu sheet có sẵn.
- XLSX import logic (giữ nguyên native group insert).
- `%`, tiền tệ có ký hiệu, datetime có giờ, năm 2 chữ số (giữ text + ngoại lệ).
- Xoá backend `cleaning/mutation/journal` (chỉ bỏ mount UI).
- Đổi release version/manifest.

---

## §12. Definition of Done

- [ ] Journey `1. Nguồn → 2. Đề bài`; không còn DOM `#assistant-step-clean`, `#preparation-wizard`.
- [ ] Browser duyệt nhiều cấp, tick nhiều thư mục, keyboard, 360px không tràn.
- [ ] CSV sạch → 100% cột số/ngày ra number/date thật (`General`, `yyyy-mm-dd`), mã 0 đầu `@`.
- [ ] Report có đủ quyết định + file skipped; không raw data/path.
- [ ] Không preview, không câu hỏi định dạng, không chọn hệ ngày.
- [ ] Nhánh workbook không đổi dữ liệu; nguồn file không bị ghi.
- [ ] `py tools/run_checks.py fast` + `runtime` + full unittest xanh (chạy ngoài sandbox DSH).
- [ ] `acceptance.md` đầy đủ; live `Passed` hoặc `Not run` + lý do.
