# Bàn giao Codex — feature 003 (một tab Nguồn)

Tài liệu này là **điểm vào duy nhất** cho người/agent thi công. Prompt chi tiết từng task: [agent-prompts.md](agent-prompts.md). Hợp đồng: [contracts/source-import.md](contracts/source-import.md). Task list: [tasks.md](tasks.md).

## 0. TL;DR

- Còn **7 task**: T301, T303, T304, T305, T306, T307, T308. T302 đã xong (19 test, exit 0).
- Đường nhập **vẫn ghi text** vì `packages.py` chưa nối `csv_typing` — đó là T304.
- `batch.py` (API AMD TokenLab) **bỏ**, không dùng nữa; đừng sửa, đừng chạy.
- Chất lượng được kiểm bằng 4 lớp ở §5; lớp quan trọng nhất: **bạn tự chạy lại lệnh kiểm chứng**, không tin báo cáo.

## 1. Hiện trạng

| Hạng mục | Trạng thái |
|---|---|
| `pbip_assistant/sources/preparation/csv_typing.py` | ✅ có, đúng spec §6, `build_typed_frame` + `describe_columns` |
| `tests/support/csv_typing_oracle.py` | ✅ oracle độc lập (không import module đang kiểm) |
| `tests/unit/test_csv_typing.py` | ✅ 19 test, `py -m unittest tests.unit.test_csv_typing -v` → OK |
| `packages.py` | ❌ vẫn `numberFormats: [["@"]]` cho CSV (T304) |
| `inventory.py` | ❌ chỉ đọc file trực tiếp trong 1 thư mục, chưa browse cây (T303) |
| task pane | ❌ vẫn 3 bước, còn `#preparation-wizard`, preview, câu hỏi định dạng (T305/T306) |
| `docs/current/*` | ❌ chưa cập nhật journey 2 bước (T301/T307) |
| Live Excel | `Not run` |

Working tree đã dirty từ trước (226 mục `git status`). **Không** reset/stash; mọi so sánh dùng baseline §4.

## 2. Nguyên tắc giao việc

1. **Một task = một agent = một lượt.** Không giao 2 task cho 1 agent (trừ T305+T306 vốn sửa cùng file).
2. Agent chỉ sửa file trong mục `**Files**` của task. Ra ngoài → dừng, báo.
3. TDD: test đỏ trước (đúng lý do), rồi code tối thiểu.
4. Không nới assert, không skip/xfail, không `except: pass`, không TODO để lại.
5. Không xoá backend cũ (`cleaning.py`, `mutation.py`, `journal.py`); chỉ bỏ mount UI.
6. Không đổi version/manifest/pyproject; không thêm dependency.
7. Báo cáo theo mẫu: `Task / Status / Tests (command + output) / Files / Deviations / Open`.

## 3. Sóng và cổng

| Sóng | Task | Lệnh cổng (chạy lại bằng tay) |
|---|---|---|
| A | T301 contract + docs | `py -m unittest tests.contracts.test_preparation_contracts tests.contracts.test_source_import_contracts tests.contracts.test_coordinator_dispatch -v` |
| B | T302 ✅ → đã xong | `py -m unittest tests.unit.test_csv_typing -v` |
| C | T303 browse/inventory | `py -m unittest tests.unit.test_preparation_browse tests.unit.test_preparation_inventory -v` |
| D | T304 typed frame | `py -m unittest tests.unit.test_preparation_packages tests.integration.test_preparation_api -v` |
| E | T305 UI browser | `node tests/taskpane/taskpane_assistant_browser.js` + `py -m unittest tests.taskpane.test_taskpane_js -v` |
| F | T306 bỏ bước 2 | `node tests/taskpane/taskpane_assistant_journey.js` + `node tests/taskpane/taskpane_preparation_wizard.js` |
| G | T307 tích hợp | `py tools/run_checks.py fast`, `py tools/run_checks.py runtime`, `py -m unittest discover -s tests -v` |
| H | T308 live | Excel thật, hoặc ghi `Not run` |

Không mở sóng sau khi sóng trước **chưa** qua cổng.

## 4. Quy trình 5 bước cho mỗi task

```powershell
# 0. Chụp mốc trước khi giao (một lần, đầu mỗi sóng)
py tools/review_003.py --snapshot

# 1. Giao prompt của task (agent-prompts.md §2) — agent sửa code
# 2. Rà tĩnh: chỉ file trong allowlist? có skip/TODO/assert rỗng?
py tools/review_003.py --task T304

# 3. Tự chạy lệnh cổng của task (không dán của agent)
py -m unittest tests.unit.test_preparation_packages -v

# 4. Đọc diff thật
git status --short          # đối chiếu với allowlist
git diff -- <file>          # đọc, không chỉ xem số dòng

# 5. Chấp nhận → ghi evidence vào acceptance.md; từ chối → prompt sửa (§4 agent-prompts.md)
```

## 5. Bốn lớp kiểm soát chất lượng

