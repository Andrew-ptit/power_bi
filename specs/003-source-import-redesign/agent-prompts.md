# Prompt giao việc cho Codex — feature 003

> **Cập nhật 2026-11-18:** T302 đã xong (thủ công, 19 test). Quy trình + kiểm soát chất lượng: [CODEX_HANDOFF.md](CODEX_HANDOFF.md). Không còn dùng `batch.py`/API TokenLab. Prompt cho reviewer: CODEX_HANDOFF §5.

Mục đích: mỗi agent nhận **một** task, tự đọc spec/contract/tasks, chỉ sửa file của mình, trả báo cáo có bằng chứng. Dán nguyên khối, đừng tóm tắt lại — tóm tắt là nguồn gốc của "làm sai ý".

Cấu trúc: **§1 PREAMBLE** (dán đầu *mọi* prompt) + **§2 prompt riêng từng task** + **§3 prompt điều phối** + **§4 cách kiểm sau mỗi sóng**.

---

## §1. PREAMBLE — dán đầu mọi prompt

```text
Repo: C:\Users\COLAIG\Downloads\power_bi (Windows, Python 3.13 stdlib, Node 24). Không thêm dependency.

Bạn thi công ĐÚNG MỘT task của feature 003. Đọc theo thứ tự, trước khi sửa bất kỳ file nào:
  1. specs/003-source-import-redesign/spec.md            (nguồn sự thật về hành vi)
  2. specs/003-source-import-redesign/contracts/source-import.md (shape request/response, reasonCode)
  3. specs/003-source-import-redesign/plan.md §4         (bảng file ↔ task)
  4. specs/003-source-import-redesign/tasks.md → mục task của bạn (test bắt buộc, lệnh kiểm chứng)
  5. AGENTS.md                                           (luật dự án, bắt buộc)

Luật cứng:
- CHỈ sửa file nằm trong mục "Files" của task. Cần sửa file khác → DỪNG, báo rõ file + lý do, không tự mở rộng.
- TDD: viết test trước → chạy thấy ĐỎ đúng lý do → implement tối thiểu → XANH → chạy lại toàn bộ lệnh của task.
- Không đổi release version / manifest / pyproject; không thêm dependency; không xoá backend cũ
  (cleaning.py, mutation.py, journal.py, store.preview/answer).
- Không log/không in raw cell, đường dẫn cá nhân, binary, token. UI chỉ dùng textContent.
- Không được nói "xong/pass" khi chưa chạy đúng lệnh kiểm chứng trong tasks.md và dán output thật.
- Không `git reset`, `git stash`, `git checkout .`, không commit file ngoài task.
- Nếu spec và code hiện tại mâu thuẫn, hoặc spec thiếu một quyết định: DỪNG công việc đang làm,
  mô tả mâu thuẫn + 2 phương án + đề xuất. Không tự chọn rồi đi tiếp.

Kết thúc, trả đúng mẫu:
  Task: T3xx
  Status: done | blocked
  Tests: <lệnh> → pass/fail (N test, Xs)  [dán dòng summary thật]
  Files changed: <danh sách path>
  Deviations: <none | mô tả + lý do>
  Open questions: <none | ...>
```

---

## §2. Prompt từng task

### T301 — Contract + owner docs

