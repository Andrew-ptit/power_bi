# Tasks — feature 003 (một tab Nguồn, nhập sheet đúng kiểu)

Input: [spec.md](spec.md), [plan.md](plan.md), [contracts/source-import.md](contracts/source-import.md), [data-model.md](data-model.md).
ID `T301–T308` thuộc feature 003; không trùng `T001–T012` của feature 002. Mỗi task là một đơn vị bàn giao cho **một agent**, có test đỏ trước, commit riêng.

## Trạng thái (cập nhật 2026-11-18)

| Task | Trạng thái | Bằng chứng / ghi chú |
|---|---|---|
| T301 | Chưa làm | — |
| **T302** | **Xong (thủ công)** | `py -m unittest tests.unit.test_csv_typing -v` → 19 tests OK, exit 0. Ba file do người viết sau khi model API hỏng. |
| T303 | Chưa làm | cần T302 (đã có `describe_columns`) |
| T304 | Chưa làm | **đường nhập vẫn ghi text**: `packages.py` còn `[["@"]]` |
| T305 | Chưa làm | — |
| T306 | Chưa làm | — |
| T307 | Chưa làm | `fast` gate hiện bị chặn bởi sandbox ghi `%TEMP%`, chưa phải lỗi code |
| T308 | Chưa làm | live Excel: `Not run` |

Ghi chú: `batch.py` (gọi API AMD TokenLab) **không còn dùng** — không ổn định (503, cắt token, lặp dòng). Bàn giao cho Codex theo [CODEX_HANDOFF.md](CODEX_HANDOFF.md).

## Quy ước chung cho mọi agent

- Chỉ sửa file trong cột **Files**. Cần ra ngoài → dừng, báo lý do, không tự mở rộng.
- TDD: viết test → chạy thấy đỏ **đúng lý do** → implement tối thiểu → xanh → chạy lại lệnh của task.
- Không thêm dependency; không đổi `pyproject`/manifest/release version; không `git reset/stash/checkout` toàn repo.
- Không in raw cell, đường dẫn cá nhân, binary hay token vào log/test output.
- Không xoá `cleaning.py`, `mutation.py`, `journal.py`, `store.preview/answer/begin_mutation`; backend đó là compatibility (spec §9).
- Mọi chuỗi UI mới: tiếng Việt, render bằng `textContent`, có `aria-live` cho tiến độ.
- Xong task: cập nhật đúng dòng evidence tương ứng trong `specs/003-source-import-redesign/acceptance.md` (T307 tạo file nếu chưa có — các task trước ghi tạm vào báo cáo, T307 hợp nhất).

## Phụ thuộc

```
T301 ──┬── T302 ── T303 ── T304 ──┐
       └── T305 ──────────────────┴── T306 ── T307 ── T308
```

- Wave 2 chạy song song: **T302** (Python, `csv_typing.py`) và **T305** (JS, browser UI) — khác file hoàn toàn.
- Wave 3: **T303** — cần `csv_typing.describe_columns()` từ T302 để dựng `fileSummary`.
- Wave 4: **T304** — cần T303 (inventory mới) và T302 (frame).
- Wave 5: **T306**. **T305 và T306 phải cùng một agent** vì cùng sửa `assistant_entry.js`/`taskpane.html`; T306 chạy sau T305.

---

## T301 — Contract đóng + owner docs

**Mục tiêu**: chốt hình dạng request/response trước khi bất kỳ ai viết code; ghi nhận thay đổi hành vi vào tài liệu sở hữu.

**Files**
- `pbip_assistant/schemas/preparation.schema.json`
- `pbip_assistant/sources/preparation/wire.py` (chỉ nếu cần thêm nhánh)
- `tests/contracts/test_source_import_contracts.py` (mới)
- `tests/contracts/test_preparation_contracts.py` (cập nhật nếu schema đổi danh sách action/field)
- `docs/current/TASKPANE_UI.md`
- `docs/current/SPEC.md` (chỉ thêm ghi chú phạm vi, không sửa FR hiện có)

**Không sửa**: `docs/current/CURRENT_STATUS.md` (chỉ T307), code runtime/UI.

