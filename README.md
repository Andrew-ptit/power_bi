# Local Data Copilot

Trợ lý local cho CSV/XLSX, Power BI Project và Excel task pane. Xem [trạng thái hiện tại](docs/current/CURRENT_STATUS.md) và [hợp đồng chức năng](docs/current/README.md). Lịch sử thay đổi được lưu trong Git; cây thư mục chỉ giữ code, tài liệu và công cụ còn sử dụng.

## Chạy ứng dụng

Python 3.13; Python runtime dùng standard library. Node phục vụ kiểm tra JavaScript. Excel runtime cần Windows/Excel Desktop; TMDL cần .NET 8 và bridge đã build.

```powershell
py -m pbip_assistant --pbip .\tests\fixtures\pbip\Retail --excel .\tests\fixtures\source\orders_synthetic.xlsx --csv .\tests\fixtures\source\orders_synthetic.csv
py -m pbip_assistant.webapp --port 8765 --open
py -m pbip_assistant.excel_addin_server
```

Web UI xử lý nguồn local. Task pane gửi prompt và mẫu workbook giới hạn qua Codex khi người dùng yêu cầu Analyze. Xem [runbook Excel](tools/excel_addin/README.md) để cấu hình HTTPS/catalog.

```powershell
dotnet restore .\tools\tmdl_bridge\TmdlBridge.csproj --locked-mode
dotnet build .\tools\tmdl_bridge\TmdlBridge.csproj -c Release --no-restore
```

NuGet restore chỉ phục vụ setup; bridge chạy offline.

## Kiểm tra

```powershell
py tools/run_checks.py fast
py tools/run_checks.py runtime
$env:PQPC_LIVE_CODEX = "1"
py tools/run_checks.py codex
Remove-Item Env:PQPC_LIVE_CODEX
py -m unittest discover -s tests -v
```

`fast` chạy unit/contracts/HTTP/Office.js simulation và 12 script task-pane JS. `runtime` chạy Excel/.NET tuần tự; Codex cần opt-in. UI Excel thật có [harness riêng](tests/live/README.md).

## Thư mục

| Thư mục | Nội dung hiện dùng |
|---|---|
| `pbip_assistant/` | Product code theo domain/feature; xem [kiến trúc](docs/current/ARCHITECTURE.md) |
| `docs/current/` | Hợp đồng, kiến trúc, trạng thái và hướng dẫn hiện hành |
| `tests/` | Unit, contracts, integration, journeys, task pane, runtime, support và fixture tổng hợp |
| `tools/` | Gate kiểm tra, Excel helper, cấu hình add-in và TMDL bridge |
| `examples/` | Lệnh mẫu và dữ liệu mẫu chạy lại được; generator fixture chỉ dùng cho test nằm trong `tests/support/` |
| `third_party/` | License của tài nguyên bên thứ ba đang sử dụng |

Workbook/CSV/ảnh cá nhân và certificate là dữ liệu local riêng. Nguồn Excel/PBIP mặc định chỉ đọc; AI không cấp approval. Typed history dùng Custom XML/CAS. Advanced M đang tạm hoãn kiểm chứng theo yêu cầu người dùng.