```text
[PREAMBLE §1]  Task: T301.

MỤC TIÊU: chốt contract đóng cho browse/inventory/packages và ghi thay đổi hành vi vào docs/current,
TRƯỚC khi bất kỳ ai viết code.

FILES (chỉ những file này):
- pbip_assistant/schemas/preparation.schema.json
- pbip_assistant/sources/preparation/wire.py (chỉ nếu schema-driven chưa đủ)
- tests/contracts/test_source_import_contracts.py (mới)
- tests/contracts/test_preparation_contracts.py (cập nhật nếu danh sách action/field đổi)
- docs/current/TASKPANE_UI.md
- docs/current/SPEC.md (chỉ thêm ghi chú phạm vi dưới §6, KHÔNG sửa FR-001..FR-036)

NỘI DUNG:
1. action `browse`: {preparationId, expectedClaimVersion, root, relativePath}.
2. action `inventory`: đổi body thành {root, items:[{relativePath, fileName}]} 1..200.
3. action `packages`: thêm `dateSystem` enum ["1900","1904"].
4. Từ chối key lạ, action lạ, path tuyệt đối/`..` trong items.
5. TASKPANE_UI.md: journey còn `1. Nguồn → 2. Đề bài`; mô tả browser + report; ghi rõ bỏ preview,
   bỏ câu hỏi định dạng, bỏ chọn hệ ngày; nhánh workbook không đổi dữ liệu.
6. SPEC.md: 3–5 dòng ghi phạm vi "nhập sheet từ CSV trong task pane tự quyết định dạng + báo ngoại lệ;
   FR-023 vẫn áp cho đường lập patch PBIP".

KIỂM CHỨNG (phải chạy, dán output):
  py -m unittest tests.contracts.test_source_import_contracts -v
  py -m unittest tests.contracts.test_preparation_contracts -v
  py -m unittest tests.contracts.test_coordinator_dispatch -v

DONE: 3 lệnh xanh; schema không nới lỏng key nào; không đổi release metadata.
```

### T302 — `csv_typing`

```text
[PREAMBLE §1]  Task: T302.

MỤC TIÊU: module thuần, không I/O, biến (headers, rows, date_system) thành frame đã định kiểu + decisions,
theo đúng bảng luật spec §6.

FILES:
- pbip_assistant/sources/preparation/csv_typing.py (mới)
- tests/support/csv_typing_oracle.py (mới — oracle viết tay, KHÔNG import csv_typing)
- tests/unit/test_csv_typing.py (mới)

API bắt buộc:
  build_typed_frame(headers, rows, *, date_system) -> {"values","numberFormats","decisions","issues"}
  describe_columns(headers, rows) -> {"columnCount","kinds":{"number","date","text"}}
Thứ tự ưu tiên: formula-like → identifier(0 đầu) → number → date → text. Không dùng float() trần
cho chuỗi có dấu phân cách; parse bằng Decimal rồi mới chuyển.

TEST BẮT BUỘC: đủ danh sách trong tasks.md T302 (15 case). Đặc biệt:
- `1,234` → 1234 (GROUP_SEPARATOR); `1.234` toàn nhóm 3 chữ số → 1234;
- `00123` → text; `=1+1`/`+A1`/`@x` → text;
- ngày: DMY khi có ngày >12 ở vị trí đầu, MDY khi có tháng >12, mơ hồ → DMY + DATE_DMY_DEFAULT;
- serial 1900 vs 1904 lệch đúng 1462; chạy 2 lần cho kết quả giống hệt.

KIỂM CHỨNG: py -m unittest tests.unit.test_csv_typing -v

DONE: 15+ case xanh, không import coordinator/Office, không I/O.
```

### T303 — browse + inventory theo lựa chọn

```text
[PREAMBLE §1]  Task: T303.

MỤC TIÊU: duyệt cây thư mục trong panel và chỉ đọc đúng file người dùng tick.

FILES:
- pbip_assistant/sources/preparation/inventory.py
- pbip_assistant/sources/preparation/store.py
- pbip_assistant/coordinator/endpoints/preparation.py
- tests/unit/test_preparation_browse.py (mới)
- tests/unit/test_preparation_inventory.py (cập nhật theo signature mới)

KHÔNG SỬA: packages.py, task pane.
PHỤ THUỘC: T302 đã merge — dùng csv_typing.describe_columns cho fileSummary, KHÔNG viết bảng map kiểu thứ hai.

NỘI DUNG:
1. browse_folder(root, relative_path): chỉ folder + file .csv/.xlsx; folder trước rồi theo name.casefold();
   tối đa 500 + truncated; breadcrumb + parentRelativePath; chặn thoát root/`..`/reparse; không đọc nội dung file.
2. inventory_selection(root, items): chỉ đọc các cặp (relativePath, fileName); giữ _guard/_bounded_bytes/
   _unchanged/verify_inventory; lỗi từng file vào errors[] (không làm hỏng cả lô); thêm fileSummary.
3. store.browse(...), store.inventory(..., items), endpoint action `browse`, `inventory` đổi body.
4. Giữ hành vi verify_inventory/stamp và giới hạn 200 file / byte limit.

TEST BẮT BUỘC: đúng 9 case trong tasks.md T303, gồm "browse không đọc nội dung" (file không đọc được vẫn liệt kê được)
và "inventory chỉ đọc file đã tick" (assert qua stamp/số lần đọc).

KIỂM CHỨNG:
  py -m unittest tests.unit.test_preparation_browse tests.unit.test_preparation_inventory -v
  py -m unittest tests.contracts.test_source_import_contracts -v

DONE: browse không đọc nội dung, inventory đọc đúng items, không đổi hành vi verify/stamp.
```