**Việc phải làm**
1. Thêm vào schema (closed, `additionalProperties: false`):
   - action `browse`: `preparationId`, `expectedClaimVersion`, `root`, `relativePath`.
   - action `inventory`: đổi từ `root`+`relativePath` sang `root`+`items[]` (`{relativePath, fileName}`), 1…200.
   - action `packages`: thêm `dateSystem` enum `["1900","1904"]`.
   - Response không cần schema (server trả), nhưng `wire.py` phải từ chối key lạ và action lạ.
2. Test: `test_browse_rejects_extra_keys`, `test_inventory_requires_items_within_limit`, `test_inventory_rejects_absolute_or_parent_path`, `test_packages_rejects_unknown_date_system`, `test_legacy_actions_unchanged`, `test_report_reason_codes_closed`.
3. `docs/current/TASKPANE_UI.md`: thay mô tả journey 3 bước bằng 2 bước, mô tả browser + report, ghi rõ bỏ preview/câu hỏi định dạng/hệ ngày, nêu nhánh workbook không đổi dữ liệu.
4. `docs/current/SPEC.md`: thêm 3–5 dòng dưới §6 ghi phạm vi: đường *nhập sheet từ CSV trong task pane* tự quyết định dạng và báo ngoại lệ; FR-023 vẫn áp cho đường lập patch PBIP.

**Kiểm chứng**
```
py -m unittest tests.contracts.test_source_import_contracts -v
py -m unittest tests.contracts.test_preparation_contracts -v
py -m unittest tests.contracts.test_coordinator_dispatch -v
```

**Done**: 3 lệnh trên xanh; schema không nới lỏng key nào; docs mô tả đúng spec §2.

---

## T302 — `csv_typing`: suy luận kiểu + frame + decisions

**Mục tiêu**: một module thuần, tất định, không I/O, biến `headers + rows + dateSystem` thành frame đã định kiểu và danh sách quyết định.

**Files**
- `pbip_assistant/sources/preparation/csv_typing.py` (mới)
- `tests/support/csv_typing_oracle.py` (mới — oracle độc lập, viết tay, không import module)
- `tests/unit/test_csv_typing.py` (mới)

**API bắt buộc**

```python
def build_typed_frame(headers, rows, *, date_system) -> dict:
    """→ {"values": [[...]], "numberFormats": [[...]], "decisions": [...], "issues": [...]}"""
def describe_columns(headers, rows) -> dict:
    """→ {"columnCount": n, "kinds": {"number": a, "date": b, "text": c}}  (dùng cho FileSummary)"""
```

**Luật**: đúng spec §6, thứ tự ưu tiên formula-like → identifier → number → date → text. Không dùng `float()` trần cho chuỗi có dấu phân cách; parse theo `Decimal` rồi mới chuyển.

**Test bắt buộc** (mỗi luật một case, oracle viết tay)
- `test_plain_integers_and_decimals_become_numbers`
- `test_group_separator_comma_is_integer` (`1,234` → 1234)
- `test_group_separator_dot_is_integer_when_all_three_digit_groups` (`1.234` → 1234, reason `GROUP_SEPARATOR`)
- `test_decimal_comma_column` (`1,5` → 1.5)
- `test_leading_zero_stays_text` (`00123`)
- `test_precision_over_15_digits_stays_text`
- `test_dates_dmy_detected_by_day_gt_12` và `test_dates_mdy_detected_by_month_gt_12`
- `test_dates_ambiguous_default_dmy_with_reason`
- `test_invalid_date_column_stays_text`
- `test_1900_and_1904_serials` (cùng ngày, khác hệ, lệch đúng 1462)
- `test_formula_like_never_numeric` (`=1+1`, `+A1`, `@x`)
- `test_mixed_column_stays_text_with_exception`
- `test_empty_cells_and_empty_column`
- `test_deterministic_twice_identical`
- `test_report_bounds` (≤200 decisions, ≤2 samples, ≤40 ký tự)

**Kiểm chứng**
```
py -m unittest tests.unit.test_csv_typing -v
```

**Done**: mọi test xanh; không `numberFormats` nào sai bảng contract §3; module không import coordinator/Office.

