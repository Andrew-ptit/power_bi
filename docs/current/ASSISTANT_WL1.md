# Assistant WL1 — Get Data

WL1 triển khai lớp engine đọc nguồn cho Pha 0 của ASSISTANT_FLOW_SPEC v1.1.
WL1 là static/engine slice, không phải Excel runtime verification.

| Module | API |
|---|---|
| sources/assistant_ingest.py | canonical_hash, add_csv, add_excel, add_folder, add_open_workbook, resolve, close |
| sources/assistant_profile.py | profile_table, build_snapshot, snapshot_hash |

CSV tái sử dụng profile_csv và CSV reader hiện có; XLSX tái sử dụng profile_workbook.
Không thêm parser OOXML, dependency, gọi AI hoặc thao tác ghi workbook.
XLSX biểu diễn scalar/cache/date do reader hiện có trả ra dưới dạng chuỗi.
Công thức thiếu cache có warning; adapter không tính công thức hoặc cam kết giá trị mới.
Workbook đang mở được đại diện bằng values selection do caller gửi; chưa có Office bridge mới.
Payload sampleOnly hoặc totalRows/totalColumns không khớp bị chặn để tránh coi mẫu là toàn nguồn.

## Nạp và bảo vệ nguồn

resolve nhận session dict và danh sách request kind csv/xlsx/folder/workbook.
session.root là gốc được chọn; locator của nguồn là đường dẫn tương đối gốc này.
Direct add nhận đường dẫn được chọn, dùng tên file làm locator công khai.
Có chặn traversal, đường dẫn vượt gốc, extension không hỗ trợ và dữ liệu lỗi.
Giới hạn là 64 MiB/file, 128 MiB/session; lỗi không tạo temp hoặc thêm source lỗi.
Folder nối file CSV theo tên tăng dần và yêu cầu header bằng nhau.
Folder kiểm lại bytes/mtime các member và tổng bytes thực tế trước khi phát hành kết quả.
Tên bảng trùng tạo requiresRename và giữ bảng cũ; snapshot bị chặn tới khi giải quyết.
close chỉ giải phóng state bộ nhớ do adapter sở hữu, không xoá file hoặc Save.

## Profile và hash

Raw rows giữ chuỗi, thứ tự và dòng trùng; thống kê dùng toàn bộ dữ liệu.
Sample là hai mươi dòng/giá trị đầu, không chọn ngẫu nhiên hoặc dedupe.
nullRate/distinctRatio dùng Decimal, quantize 0.001, ROUND_HALF_UP; distinct loại chuỗi rỗng.
type=text, role=null, roleStatus=unknown, evidence=[]; diễn giải nghiệp vụ thuộc WL2.
canonical_hash là SHA-256 của JSON UTF-8 với sort_keys, separators không khoảng trắng, allow_nan=False.
headerHash hash header; sampleHash hash hai mươi dòng đầu; fingerprint hash name/header/sample.
Source file hash canonical bytes.hex(); ID nội dung tất định, không uuid/random/time.
Snapshot sắp xếp nguồn và bảng theo tên; hashBasis gồm snapshot, sources, tables.
Theo quyết định người dùng, hash projection bỏ snapshot.createdAt và sources[].addedAt.
Output vẫn giữ timestamp; đổi timestamp không đổi hash, đổi nội dung nguồn vẫn đổi hash.

## CSV mơ hồ và golden

CSV delimiter mơ hồ chưa được nhận thành source/table; cần chọn một candidate rõ ràng.
Chọn lại trong cùng session thay pending profile và cho phép build_snapshot.
orders_ambiguous_discount.csv thực tế có delimiter semicolon duy nhất; auto/manual cùng fingerprint.
Theo quyết định người dùng, T-WL1-02 dùng CSV mơ hồ thực sự trong TemporaryDirectory.
Hai lựa chọn delimiter hợp lệ trên mẫu tạm tạo hai fingerprint khác nhau; không sửa golden.
Golden FIN/SALES đối chiếu đúng field WL1; không đối chiếu ID, timestamp hoặc suy luận WL2.

## Kiểm tra và giới hạn

Chạy: py -m unittest tests.contracts.test_assistant_wl1 -v
Unit: py -m unittest tests.unit.test_assistant_ingest tests.unit.test_assistant_profile
Hồi quy: py tools/run_checks.py fast
Chưa làm WL2 trở lên, UI/navigator, HTTP wiring, Office runtime hoặc ghi workbook.
Các test dùng nguồn synthetic, không dùng workbook người dùng hoặc xác nhận KPI/nghiệp vụ.
Chưa kiểm chứng Excel/Power BI Desktop; không diễn giải engine test thành live journey.