### T304 — typed frame + import report

```text
[PREAMBLE §1]  Task: T304.

MỤC TIÊU: bỏ `[["@"]]` cho CSV; ghi frame đã định kiểu và trả importReport.

FILES:
- pbip_assistant/sources/preparation/packages.py
- pbip_assistant/sources/preparation/mutation.py (CHỈ method packages(); không đụng begin/apply)
- pbip_assistant/sources/preparation/store.py (truyền date_system)
- tests/unit/test_preparation_packages.py (cập nhật)
- tests/integration/test_preparation_api.py (thêm case packages + dateSystem)

KHÔNG SỬA: csv_typing.py (T302), task pane.

NỘI DUNG:
1. CSV branch: csv.reader như hiện tại → csv_typing.build_typed_frame(..., date_system=...) → values/formulas/
   formulaCells/numberFormats. Giữ guard: ragged rows, MAX_CELLS, 100k dòng, 200 cột, 64 MiB.
2. importReport đúng contract §3: totals + files[] (status imported/skipped, reading, sheets, decisions, issues).
   File lỗi → skipped + issues[], KHÔNG ném lỗi cả lô, KHÔNG tạo package cho file skipped.
3. packages(..., date_system=None): thiếu khi có cột ngày → DP_DATE_SYSTEM_REQUIRED; không có cột ngày → "1900".
4. XLSX branch giữ nguyên byte-for-byte hành vi.

TEST BẮT BUỘC: 8 case trong tasks.md T304. Bắt buộc assert:
  typeof value == "number" và numberFormat == "General" cho cột số; serial đúng cả 1900/1904;
  text `@` cho mã 0 đầu; report không chứa path tuyệt đối/raw row.

KIỂM CHỨNG:
  py -m unittest tests.unit.test_preparation_packages -v
  py -m unittest tests.integration.test_preparation_api -v
  py -m unittest tests.unit.test_csv_typing -v

DONE: không còn [["@"]] cho CSV; XLSX không đổi.
```

### T305 — UI browser + report (agent UI, phần 1)

```text
[PREAMBLE §1]  Task: T305.

MỤC TIÊU: người dùng duyệt cây thư mục, tick file, nhập, xem kết quả + ngoại lệ — trong tab Nguồn.
LƯU Ý: bạn sẽ làm tiếp T306 trong cùng phiên; đừng đổi journey ở bước này.

FILES: (đúng danh sách tasks.md T305)
- pbip_assistant/excel_addin/assistant_browser.js (mới)
- pbip_assistant/excel_addin/assistant_entry.js (chỉ điểm nối onImported/onBrowse)
- pbip_assistant/excel_addin/preparation_bridge.js
- pbip_assistant/excel_addin/preparation_runtime.js (thêm probeDateSystem)
- pbip_assistant/excel_addin/taskpane.html, taskpane.css
- tests/taskpane/taskpane_assistant_browser.js (mới)
- tests/taskpane/test_taskpane_js.py (đăng ký script)

KHÔNG SỬA: preparation_controller.js; phần journey/step của assistant_entry.js.

MARKUP/CHUỖI: dùng đúng id + chuỗi tiếng Việt trong tasks.md T305 (mục "Markup/chuỗi bắt buộc").
KHÔNG có bảng preview dữ liệu, KHÔNG câu hỏi định dạng, KHÔNG select hệ ngày, KHÔNG nút Xem trước.

HÀNH VI: browse(relativePath) → render; vào folder / lên cấp trên; selection giữ theo (relativePath, fileName);
tick file hiện fileSummary (8 cột · 5 số · 2 ngày · 1 chữ); nhập: probeDateSystem() một lần (cache theo workbook)
→ importSelection({items, dateSystem}) → render report → onImported(); keyboard đủ; 360px không tràn ngang.

KIỂM CHỨNG:
  node tests/taskpane/taskpane_assistant_browser.js
  py -m unittest tests.taskpane.test_taskpane_js -v

DONE: script mới xanh + đã đăng ký; không đổi journey.
```