---

## T303 — Browse cây thư mục + inventory theo lựa chọn

**Mục tiêu**: duyệt được thư mục con trong panel và chỉ đọc đúng file người dùng tick.

**Files**
- `pbip_assistant/sources/preparation/inventory.py`
- `pbip_assistant/sources/preparation/store.py`
- `pbip_assistant/coordinator/endpoints/preparation.py`
- `pbip_assistant/coordinator/server.py` (đăng ký route browse)
- `tests/fixtures/contracts/route_paths.json` (đồng bộ danh sách route)
- `tests/unit/test_preparation_browse.py` (mới)
- `tests/unit/test_preparation_inventory.py` (cập nhật theo signature mới)

**Không sửa**: `packages.py` (T304), task pane.

**Phụ thuộc**: T302 đã merge (`csv_typing.describe_columns`).

**Việc phải làm**
1. `browse_folder(root, relative_path) -> dict` đúng response contract §1: chỉ folder + `.csv`/`.xlsx`; sort folder trước; tối đa 500 + `truncated`; `parentRelativePath`; breadcrumb; guard thoát root/reparse.
2. `inventory_selection(root, items)`: chỉ đọc các cặp `(relativePath, fileName)`; giữ nguyên `_guard`/`_bounded_bytes`/`_unchanged`/`verify_inventory`; gom lỗi từng file vào `errors[]`; thêm `fileSummary` bằng `csv_typing.describe_columns(headers, rows)` — **không** tự viết bảng map kiểu thứ hai.
3. `store.browse(...)`, `store.inventory(..., items)`, endpoint action `browse`; `inventory` đổi body; giữ `expectedClaimVersion` check.
4. Giữ `inventory_folder` (hàm cũ) nếu test cũ còn dùng — có thể refactor nó thành `inventory_selection` với items = toàn bộ file trực tiếp.

**Test bắt buộc**
- `test_browse_lists_folders_then_supported_files_sorted`
- `test_browse_skips_unsupported_and_hidden_files`
- `test_browse_rejects_parent_escape_and_absolute_path`
- `test_browse_truncates_at_500`
- `test_browse_empty_folder_returns_empty_list`
- `test_inventory_reads_only_selected_items` (file không tick không bị đọc — assert qua số lần `_bounded_bytes`/stamp)
- `test_inventory_collects_per_file_errors_without_failing_batch`
- `test_inventory_rejects_duplicate_items_and_over_200`
- `test_inventory_still_detects_source_change`

**Kiểm chứng**
```
py -m unittest tests.unit.test_preparation_browse tests.unit.test_preparation_inventory -v
py -m unittest tests.contracts.test_source_import_contracts -v
```

**Done**: browse không đọc nội dung (test dùng file lớn/không đọc được vẫn liệt kê được); inventory đọc đúng items; không thay đổi hành vi verify/stamp.

---

## T304 — Typed CSV frame + import report trong `packages`

**Mục tiêu**: bỏ `[["@"]]`, ghi frame đã định kiểu và trả report.

**Files**
- `pbip_assistant/sources/preparation/packages.py`
- `pbip_assistant/sources/preparation/mutation.py` (**chỉ** method `packages`, không đụng begin/apply)
- `pbip_assistant/sources/preparation/store.py` (truyền `dateSystem`)
- `tests/unit/test_preparation_packages.py` (cập nhật)
- `tests/integration/test_preparation_api.py` (thêm case `packages` + `dateSystem`)
- `pbip_assistant/coordinator/endpoints/preparation.py` (chỉ nhánh packages chuyển dateSystem)
- `tests/integration/test_preparation_direct.py` (đồng bộ request inventory và kiểm chứng dữ liệu đúng kiểu)
- `tests/integration/test_preparation_mutation.py` (chỉ fixture Qty nếu tái hiện sai kiểu trong ảnh phục hồi)
- `pbip_assistant/sources/preparation/csv_typing.py` (duyệt 2026-11-20: ô trống = `null` + `General`)
- `pbip_assistant/sources/preparation/package_preservation.py` (duyệt 2026-11-20: verifier so `numberFormats` của package)
- `tests/unit/test_preparation_package_preservation.py` (duyệt 2026-11-20: plan CSV có `numberFormats`)
- `tests/unit/test_csv_typing.py` (duyệt 2026-11-20: kỳ vọng ô trống)
- `specs/003-source-import-redesign/contracts/source-import.md` (duyệt 2026-11-20: `readingDecisions`, `reviewHash` theo `dateSystem`)
- `specs/003-source-import-redesign/spec.md` (duyệt 2026-11-20: đồng bộ mục 9 + ô trống)
- `specs/003-source-import-redesign/acceptance.md` (duyệt 2026-11-20: bằng chứng T304)
- `specs/003-source-import-redesign/tasks.md` (duyệt 2026-11-20: allowlist + phạm vi T304)

