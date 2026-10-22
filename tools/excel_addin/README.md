# Chạy thử W-21 trong Excel Desktop

## Điều kiện

- Windows và Excel Desktop Microsoft 365/Office 16 có `XLOOKUP`, `LET`, `IFS` và `Formula2`.
- Python chạy được lệnh test của repository.
- Fixture đã lưu local: `tests/fixtures/excel/excel_mcp_sales_input.xlsx`.
- Ít nhất một cổng trong pool `3079` xuống `3072` còn trống.

## 1. Tạo HTTPS certificate cho localhost

Mở PowerShell tại repository root:

```powershell
.\tools\excel_addin\setup-dev.ps1 -Trust
```

Windows có thể hiện hộp thoại trust certificate. Chỉ đồng ý nếu đường dẫn script đúng repository này. Private key nằm trong `tools/excel_addin/.certs/` và không được commit/chia sẻ.

## 2. Chạy coordinator

```powershell
py -m pbip_assistant.excel_addin_server
```

Giữ cửa sổ này mở. Coordinator in ra cổng/channel đã chọn, tự đồng bộ manifest repository/catalog và xác minh SHA-256. Đóng/mở lại task pane, rồi kiểm tra `/api/health` trên cổng được in ra.

## 3. Sideload manifest

Manifest: `tools/excel_addin/manifest.xml`.

Trong Excel Desktop, dùng **Home/Insert → Add-ins → More Add-ins/My Add-ins → Upload My Add-in** nếu tenant hiển thị lựa chọn này, rồi chọn manifest. Nếu Excel của tổ chức không có nút upload, cấu hình một **Trusted Add-in Catalog** theo hướng dẫn Microsoft và trỏ catalog đó tới thư mục chứa manifest; việc này phụ thuộc chính sách Office của máy.

Nếu nút **Upload My Add-in** bị ẩn nhưng máy cho phép developer sideload, dùng coordinator đang chạy và lệnh sau:

```powershell
npx --yes office-addin-debugging@7.0.1 start .\tools\excel_addin\manifest.xml desktop `
  --app excel `
  --document .\w21_manual_fixture\excel_mcp_sales_input.xlsx `
  --no-debug --no-live-reload --dev-server-port <PORT_DUOC_IN_RA>
```

Lệnh này đăng ký manifest dưới user hiện hành và mở một bản fixture tạm trong Excel. Khi kết thúc demo, gỡ đăng ký bằng:

```powershell
npm run excel:addin:stop
```

Sau sideload, mở add-in **Reqwise-excel-mcp**. Nếu panel trắng, mở URL task pane mà coordinator vừa in ra một lần trong browser để xác nhận certificate đã trust, sau đó đóng/mở lại panel.

## 4. UAT happy path

1. Tạo một bản fixture dùng riêng để test, không dùng dữ liệu thật:

   ```powershell
   py -m examples.excel_mcp_fixtures .\w21_manual_fixture
   ```

2. Mở `w21_manual_fixture\excel_mcp_sales_input.xlsx` trong Excel và đảm bảo file đã Save.
3. Mở task pane. Kiểm tra panel hiện `EXCEL CONNECTED`, `2 table`, `Sales`.
4. Giữ prompt mẫu và bấm **Phân tích workbook**.
5. Kiểm tra 4 công thức, nhãn **SIMULATED**, 6 dòng preview và thông báo chưa ghi Excel.
6. Tick xác nhận rồi bấm **Duyệt, tạo copy và chạy Excel**; xác nhận hộp thoại.
7. Kết quả đạt khi panel hiện **EXCEL VERIFIED**, `Khớp manifest`, và tạo file mới cạnh fixture có tên `excel_mcp_sales_input_AI_copy_*.xlsx`.
8. Mở file copy, xác nhận `SalesTable` có bốn cột mới và giá trị tương ứng. File nguồn phải vẫn chỉ có 9 cột.

## 5. Negative checks tối thiểu

- Đổi tên `SalesTable` hoặc một header trong một fixture dùng riêng: plan phải `SCHEMA_MISMATCH`, nút apply bị khóa.
- Sửa prompt sau khi plan xuất hiện: approval cũ phải mất hiệu lực và yêu cầu phân tích lại.
- Bỏ chọn một operation: backend phải từ chối `APPROVAL_SCOPE`.
- Mở workbook chưa Save hoặc URL cloud: `WORKBOOK_UNSAVED`/`REMOTE_WORKBOOK_UNSUPPORTED`.
- Nếu Excel không hỗ trợ công thức mới: `FORMULA_UNSUPPORTED`; không có nhãn verified.

## 6. Dừng và cleanup

- Nhấn `Ctrl+C` ở coordinator.
- Xóa add-in khỏi **My Add-ins** nếu không dùng nữa.
- Xóa các fixture/copy do chính buổi test tạo khi đã review xong.
- Có thể xóa `tools/excel_addin/.certs`; certificate đã trust trong Windows certificate store phải được gỡ riêng nếu không còn dùng. Không chạy `dotnet dev-certs --clean` vì lệnh đó xóa rộng các HTTPS dev certificate khác trên máy.

## Trạng thái bằng chứng

Unit/API test và isolated COM smoke không thay thế bước sideload UI. Chỉ đóng GX1 khi bảng W21-AC trong `W21_EXCEL_TASKPANE_SPEC.md` có cả bằng chứng task pane và runtime Excel Desktop.
