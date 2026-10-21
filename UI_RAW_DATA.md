# UI source-only — wireframe và hợp đồng kiểm thử

| Thuộc tính | Giá trị |
|---|---|
| Phạm vi | S1 — Chọn đầu vào; S2 — Data profile |
| Runtime | Web app cục bộ tại `127.0.0.1`, Python standard library |
| Nguồn | `.xlsx`, `.csv`; nhiều file trong một phiên |
| Trạng thái | Functional prototype; không phải toàn bộ W-17 |
| Ngoài phạm vi | PBIP, Power BI Desktop, AI, mapping nghiệp vụ, DAX/M/TMDL/PBIR, apply |

## Chạy ứng dụng

```powershell
py -m pbip_assistant.webapp --port 8765 --open
```

Nếu không dùng `--open`, mở thủ công [http://127.0.0.1:8765/](http://127.0.0.1:8765/). Dừng bằng `Ctrl+C`. File được upload vào thư mục tạm của tiến trình và bị xóa khi server dừng; nguồn gốc không bị sửa.

## Wireframe chức năng

```text
┌──────────────────────────┬──────────────────────────────────────────────────────┐
│ DATA PROFILER · LOCAL    │ RAW DATA · READ ONLY                                 │
│                          │ Kiểm tra dữ liệu trước khi phân tích                  │
│ 01 Nguồn dữ liệu         ├──────────────────────────────────────────────────────┤
│ 02 Data profile          │ [ Kéo/thả XLSX/CSV | Chọn file từ máy ]              │
│ 03 Mapping & AI (khóa)   │                                                      │
│                          │ FILES                                                │
│ Excel/CSV     Sẵn sàng   │ [file.xlsx] [read-only note]                  [x]    │
│ Power BI      Chưa chạy  │ [file.csv ] [encoding][delimiter][header]     [x]    │
│ AI            Chưa chạy  │                                                      │
│                          │                         [ Phân tích dữ liệu → ]        │
├──────────────────────────┼──────────────────────────────────────────────────────┤
│ Bản sao tạm; không ghi   │ Metrics: nguồn · dòng · cột · vấn đề                 │
│ ngược vào nguồn          │ Datasets | Preview | Cột | Vấn đề | So schema        │
└──────────────────────────┴──────────────────────────────────────────────────────┘
```

## Luồng và trạng thái

1. Người dùng kéo/thả hoặc chọn nhiều file.
2. Trình duyệt gửi từng file tới loopback server bằng token của phiên.
3. CSV có thể chọn encoding, delimiter và header row; XLSX profile tất cả worksheet.
4. Người dùng bấm **Phân tích dữ liệu**.
5. UI hiển thị:
   - tổng file/dòng/cột/vấn đề;
   - preview tối đa 20 dòng hợp lệ;
   - profile từng cột: kiểu, null, duplicate, sample giới hạn;
   - worksheet/table/formula-cache warning;
   - row-width error và mã lỗi chặn;
   - so schema giữa nhiều dataset.
6. CSV mơ hồ hoặc lỗi đọc giữ nguyên file trong phiên để người dùng đổi tùy chọn và chạy lại.

| Trạng thái | Ý nghĩa UI |
|---|---|
| `needs_input` | Chưa có file |
| `profile_ready` | Profile tĩnh hoàn tất, không có lỗi chặn mapping |
| `needs_input_fix` | Vẫn hiện profile khả dụng nhưng chỉ rõ lỗi cần sửa |
| `not_run` | AI, PBIP và Desktop chưa chạy; không được hiển thị như pass |

## Ranh giới an toàn

- Server chỉ bind `127.0.0.1` hoặc `::1`; không có tùy chọn bind LAN.
- Không dùng CDN, font hoặc API bên ngoài; CSP chỉ cho phép `self`.
- Mutation API cần token ngẫu nhiên và chặn origin ngoài loopback.
- Tên file được loại path traversal; chỉ `.xlsx` và `.csv`.
- Giới hạn 64 MiB/file, 128 MiB/phiên, preview tối đa 50 dòng ở API và 20 dòng ở UI.
- Access log không ghi file name, query, request body hoặc giá trị ô.
- Preview raw row là opt-in của UI; parser gọi theo mặc định không trả raw records.

## Kiểm thử nghiệm thu

| Nhóm | Tình huống | Điều kiện đạt |
|---|---|---|
| Upload | XLSX + CSV cùng phiên | Hai nguồn xuất hiện riêng, hash/size có mặt |
| Profile | Fixture chuẩn | Preview, cột, null/duplicate và schema comparison hiển thị |
| Retry | CSV delimiter mơ hồ | Có mã lỗi; chọn delimiter rồi chạy lại thành công |
| Negative | Extension/path traversal/token/origin sai | Request bị chặn, không tạo file tạm |
| Privacy | Parser mặc định và access log | Không trả preview mặc định; không log cell/body |
| Cleanup | Xóa file/reset/dừng server | Bản sao tạm được xóa |
| Regression | Toàn bộ suite | 98 test đạt, 1 skip do quyền symlink tại 03/10/2026 |

Browser walkthrough/chụp màn hình cần một phiên Browser khả dụng. Trong lần triển khai này, nghiệm thu tự động dùng HTTP server thật, DOM asset checks, JavaScript syntax check và integration tests; không ghi nhận browser walkthrough là đã chạy.