### T306 — bỏ bước Làm sạch, journey 2 bước (agent UI, phần 2)

```text
[PREAMBLE §1]  Task: T306. Nếu bạn vừa làm T305 thì tiếp tục luôn, không cần đọc lại từ đầu.

MỤC TIÊU: journey còn `1. Nguồn → 2. Đề bài`; xoá DOM/nhánh code preview, câu hỏi, chọn hệ ngày;
scan vẫn chạy ngầm để giữ binding cho Đề bài.

FILES:
- pbip_assistant/excel_addin/assistant_entry.js
- pbip_assistant/excel_addin/taskpane.html, taskpane.css
- pbip_assistant/excel_addin/taskpane.js (chỉ phần mount/gate liên quan)
- tests/taskpane/taskpane_assistant_journey.js (mới)
- tests/taskpane/test_taskpane_js.py
- tests/taskpane/taskpane_preparation_wizard.js (chỉ bỏ assert DOM wizard; ghi rõ lý do, không xoá case khác)

NỘI DUNG:
1. Xoá #assistant-step-clean; #assistant-step-problem đổi nhãn `2. Đề bài`; bỏ state "clean".
2. Xoá #preparation-wizard (details, select hệ ngày, #preparation-scan, #preparation-inventory, #preparation-panel).
   Trong taskpane.js bỏ showCleaning/applyCleanup/undo/redo/onApplied khỏi entry, nhưng GIỮ
   window.ReqwisePreparation.mount(...) vì bridge.getState/wizard.state/scanWorkbook phụ thuộc nó.
   Không xoá file preparation_controller.js.
3. Sau nhập hoặc chọn workbook: scan ngầm (progress `Đang đọc lại nguồn…`) → thành công: canProblem=true,
   hiện summary nguồn; thất bại: báo lỗi, Đề bài tắt.
4. `+ Thêm nguồn` mở lại browser.

TEST BẮT BUỘC: 6 case trong tasks.md T306.

KIỂM CHỨNG:
  node tests/taskpane/taskpane_assistant_journey.js
  node tests/taskpane/taskpane_assistant_entry.js
  node tests/taskpane/taskpane_preparation_wizard.js
  py -m unittest tests.taskpane.test_taskpane_js -v

DONE: không còn tham chiếu #preparation-wizard/#assistant-step-clean; scan ngầm vẫn cấp binding.
```

### T307 — regression + acceptance

```text
[PREAMBLE §1]  Task: T307.

MỤC TIÊU: chứng minh toàn feature xanh và ghi evidence trung thực.

FILES:
- specs/003-source-import-redesign/acceptance.md (mới)
- docs/current/TASKPANE_UI.md, docs/current/CURRENT_STATUS.md (chỉ trạng thái, KHÔNG bump version)
- tests/required_cases.json (chỉ thêm, không xoá case)

NỘI DUNG:
1. acceptance.md: bảng S01–S13 / SI01–SI15 / SC01–SC08 ↔ test hoặc evidence; trạng thái Pass/Fail/Blocked/Not run.
2. Chạy và dán output: py tools/run_checks.py fast; py tools/run_checks.py runtime;
   py -m unittest discover -s tests -v; 2 script taskpane mới.
3. Ghi CURRENT_STATUS: automated pass, live Excel `Not run`, release metadata không đổi.
4. Không gắn "verified" cho mục chỉ có test giả lập. Không xoá/skip case nào để đạt xanh.

DONE: gate xanh + acceptance đầy đủ + không case nào bị gỡ.
```

### T308 — live synthetic

