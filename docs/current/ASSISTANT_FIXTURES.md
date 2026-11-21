# Assistant fixtures — hợp đồng dữ liệu WL1–WL7

Bộ này hỗ trợ ASSISTANT_FLOW_SPEC v1.1 bằng dữ liệu synthetic và assertion độc lập.
Đây là fixture pack, không phải runtime verification.

## Thành phần

| Vùng | Nội dung |
|---|---|
| tests/fixtures/assistant/tp-fin | Bảy CSV, danh mục công thức và chuỗi artifact P&L |
| tests/fixtures/assistant/tp-sales | Bảy CSV, gồm ba file Orders theo tháng; generic mode |
| tests/fixtures/assistant/tp-unknown | Brief/chốt chưa đủ policy; không ép người dùng chọn |
| tests/fixtures/assistant/variants | Tám nhánh lỗi, cảnh báo và stale |
| tests/fixtures/assistant/schema | Mười chín schema đóng, required-all |
| tests/fixtures/assistant/manifest.json | Bảng anchor và bốn mươi lăm case sản phẩm |

Oracle tài chính nằm ở tests/support/assistant_fin.py; oracle doanh số nằm ở
tests/support/assistant_sales.py. Cả hai dùng Decimal và chỉ đọc CSV đã lưu trong fixture.
tests/support/assistant_variants.py dẫn xuất nhánh lỗi từ artifact đã lưu.
Không có phụ thuộc thư mục giao việc hoặc workbook người dùng khi chạy test.

## Số và fingerprint

Mọi giá trị phân tích có formulaId trỏ tới formulas.json, basis engine-decimal.
Anchor được kiểm bằng hằng số độc lập trong test; không import ANCHORS để tự đối chiếu.
Số đối soát tham chiếu được kiểm ban đầu bằng data/anchors_check.py của gói giao việc.
Tiền được lưu bằng chuỗi số thập phân; không dùng float cho tiền.
Các tỷ lệ profile là metadata số được lượng tử hoá theo contract.

JSON: UTF-8 không BOM, LF, sort_keys, indent hai khoảng trắng và newline cuối.
Hash canonical dùng JSON sort_keys, separators không khoảng trắng và allow_nan=False.
Tiền tố sha256: nối với digest SHA-256. hashBasis liệt kê field được bind vào hash.
Chuỗi hash nối snapshot, understand, brief, decisions, spec, preview, approval và record.
Nguồn thay đổi hoặc quyết định thay đổi phải làm stale artifact tương ứng.

## Ánh xạ kiểm tra

| Tầng | Hợp đồng được kiểm |
|---|---|
| WL1 | Danh sách nguồn, schema/profile, append theo tên, fingerprint, các nhánh bị chặn |
| WL2 | Vai, khóa/quan hệ, fan-out, role unknown và provenance |
| WL3 | Output contract, sub-problem A/B, findings/formula, missing_data, hai loại insight |
| WL4 | Quyết định một-một, step DAG, group trước Budget join, invalidate |
| WL5 | Values-only, nguồn bất biến, control total và Op+FX=Total=Variance |
| WL6 | Approval bind spec/preview, single-use, sheet mới, không tự Save |
| WL7 | Delta, Decision Record, nhãn và stale |
| E2E | Tính nhất quán artifact FIN/SALES/UNKNOWN/NOPACK, chưa phải live journey |

## Chạy và tái sinh

Chạy: py -m unittest tests.contracts.test_assistant_fixtures -v
Gate hồi quy: py tools/run_checks.py fast
Tái sinh FIN/UNKNOWN: py -m tests.support.assistant_fin
Tái sinh SALES: py -m tests.support.assistant_sales
Tái sinh biến thể sau artifact gốc: py -m tests.support.assistant_variants

Schema decisions dùng brief.schema.json::$defs.decisionsDocument, không có file thứ hai mươi.
Các nhánh variant cùng schema artifact gốc; field variantOf/variantReason được bind hash.

## Giới hạn

Các assertion kiểm dữ liệu hợp đồng, không thực thi connector, Typed Steps, Preview hay Apply.
Chưa có code feature từ task này; không có UI hoặc engine runtime được bổ sung.
Schema tạm ở tests/fixtures/assistant/schema; khi có code sẽ chuyển sang pbip_assistant/schemas.
Không suy ra xác nhận nghiệp vụ hoặc runtime từ nhãn verified trên luật dữ liệu synthetic.
Suy luận AI không được gán verified; missing_data giữ out_of_scope và không bịa giá trị.
TP-SALES không có FX; bridge không áp dụng và các trường tiền tương ứng là null.
TP-UNKNOWN giữ freezeBlocked khi policy chưa chốt; checklist là câu hỏi để người dùng rà soát.
