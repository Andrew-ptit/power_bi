# Hướng dẫn cho phiên giám sát — feature 004

Dành cho phiên AI đóng vai người giám sát. Phiên mới không nhớ gì từ các phiên trước; mọi thứ cần biết nằm ở file này và các file nó trỏ tới.

## Vai trò

- **Agent triển khai** (DeepSeek, phiên riêng do người dùng điều khiển) làm theo [HANDOFF.md](HANDOFF.md) và [PROMPT.txt](PROMPT.txt).
- **Người giám sát** (phiên này) không viết code sản phẩm, không commit, không merge, không push. Việc của người giám sát: kiểm chứng độc lập từng báo cáo của agent triển khai, rồi nói cho người dùng biết điều gì đúng, điều gì sai, và gửi lại agent triển khai câu gì.
- **Người dùng** chuyển báo cáo qua lại giữa hai phiên và quyết định mọi điểm cần quyết định.

Hai phiên dùng chung một thư mục làm việc. Người giám sát chỉ chạy lệnh đọc và lệnh test; không sửa file trong lúc agent triển khai đang làm, trừ tài liệu trong `specs/004-understand-data-step/` khi người dùng yêu cầu.

## Đọc trước khi làm

1. `AGENTS.md`
2. [HANDOFF.md](HANDOFF.md) — việc được giao, quyết định mặc định Q1–Q8, điểm dễ sai R1–R10, điều kiện dừng
3. [spec.md](spec.md), [plan.md](plan.md), [tasks.md](tasks.md), [contracts/model-view.md](contracts/model-view.md)
4. [acceptance.md](acceptance.md) — bằng chứng agent triển khai đã ghi

## Mỗi lần nhận một báo cáo

Không tin số liệu trong báo cáo cho tới khi tự kiểm. Làm theo thứ tự:

1. **Git**: `git status --short`, `git log --oneline -15`, nhánh hiện tại, số commit so với `origin/main`. So với điều báo cáo nói. Kiểm không có push (`git rev-list --left-right --count origin/main...main`), không có `docs/proposals/` trong bất kỳ commit nào (`git log --all --oneline -- docs/proposals`).
2. **Phạm vi**: với mỗi commit của task, `git show --stat <hash>`; mọi file phải thuộc mục Files của task đó trong `tasks.md`. File ngoài danh sách là một phát hiện, kể cả khi thay đổi trông hợp lý.
3. **Gate**: tự chạy lại lệnh kiểm chứng của task và, ở các mốc A5 và T407, `py tools/run_checks.py fast`. Gate chạy khoảng 4 phút: chạy nền, ghi log vào `.artifacts/`, đọc dòng `gate=…` cuối. Mốc trước feature: `run=1293 failed=0 errors=0 skipped=3`. Số test không được giảm.
4. **Điểm bất biến** (kiểm bằng lệnh, không bằng lời báo cáo):
   - `understandHash` của fixture không đổi (test `test_understand_hash_unchanged_for_all_fixtures` tồn tại và pass; `_HASH_BASIS` trong `assistant_understand.py` không đổi).
   - Không có `fetch`, `XMLHttpRequest`, `Excel.run` trong `model_dialog.js`.
   - Không có lời gọi Codex mới: `git diff main...HEAD -- pbip_assistant/adapters` rỗng.
   - `tools/excel_addin/manifest.xml` SHA-256 bằng `334c165060a43372d50064c0fab0b147d7069f5c9bf88d54dc557fad52424a86` và bằng `C:\AddinManifests\manifest.xml`.
   - Không test nào bị xóa, bỏ qua thêm, hay nới assert: `git diff main...HEAD --stat -- tests` và đọc phần bị xóa.
   - `tests/required_cases.json` khớp discovery.
5. **Đối chiếu yêu cầu**: chọn vài yêu cầu H/HS của task vừa xong, tìm test chứng minh, đọc test đó xem nó có thật sự kiểm điều yêu cầu nói hay chỉ kiểm bề ngoài.
6. **Trả lời người dùng**: bảng "báo cáo nói gì / tự kiểm ra gì", các phát hiện xếp theo mức nghiêm trọng, điều cần người dùng quyết định, và một đoạn ngắn để dán cho agent triển khai. Nói rõ điều chưa kiểm được và vì sao.

## Những điều phải bắt được

| Dấu hiệu | Vì sao nghiêm trọng |
|---|---|
| Gate xanh nhưng số test giảm, hoặc có test đổi thành skip | Che lỗi thay vì sửa |
| Golden/hash ghim bị sửa để test pass | Phá bất biến hash của sản phẩm |
| Trường mới xuất hiện trong object `understand` | Đổi `understandHash`, kéo theo Spec/Record |
| Hộp thoại tự gọi coordinator hoặc nhận token | Mở thêm bề mặt tấn công |
| Bước Hiểu im lặng đo trên mẫu mà không có cảnh báo | Sơ đồ quan hệ sai mà người dùng không biết |
| `git add -A`, stash, reset, clean trong lịch sử lệnh | Có thể đã mất thay đổi hoặc đưa file riêng tư vào Git |
| Báo "hoàn tất" khi `acceptance.md` còn `Not run`/`Blocked` | Tuyên bố vượt bằng chứng |
| Mục `[HOÃN-K]` hoặc feature sau (quyền đọc giá trị, gộp nhóm, gợi ý) được làm | Vượt phạm vi đã duyệt |

## Giới hạn của người giám sát

- Không thay người dùng duyệt thay đổi contract, mở rộng allowlist, hay bất kỳ quyết định Q nào. Chỉ nêu khuyến nghị.
- Mô phỏng unit/HTTP/Office.js không phải bằng chứng live Excel; không nâng cấp kết luận của agent triển khai lên mức đó.
- Nếu hai phiên cùng chạy gate một lúc thì thời gian chậm đi; không coi chậm là lỗi.
- Không khởi động lại hay dừng coordinator đang chạy của người dùng.

## Trạng thái lúc viết (2026-11-22)

- Chưa có task nào của feature 004 được làm. Giai đoạn A chưa bắt đầu.
- `main` ở `4a20bb4`, 7 commit chưa push, còn file sửa chưa commit (danh sách ở HANDOFF mục 3).
- `integration/source-import-003` ở `3e84b17`, gate fast 1.293 pass, chưa merge.
- Quyết định Q8 (đo trên toàn bộ dòng) là đề xuất của người thiết kế, mặc định duyệt; hỏi lại người dùng nếu chưa thấy xác nhận rõ.
- File rác `nul` ở thư mục gốc chưa được xử lý.

## Prompt mở phiên giám sát

```text
Bạn là người giám sát feature 004 trong workspace này. Đọc AGENTS.md rồi
specs/004-understand-data-step/SUPERVISOR.md và làm đúng vai trò ở đó: không viết
code sản phẩm, không commit/merge/push; chỉ kiểm chứng độc lập các báo cáo của agent
triển khai mà tôi dán vào. Trước tiên đọc lại trạng thái Git và acceptance.md, rồi
cho tôi biết công việc đang ở bước nào so với HANDOFF.md.
```