**Không sửa**: `csv_typing.py` (T302), UI.

**Việc phải làm**
1. CSV branch: đọc rows như hiện tại (encoding/delimiter/header_row từ `csvReading`) → `csv_typing.build_typed_frame(..., date_system=body dateSystem)` → `values/formulas/formulaCells/numberFormats`.
2. Giữ guard hiện có: ragged rows, `MAX_CELLS`, 100k dòng, 200 cột, 64 MiB.
3. Gộp `decisions` + `reading` + `sheets` thành `importReport` (contract §3); file lỗi thành `status: "skipped"` với `issues[]`, **không** ném lỗi cả lô; không có package cho file skipped.
4. `mutation.Store.packages(..., date_system=None)`; endpoint truyền `body["dateSystem"]`; thiếu khi có cột ngày → `DP_DATE_SYSTEM_REQUIRED`; không có cột ngày → mặc định `"1900"` để `direct.py` không đổi.
5. XLSX branch giữ nguyên hành vi (không đổi frame native).
6. Ô CSV rỗng → `null` + numberFormat `General`; cột toàn rỗng vẫn `EMPTY_COLUMN` (quyết định 2026-11-20).
7. `verify_package_csv_import` so `numberFormats` từng ô của package, không bắt mọi ô `@` (quyết định 2026-11-20).

**Test bắt buộc**
- `test_csv_number_column_written_as_number_general`
- `test_csv_date_column_serial_matches_1900_and_1904`
- `test_csv_leading_zero_and_text_columns_use_at_format`
- `test_import_report_lists_decisions_with_reason_codes`
- `test_ragged_csv_skipped_but_other_files_import`
- `test_report_has_no_absolute_path_or_raw_row`
- `test_date_system_required_when_date_columns_exist`
- `test_xlsx_package_unchanged`
- `test_empty_cells_are_blank_with_general_format` (quyết định 2026-11-20)
- `test_packages_leaves_empty_csv_cells_blank_with_general` (quyết định 2026-11-20)
- `test_typed_formats_pass_and_wrong_format_is_rejected` (quyết định 2026-11-20)
- `test_oversized_csv_is_skipped_without_blocking_other_files`

**Kiểm chứng**
```
py -m unittest tests.unit.test_preparation_packages -v
py -m unittest tests.integration.test_preparation_api -v
py -m unittest tests.unit.test_csv_typing -v
```

**Done**: không còn `[["@"]]` cho CSV; report khớp contract; XLSX không đổi.

---

## T305 — UI: browser cây thư mục + chọn file + báo cáo kết quả

**Mục tiêu**: người dùng duyệt cây, tick file, nhập, xem kết quả + ngoại lệ — tất cả trong tab Nguồn.

**Files**
- `pbip_assistant/excel_addin/assistant_browser.js` (mới)
- `pbip_assistant/excel_addin/assistant_entry.js` (chỉ thêm điểm nối `onImported`/`onBrowse`, **không** đổi journey/step — T306)
- `pbip_assistant/excel_addin/preparation_bridge.js`
- `pbip_assistant/excel_addin/preparation_runtime.js` (thêm `probeDateSystem`)
- `pbip_assistant/excel_addin/taskpane.html`
- `pbip_assistant/excel_addin/taskpane.css`
- `tests/taskpane/taskpane_assistant_browser.js` (mới)
- `tests/taskpane/test_taskpane_js.py` (đăng ký script mới)
- `pbip_assistant/excel_addin/taskpane.js` (duyệt 2026-11-20: mount browser + nối `onBrowse`/`onImported`)
- `tests/taskpane/preparation_native_mutations.js` (duyệt 2026-11-20: fixture typed + `probeDateSystem`)
- `tests/taskpane/taskpane_preparation_startup.js` (duyệt 2026-11-20: nạp module browser)
- `specs/003-source-import-redesign/acceptance.md` (duyệt 2026-11-20: bằng chứng T305)
- `specs/003-source-import-redesign/tasks.md` (duyệt 2026-11-20: allowlist + phạm vi T305)