```text
[PREAMBLE §1]  Task: T308.

MỤC TIÊU: chạy journey thật trên Excel Desktop nếu môi trường có; nếu không, ghi Not run trung thực.

1. Nếu có Excel + harness: fixture synthetic (CSV số/ngày/mã 0 đầu + 1 file lỗi), chạy browse 2 cấp → tick →
   nhập → đọc lại numberFormat + typeof values từ Excel thật → đối chiếu oracle. Không dùng workbook của người dùng.
2. Nếu không có: ghi `Blocked/Not run` + lý do chính xác vào acceptance.md. Không mô phỏng rồi ghi pass.
```

---

## §3. Prompt điều phối (dán cho agent lead/Codex chính)

```text
Bạn là agent điều phối thi công feature 003 trong repo C:\Users\COLAIG\Downloads\power_bi.

Đọc trước: specs/003-source-import-redesign/{spec,plan,tasks}.md + contracts/source-import.md + AGENTS.md.

Nhiệm vụ: chạy đúng thứ tự sóng dưới đây, mỗi sóng giao cho MỘT subagent, dán prompt tương ứng
trong specs/003-source-import-redesign/agent-prompts.md (kèm PREAMBLE §1). Sau mỗi sóng, bạn tự kiểm rồi
mới mở sóng sau. Không sửa code thay subagent trừ khi họ blocked.

Wave A: T301
Wave B: T302  ||  T305
Wave C: T303
Wave D: T304
Wave E: T306
Wave F: T307
Wave G: T308

Sau mỗi sóng, bắt buộc tự kiểm (đừng tin báo cáo suông):
  git status --short          # chỉ file thuộc task được đổi
  git diff --stat             # không có file lạ
  <lệnh kiểm chứng của task>  # chạy lại chính bạn, không dán của subagent
  grep -n "@unittest.skip\|it.skip\|test.skip" <file test mới>   # không skip để đạt xanh
Nếu lệch: dừng, gửi prompt sửa (§4) cho đúng agent đó, không mở sóng mới.

Báo cáo cuối mỗi sóng: task, file đổi, lệnh + kết quả thật, lệch so với spec (nếu có), task kế tiếp.
```

---

## §4. Prompt sửa khi một task trượt

```text
[PREAMBLE §1]  Task: <T3xx> — SỬA LẦN 2.

Bạn đã báo done nhưng kiểm tra độc lập thấy lệch:
- <lệnh> → <output thật>
- <mô tả lệch>: ví dụ "cột số vẫn là string, numberFormat vẫn là @"

Yêu cầu:
1. Tái hiện đúng lỗi bằng test (nếu test hiện tại không bắt được lỗi này, đó chính là lỗi thứ hai:
   thiếu case — thêm case đó trước).
2. Sửa trong đúng file của task, không mở rộng phạm vi.
3. Chạy lại toàn bộ lệnh kiểm chứng của task và dán output.
4. Ghi rõ nguyên nhân gốc (root cause), không chỉ mô tả cách vá.
```

---

## §5. Mẹo để Codex không "sáng tạo" sai

| Tình huống | Cách chặn trong prompt |
|---|---|
| Tự đổi spec cho dễ làm | "Spec là nguồn sự thật; mâu thuẫn → DỪNG, không tự chọn" |
| Tự sửa file ngoài phạm vi | Danh sách Files + "cần ra ngoài → DỪNG" |
| Xoá test/ skip để xanh | "Không xoá/skip case; thêm case mới thay vì nới assert" |
| Báo pass không chạy | "Phải dán output thật; lead sẽ chạy lại" |
| Làm gộp nhiều task | "ĐÚNG MỘT task mỗi lượt" |
| Đoán định dạng khi mơ hồ | Trỏ thẳng spec §6 + reasonCode trong contract |
| Đụng backend cũ | "Không xoá cleaning/mutation; chỉ bỏ mount UI" |

Ngoài ra: với mỗi prompt, đính kèm **đường dẫn 3 file** (spec, tasks, contract) thay vì dán nội dung — Codex đọc file sẽ chính xác hơn bạn tóm tắt, và luôn có bản mới nhất.
