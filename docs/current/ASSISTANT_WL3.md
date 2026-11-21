# Assistant WL3 — Khung và Decision Brief

WL3 là nửa tất định của Brief, không gọi AI, không phải Excel runtime verification.
Đầu vào là raw tables, snapshot WL1, model WL2, DomainPack và prompt người dùng.

| Module | API |
|---|---|
| sources/assistant_pack.py | load_pack, validate_pack, select_pack |
| sources/assistant_findings.py | measure_set, formulas, number, scenario_fx_basis |
| sources/assistant_brief.py | build_brief, brief_hash, build_unresolved_decisions |

## DomainPack và nguồn số

Hai pack đóng băng là fin-pl-v1 và generic, được đọc qua core.resources.
Schema canonical assistant_domain_pack.schema.json đóng mọi object và required-all.
Pack chỉ khai báo câu chữ, metadata và formulaId; không chứa giá trị tiền hoặc status verified.
Validator chặn field/type lạ, reference sai, policy/option trùng, tiền trong chuỗi và prose.
Expression trong pack không được eval/exec; chỉ registry engine sở hữu phép tính.
Findings, consequence và scenario đều trích số từ assistant_findings kèm formulaId.
Nguồn lời văn là pack; nguồn evidence có thể data hoặc pack, không phát provenance llm.

## Phép đo và cách trình bày

FIN tính exact dedupe, dấu C/D, ánh xạ prefix và FX average theo tiền tệ từng dòng.
IC bị loại cả hai vế khỏi P&L nhưng vẫn giữ trong control total; orphan CC không bị bỏ.
Budget USD rate là input policy đóng băng 25180 từ công thức tham chiếu; không phải tổng tính từ CSV.
Budget USD/VND và mọi tổng tiền được cộng lại từ dữ liệu, không lấy từ pack/golden.
Bridge giữ Op+FX=Total=Variance. SALES tính Quantity×UnitPrice×(1−DiscountPct/100), giữ trả hàng âm.
VND xuất chuỗi nguyên, không tự làm tròn; percent/pp xuất hai chữ số thập phân ROUND_HALF_UP.
Giá trị không có cơ sở chia trả None; assembler không tạo finding số cho giá trị thiếu.
Numeric input hỗ trợ tối đa 50 coefficient digits và |exponent|/|adjusted|≤50, context riêng precision 300.
Vượt cap, thiếu rate được dùng hoặc mapping mơ hồ báo lỗi rõ; FIN bridge hiện chỉ một tháng USD/VND.

## Ba quyết định đã chốt

Period bao trọn các tháng chứa ngày phát sinh, thay vì chỉ đúng min/max ngày quan sát.
Status/provenance SP mô tả bằng chứng engine; riêng SP-4 verified/data chỉ sau check số học.
Câu chữ SP-4 từ pack vẫn authored, không vì thế được xác nhận đúng policy nghiệp vụ.
Scenario B gom FX vào Op, giữ nguyên tổng variance; không gọi đó là revalue constant currency.
Nhãn scenario lấy từ option SP-2 trong pack, các giá trị vẫn do engine tính.
SP missing_data giữ consequence null và out_of_scope; không tạo số LY hoặc price/volume/mix.

## Binding, override và kiểm tra

Assembler kiểm hash understand/snapshot và source profile binding, giữ input bằng deepcopy.
briefHash bind mọi field nội dung đã khai báo, gồm prompt, numeric values và câu chữ authored.
output_contract_override cho phép chọn lại grain/measure trong tập engine/pack đã hỗ trợ.
Đổi currency, period hoặc filters bị từ chối khi chưa có phép tính nguồn tương ứng.
policy_unresolved giữ lựa chọn null; helper decisions luôn chặn và không cấp approval/freeze/step.
Mutation bắt buộc thêm rebate vào clone bộ nhớ, dựng lại snapshot/model và kiểm số đổi đúng.
Không ghi hoặc dùng workbook người dùng; test kiểm SHA-256 và mtime nguồn/golden không đổi.

Chạy: py -m unittest tests.contracts.test_assistant_wl3 -v
Unit: py -m unittest tests.unit.test_assistant_pack tests.unit.test_assistant_findings tests.unit.test_assistant_brief -v
Hồi quy: py tools/run_checks.py fast

Chưa có LLM narrative, UI, HTTP/Office wiring, WL4 freeze/compile/Apply hoặc ghi workbook.
Các assertion engine không xác nhận policy nghiệp vụ, KPI hay khả năng chạy trong Excel/Power BI Desktop.