**Không sửa**: `assistant_entry.js` phần journey/step (T306 sửa); `preparation_controller.js`.

**Markup/chuỗi bắt buộc**
- Khối browser: `#assistant-browser` gồm breadcrumb `#assistant-browser-path`, nút `#assistant-browser-up` (`↑ Lên cấp trên`), danh sách `#assistant-browser-list`, dòng trạng thái `#assistant-browser-status`.
- Footer: `#assistant-selected-summary` (`Đã chọn N file · M sheet sẽ được tạo`), nút `#assistant-import-selected` (`Nhập vào workbook`), nút `#assistant-select-all` (`Chọn tất cả thư mục này`).
- Kết quả: `#assistant-import-report` với `#assistant-import-summary` (`Đã nhập 8 file → 8 sheet`), `#assistant-import-exceptions` (`Ngoại lệ đã tự xử lý (12)` — mỗi dòng: `dim_products.csv · unit_price: số · dấu chấm thập phân → Number · 1.480 ô`), `#assistant-import-skipped` (`Bỏ qua (1)` + lý do).
- Tiến độ: `Đang nhập 3/8: dim_products.csv…` trong `aria-live`.
- Trạng thái rỗng: `Thư mục này không có file .csv hoặc .xlsx.`; huỷ dialog: `Chưa chọn thư mục.`

**Hành vi**
1. `preparation_bridge.browse(relativePath)` → `assistant_browser.render(...)`; đi vào folder khi click; `up` về parent; giữ selection theo `(relativePath,fileName)` trong `Map`.
2. Tick file: hiện `fileSummary` (`8 cột · 5 số · 2 ngày · 1 chữ`) — **không** hiện giá trị ô.
3. Nhập: `probeDateSystem()` (một lần, cache theo workbook) → `importSelection({items, dateSystem})` → render report → gọi `onImported()` (entry sẽ nối ở T306).
4. Không có bảng preview, không câu hỏi, không select hệ ngày, không nút `Xem trước`.
5. Keyboard: Tab/Enter/Space hoạt động; mọi text qua `textContent`; 360px không tràn ngang.
6. Trước khi nhập chỉ hiện số file đã chọn; cột/số/ngày/chữ và số sheet chỉ hiện sau khi nhập (SI04 đã chốt 2026-11-20). Đọc file khi bấm nhập: `inventorySelection` → `review-import` → `packages(dateSystem)` → approve/direct.
7. `probeDateSystem()` thất bại → chặn nhập, báo rõ; không mặc định 1900 (quyết định 2026-11-20).
8. Sau nhập: bỏ file đã nhập khỏi selection, giữ file bị skipped để nhập lại (quyết định 2026-11-20).

**Test bắt buộc** (`node tests/taskpane/taskpane_assistant_browser.js`, fake DOM + fake bridge)
- `test_browse_renders_folders_before_files_and_breadcrumb`
- `test_navigate_into_and_up_keeps_selection`
- `test_select_all_scoped_to_current_folder`
- `test_summary_counts_files_and_sheets`
- `test_import_posts_items_and_date_system`
- `test_report_renders_exceptions_and_skipped_without_raw_values`
- `test_no_preview_or_question_dom`
- `test_status_strings_vietnamese`
- `test_text_rendered_as_text_not_html`

**Kiểm chứng**
```
node tests/taskpane/taskpane_assistant_browser.js
node tests/taskpane/preparation_native_mutations.js
node tests/taskpane/taskpane_preparation_startup.js
py -m unittest tests.taskpane.test_taskpane_js -v
```

