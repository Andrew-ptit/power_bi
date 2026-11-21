# Specification quality checklist — feature 004

Rà ngày 2026-11-21 trên [spec.md](../spec.md). Người rà: tác giả spec (tự rà; chưa có reviewer độc lập).

## Nội dung

- [x] Nêu vấn đề của người dùng và bằng chứng trong code (§1)
- [x] Phạm vi trong/ngoài rõ; mục hoãn có thẻ nhận biết (§3)
- [x] Mỗi user story có independent test (§4)
- [x] Không lẫn quyết định của người dùng với đề xuất của người thiết kế (§2, §6, §10)

## Yêu cầu

- [x] Mỗi yêu cầu H01–H18 kiểm thử được
- [x] Luật `grainKind` tất định, có ngưỡng và trường hợp biên (§6)
- [x] Tiêu chí thành công đo được (§8)
- [x] Edge case được liệt kê (§4)
- [x] Supersession với 003 được ghi rõ (§9)

## Điểm còn mở (không chặn việc lập plan, chặn việc code)

- [ ] Nền triển khai chưa chốt: 003 chưa merge, cấu trúc đang được dọn (§10) → T400
- [ ] `DialogApi 1.2` và giới hạn message chưa kiểm chứng trên host (§10) → T406 bước 0
- [ ] Ngưỡng phân loại snapshot chưa kiểm bằng dữ liệu thật (§6)
- [ ] Ảnh hưởng của câu hỏi `grain` lên test ghim hash chưa biết (§10) → T403

## Ghi chú

Spec chưa qua `speckit-clarify` hay `speckit-analyze`. Feature directory được tạo thủ công theo cách của feature 003 (không tạo branch) vì working tree đang có nhiều thay đổi chưa commit.
