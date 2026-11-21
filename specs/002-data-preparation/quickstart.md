# Kiểm thử luồng chuẩn bị dữ liệu — feature 002

Luồng đã được nối để người dùng tự kiểm thử trực tiếp. Trạng thái nghiệm thu Excel thật vẫn là `user_pending`; các phần hướng dẫn live bên dưới là tài liệu kỹ thuật, không phải yêu cầu agent tự điều khiển Excel.

1. Mở workbook mới hoặc workbook có sẵn, đóng rồi mở lại panel **Reqwise-excel-mcp**.
2. **Nguồn → Chọn thư mục**: tick từng file hoặc **Chọn tất cả**, xem tên sheet dự kiến, bấm **Nhập các file đã chọn**. CSV tạo một sheet; XLSX nhập toàn bộ nhóm sheet, có tiến độ theo file.
3. **Làm sạch** tự quét các sheet. Trả lời các điểm chưa rõ, xem ngoại lệ và bản xem trước rồi **Áp dụng**; nếu không cần sửa thì **Dùng dữ liệu này**.
4. Chọn **Đề bài** và nhập bài toán. **+ Thêm nguồn** mở Browse để nhập bổ sung, sau đó quét/duyệt lại dữ liệu liên quan.
5. Các nút **↶ Khôi phục / ↷ Làm lại** dùng lịch sử trong phiên. Khi phiên hết hạn hoặc workbook khác với binding đã lưu, **Bắt đầu phiên mới với workbook này** tạo phiên mới sau hành động rõ ràng của người dùng.

Không tự Save. File nguồn và sheet hiện có không bị ghi đè; sheet cá nhân được giữ nguyên và có bản kết quả riêng. Cấu trúc không thể bảo toàn, dữ liệu vượt giới hạn hoặc thay đổi sau duyệt sẽ bị chặn rõ ràng. Ghi/đọc lại chưa xác định không được tự chạy lại. Kiểm thử trực tiếp và báo lỗi thuộc người dùng theo chỉ dẫn mới nhất.

## Readiness and context

2026-11-14 read-only check: Python 3.13.5, Node v24.13.1; existing gate certificate/key paths present. This is setup evidence only, not Excel/Codex/auth/runtime readiness or qualification. No user workbook opened/read. New native import/restore capability Not run.

Spec Kit feature context without changing pinned baseline:

```powershell
$env:SPECIFY_FEATURE_DIRECTORY='specs/002-data-preparation'
$env:SPECIFY_FEATURE_NO_PERSIST='1'
./.specify/scripts/powershell/check-prerequisites.ps1 -Json -RequireTasks -IncludeTasks
```

## Focused tests (after corresponding tasks exist)

```powershell
py -m unittest tests.contracts.test_preparation_contracts tests.unit.test_preparation_journal tests.unit.test_preparation_inventory tests.unit.test_preparation_cleaning -v
py -m unittest tests.integration.test_preparation_sessions tests.integration.test_preparation_import tests.integration.test_preparation_apply tests.integration.test_preparation_recovery -v
node tests/taskpane/taskpane_preparation_runtime.js
node tests/taskpane/taskpane_preparation_wizard.js
```

Expected: all assertions pass, no unsupported/source-changed/backup-failed/stale action writes; personal source unchanged; formula/format round-trip matches hand oracle. During RED, observe missing intended behavior before code; not arbitrary test typo/import error as success.

## Existing regression gates

```powershell
py tools/run_checks.py fast
py tools/run_checks.py runtime
py -m unittest discover -s tests -v
```

Run at exact-current integrated revision; retain stdout summaries/error codes and time, not raw private contents. All existing 12 taskpane scripts stay covered, plus preparation scripts.

## Synthetic live gate

Existing harness instructions: `tests/live/README.md`. T002 extends scenario selection and fixture generation for preparation without replacing defaults. Only after that task adds `--scenario preparation`, execute a fresh ignored output directory:

```powershell
py -m tests.live.create_fixture .artifacts/gate-preparation-<run-id>/fixture <run-id>
py tools/live_excel_gate.py --run-id <run-id> --out .artifacts/gate-preparation-<run-id> --scenario preparation
```

Fixture generator/scenario must include preparation's dependency-complete source files and oracle. Implementer drives unique synthetic manifest in actual Excel using existing harness, never user's workbook, shared production manifest overwrite or shared coordinator bootstrap. Server command alone does not start Excel or establish live pass. Use existing computer-use workflow if UI needed; cannot delegate required verification to user.

Expected complete/pass after success and recovery: import groups and literal CSV, answer/edit/review, both cleanup target strategies, full read-back, undo/redo, taskpane reload, stale/manual conflict, quota and expired tokens, partial/unknown failure path. Original source fingerprints unchanged. Native API fidelity is a gate; API documentation/export/HTTP/fake tests insufficient.

Codex: Not applicable to local preparation. Advanced M: Deferred by user. Missing Excel/auth/UI gate: Blocked/Not run with exact reason. Runtime artifacts/backups/gate secrets stay in ignored marked temp/.artifacts, no raw workbook committed.