**Done**: script mới xanh và được đăng ký trong `test_taskpane_js.py`; không sửa hành vi journey.

---

## T306 — Bỏ bước `Làm sạch`, journey 2 bước, vệ sinh wiring

**Mục tiêu**: hành trình còn `1. Nguồn → 2. Đề bài`; không còn DOM/nhánh code preview, câu hỏi, hệ ngày; `scan` chạy ngầm để giữ binding Đề bài.

**Files**
- `pbip_assistant/excel_addin/assistant_entry.js`
- `pbip_assistant/excel_addin/taskpane.html`
- `pbip_assistant/excel_addin/taskpane.css`
- `pbip_assistant/excel_addin/taskpane.js` (chỉ phần mount/gate liên quan)
- `tests/taskpane/taskpane_assistant_journey.js` (mới)
- `tests/taskpane/taskpane_assistant_entry.js` (đồng bộ kiểm tra hành trình hai bước, giữ kiểm tra lỗi và phục hồi)
- `tests/taskpane/test_taskpane_js.py`
- `tests/taskpane/taskpane_preparation_wizard.js` (chỉ để bỏ assert DOM wizard nếu đã xoá — ghi rõ lý do)
- `pbip_assistant/excel_addin/preparation_controller.js` (duyệt 2026-11-20: headless, bỏ nhánh render wizard)
- `pbip_assistant/excel_addin/preparation_bridge.js` (duyệt 2026-11-20: `businessSourcesFromScan`, bỏ applyCleanup/undo/redo)
- `pbip_assistant/excel_addin/assistant_browser.js` (duyệt 2026-11-20: `reopen()` giữ thư mục + selection)
- `tests/taskpane/taskpane_preparation_bridge.js` (duyệt 2026-11-20: handoff từ scan, bỏ cleanup)
- `tests/taskpane/taskpane_preparation_direct.js` (duyệt 2026-11-20: `packages` trả `reviewHash`)
- `specs/003-source-import-redesign/acceptance.md` (duyệt 2026-11-20: bằng chứng T306)
- `specs/003-source-import-redesign/tasks.md` (duyệt 2026-11-20: allowlist + phạm vi T306)

**Việc phải làm**
1. Xoá `#assistant-step-clean` khỏi journey; `#assistant-step-problem` đổi nhãn `2. Đề bài`; state machine trong `assistant_entry.js` bỏ `step === "clean"`.
2. Xoá `#preparation-wizard` (details, select hệ ngày, `#preparation-scan`, `#preparation-inventory`, `#preparation-panel`) khỏi tab Trợ lý. Trong `taskpane.js`: bỏ `showCleaning`/`applyCleanup`/`undo`/`redo`/`onApplied` khỏi entry, **giữ** `window.ReqwisePreparation.mount(...)` (vì `bridge.getState`, `wizard.state` và `probeDateSystem/scanWorkbook` phụ thuộc nó) cùng `onDirty`/`onBusy`. Không xoá file `preparation_controller.js`.
3. Sau nhập (T305) hoặc chọn workbook: chạy `scan()` ngầm với progress `Đang đọc lại nguồn…`; thành công → `canProblem = true`, hiện summary nguồn; thất bại → thông báo lỗi, `Đề bài` tắt.
4. `+ Thêm nguồn` mở lại browser; giữ selection cũ hay reset theo hành vi hiện có nhưng phải nhất quán và có test.
5. Không đổi cơ chế approval/permit/read-back của import; không đổi nhánh workbook.
6. Business handoff lấy snapshot của lần scan sau import (`businessSourcesFromScan`), không Apply làm sạch (quyết định 2026-11-20).
7. Scan lỗi: giữ report đã nhập, tắt Đề bài, hiện nút `Đọc lại nguồn` (quyết định 2026-11-20).
8. `+ Thêm nguồn` mở lại browser đúng thư mục, giữ selection skipped (quyết định 2026-11-20).
9. Bỏ applyCleanup/undo/redo/cleaningComplete khỏi entry, bridge, taskpane; controller còn headless giữ `wizard.state` + `scanWorkbook` (quyết định 2026-11-20).

