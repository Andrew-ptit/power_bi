# Assistant WL2 — Hiểu dữ liệu

WL2 là engine slice tất định, không gọi AI, không phải Excel runtime verification.
Phạm vi là Pha 1 của ASSISTANT_FLOW_SPEC v1.1; đầu vào là raw tables và snapshot từ WL1.

| Module | API |
|---|---|
| sources/assistant_keys.py | candidate_keys, foreign_key_candidates, relationships, key_report, has_finance_schema |
| sources/assistant_roles.py | structural_roles, column_roles, assumption_ledger, warning_classification |
| sources/assistant_understand.py | build_understand, understand_hash |

Assembler xác minh hash snapshot và các field profile WL1 sở hữu trước khi bind raw table copies.
Hỗ trợ snapshot WL1 runtime và snapshot fixture canonical; không đọc fixture hoặc file nguồn trong assembler.
ID được bind từ snapshot đã kiểm, không hardcode ID/tên fixture hoặc mutate raw/snapshot.
snapshotHash trong output luôn bằng hash của snapshot được caller cung cấp.

## Khóa và quan hệ

Khóa ứng viên đo trên toàn bộ dòng thô: unique đúng tuyệt đối, không null; không dùng ratio làm tròn để quyết định.
Composite key phải tối thiểu; GL.(DocNo,LineNo) không unique và GL raw vẫn có 31 dòng.
View quan hệ ledger được nhận từ schema: exact-row dedupe, Month từ các ngày ISO nhất quán.
FX lookup dùng các dòng RateType=average. Các bảng khác không bị tự dedupe.
orphan đếm số dòng trái không có tuple khóa bên phải; overlap=(rows-orphan)/rows.
Overlap và inflationFactor dùng Decimal, quantize 0.001, ROUND_HALF_UP; score=overlap.
Fan-out mô phỏng left join bằng multiplicity, không tạo payload joined rows.
rowsAfter>rowsBefore luôn fanOutRisk=high và needs_confirm.
Theo quyết định người dùng, cardinality phản ánh uniqueness: 1:1, N:1, 1:N hoặc N:N.
Generic có orphan cần xác nhận; finance pack dùng ngưỡng overlap 0.5 trên phân số gốc.
Finance schema được dò từ cột tài khoản và FX, không dựa vào tên bảng.
Candidate zero/low overlap vẫn được báo; không coi zero overlap là bằng chứng role/FK thực.

## Vai, nghĩa cột và ledger

Fact lớn nhất cần repeated FK và ít nhất hai bảng đích có overlap dương; được phép có row PK unique.
Không đủ bằng chứng fact thì báo lỗi, không gán theo tên.
Dim dựa trên full raw PK; partial non-PK lookup từ fact ưu tiên hơn candidate N:N phụ.
Bridge chỉ khi có N:N; mọi role có evidence đo được và confidence 0..1, không verified.
column_roles trả proposal riêng; không sửa type/role trong snapshot WL1.
Currency ưu tiên role currency khi đồng thời là khóa, vẫn giữ evidence khóa theo lựa chọn người dùng.
Date/amount dùng ngưỡng 95%; percent theo tên; text cần distinctRatio ít nhất 0.5.
Không đủ bằng chứng thì null/unknown; Segment2 giữ unknown.
Ledger chỉ phát data và pack thực sự được chọn; không bịa history/user hoặc provenance llm.
Thiếu average được dùng là blocker; closing hoặc rate không dùng chỉ warning.
Diagnostic không echo currency cell tùy ý, chỉ mã có format phù hợp hoặc thông báo đếm chung.

## Hash, giới hạn và kiểm tra

understandHash bind snapshotHash, pack, roles, relationships, assumptions, warnings và variant metadata.
Hash dùng canonical_hash của WL1; cùng input cho cùng output; nguồn vẫn chỉ đọc.
Composite pool tối đa 16 cột, 100.000 combinations và 5.000.000 row×column evaluations mỗi bảng.
FK/relationship giới hạn 10.000 candidate và 5.000.000 row×column evaluations; vượt cap báo lỗi rõ.
Golden chỉ so cặp/giá trị dẫn xuất đã quy định; cho phép superset, không so prose role/ledger/warning/hash.
Chạy: py -m unittest tests.contracts.test_assistant_wl2 -v
Unit: py -m unittest tests.unit.test_assistant_keys tests.unit.test_assistant_roles tests.unit.test_assistant_understand -v
Hồi quy: py tools/run_checks.py fast

Chưa làm WL3+, Decision Brief, UI, HTTP/Office wiring hoặc ghi workbook.
Không gọi AI/LLM/Codex/network; không xác nhận policy nghiệp vụ hoặc KPI.
Các test synthetic và engine không thay cho kiểm chứng Excel/Power BI Desktop.