| Lớp | Ai làm | Bắt được gì | Chi phí |
|---|---|---|---|
| **L1. Cổng tự động** | Bạn chạy | Code sai, hồi quy | 1 lệnh/task |
| **L2. Rà tĩnh** (`review_003.py`) | Bạn chạy | Sửa ngoài phạm vi, skip test, assert rỗng, TODO | 2 giây |
| **L3. Review chéo** | Agent thứ hai, **cấm sửa file** | Test không thực sự kiểm hành vi, bỏ sót case spec | 5–10 phút |
| **L4. Tích hợp + live** | Bạn | Luồng thật trong Excel, DOM thật | cuối feature |

**L3 — prompt reviewer** (dán cho agent review, chỉ đọc):

```text
Bạn là reviewer độc lập. KHÔNG sửa file nào, không commit.

Đọc: specs/003-source-import-redesign/{spec.md §6, tasks.md <TASK>, contracts/source-import.md}
và diff của task: `git diff -- <các file trong allowlist>`.

Trả lời đúng 6 câu, mỗi câu kèm dẫn chứng file:dòng:
1. Có hành vi nào trong spec/task mà code KHÔNG làm? (liệt kê)
2. Có test nào pass dù code sai? (test tự chứng minh chính nó — ví dụ assert giá trị do code sinh ra)
3. Có case biên nào trong spec §6/Edge Cases chưa được test?
4. Có chỗ nào nới lỏng cổng an toàn (skip, except rỗng, ghi ngoài allowlist, log dữ liệu thô)?
5. Có thay đổi nào ngoài phạm vi task không?
6. Nếu phải bác bỏ task này, lý do duy nhất là gì?

Kết luận: ACCEPT | REJECT kèm 3 việc phải sửa, xếp theo mức nghiêm trọng.
```

**Nguyên tắc vàng:** một agent vừa viết code vừa tự chấm là vô nghĩa. Luôn có L1 + L2 do bạn chạy, và L3 do agent khác.

## 6. Definition of Done của cả luồng

- [ ] Tab Trợ lý: journey đúng `1. Nguồn → 2. Đề bài`; không còn `#assistant-step-clean`, `#preparation-wizard`.
- [ ] Bấm `Chọn thư mục` → duyệt được thư mục con, tick file, `Chọn tất cả` theo thư mục.
- [ ] Nhập CSV → sheet có number thật (`typeof === "number"`, format `General`), ngày là serial + `yyyy-mm-dd`, mã 0 đầu là text `@`.
- [ ] Sau nhập: `Đã nhập N file → M sheet`, khối `Ngoại lệ đã tự xử lý`, file lỗi ở `Bỏ qua`.
- [ ] Không còn preview, không câu hỏi định dạng, không chọn hệ ngày.
- [ ] `Tiếp tục: Đề bài` bật sau khi nguồn verified; nhánh workbook không đổi byte nào.
- [ ] `py tools/run_checks.py fast` + `runtime` xanh (chạy ngoài sandbox DSH).
- [ ] `acceptance.md` có evidence từng dòng; live Excel ghi `Passed` hoặc `Not run` + lý do.

## 7. Prompt mở đầu cho Codex (dán một lần)

```text
Repo: C:\Users\COLAIG\Downloads\power_bi. Feature 003 đang dở.

Đọc trước, theo thứ tự:
1. specs/003-source-import-redesign/CODEX_HANDOFF.md   ← quy trình + QC
2. specs/003-source-import-redesign/tasks.md           ← task của bạn
3. specs/003-source-import-redesign/spec.md (nhất là §6 luật kiểu)
4. specs/003-source-import-redesign/contracts/source-import.md
5. AGENTS.md

Bạn làm task <T3xx>. Chỉ sửa file trong mục **Files** của task đó. TDD, không skip test,
không đổi version/manifest, không thêm dependency. Xong thì chạy đúng lệnh **Kiểm chứng**
và báo cáo kèm output thật.

Nếu spec thiếu quyết định hoặc mâu thuẫn với code hiện tại: DỪNG, nêu 2 phương án, không tự chọn.
```

## 8. Dấu hiệu phải bác bỏ ngay

| Dấu hiệu | Vì sao |
|---|---|
| "Đã sửa xong" nhưng không có output lệnh | Không có bằng chứng |
| Test mới toàn `assert True` / so sánh với chính output của code | Test tự chứng minh |
| Diff chạm file ngoài allowlist | Trôi phạm vi, khó truy vết |
| Sửa `tasks.md`/`spec.md` cho khớp code | Đảo ngược nguồn sự thật |
| Bỏ qua `dateSystem` rồi mặc định 1900 | Sai 1.462 ngày |
| NumberFormat `"0"` hoặc `"@"` cho cột số | Quay lại đúng lỗi người dùng phàn nàn |

## 9. Nợ kỹ thuật đã biết (đừng cố sửa trong feature này)

- `fast` gate hiện fail trong sandbox DSH vì test ghi `%TEMP%`; chạy ngoài sandbox mới công bằng.
- `batch.py` + `runs/` là công cụ thử nghiệm đã bỏ; đã ignore trong git.
- Backend cleaning/preview vẫn tồn tại nhưng không còn đường UI; xoá là việc riêng, không thuộc 003.