**Test bắt buộc**
- `test_journey_has_two_steps_only`
- `test_no_cleaning_wizard_dom`
- `test_import_then_continue_enabled_after_scan`
- `test_workbook_choice_does_not_write_cells`
- `test_scan_failure_disables_problem_step`
- `test_add_source_returns_to_browser`

**Kiểm chứng**
```
node tests/taskpane/taskpane_assistant_journey.js
node tests/taskpane/taskpane_assistant_entry.js
node tests/taskpane/taskpane_preparation_wizard.js
py -m unittest tests.taskpane.test_taskpane_js -v
```
**Done**: không còn tham chiếu DOM `#preparation-wizard`/`#assistant-step-clean`; journey 2 bước; scan ngầm vẫn cấp binding cho Đề bài.

---

## T307 — Regression, acceptance matrix, owner docs

**Files**
- `specs/003-source-import-redesign/acceptance.md` (mới)
- `docs/current/TASKPANE_UI.md`, `docs/current/CURRENT_STATUS.md` (chỉ ghi trạng thái, **không** bump version)
- `tests/required_cases.json` (chỉ nếu cần thêm case mới; không xoá case)

**Việc phải làm**
1. Lập acceptance matrix: mỗi `S01–S13`, `SI01–SI15`, `SC01–SC08` ↔ test/evidence, trạng thái `Pass / Fail / Blocked / Not run`.
2. Chạy full gate và ghi command + revision + thời gian + kết quả:
   ```
   py tools/run_checks.py fast
   py tools/run_checks.py runtime
   py -m unittest discover -s tests -v
   node tests/taskpane/taskpane_assistant_browser.js
   node tests/taskpane/taskpane_assistant_journey.js
   ```
3. Rà `docs/current/TASKPANE_UI.md` lần cuối; ghi CURRENT_STATUS: feature 003 automated pass, **live Excel `Not run`**, release metadata không đổi.
4. Không tuyên bố "verified" cho bất kỳ mục chỉ có test giả lập.

**Done**: 3 lệnh gate xanh; acceptance.md đầy đủ; không case nào bị xoá khỏi `required_cases.json`.

---

## T308 — Live synthetic (chỉ khi có Excel)

**Files**: `specs/003-source-import-redesign/acceptance.md`, `tests/live/README.md` (bổ sung scenario nếu làm).

**Việc phải làm**
1. Nếu môi trường có Excel Desktop + harness: tạo fixture synthetic (CSV số/ngày/mã 0 đầu + 1 file lỗi), chạy đúng journey: browse 2 cấp → tick → nhập → đọc lại `numberFormat` + `typeof values` từ Excel thật → đối chiếu oracle.
2. Nếu không có Excel/harness: ghi `Blocked`/`Not run` với lý do chính xác, **không** giả lập thành pass, không giao việc kiểm thử cho người dùng như implementer.
3. Tuyệt đối không dùng workbook thật của người dùng làm fixture.

**Done**: có evidence thật hoặc dòng `Not run` trung thực trong acceptance.md.

---

## Định dạng báo cáo cuối mỗi task

```
Task: T30x
Status: done | blocked
Tests: <command> → pass/fail (N tests, Xs)
Files changed: <paths>
Deviations: <none | mô tả + lý do>
Open questions: <none | ...>
```

## Definition of Done (toàn feature)

- [ ] Journey chỉ còn `1. Nguồn` và `2. Đề bài`; không DOM preview/câu hỏi/hệ ngày.
- [ ] CSV sạch → 100% cột số/ngày ra number/date thật đúng numberFormat.
- [ ] Mọi quyết định tự động hiện trong report; file lỗi bị bỏ qua có lý do.
- [ ] Browser duyệt nhiều cấp, giữ selection, dùng được bằng keyboard ở 360px.
- [ ] Nhánh workbook không đổi dữ liệu; nguồn file không bị ghi.
- [ ] Gate fast/runtime/full xanh; toàn bộ script taskpane đang có trong gate + 2 script mới chạy.
- [ ] `acceptance.md` có evidence và `Not run` trung thực cho live.
