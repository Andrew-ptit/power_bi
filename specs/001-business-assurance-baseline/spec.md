# Feature Specification: Baseline tin cậy nghiệp vụ và xác minh ghi Excel

**Feature directory**: `specs/001-business-assurance-baseline/`  
**Git branch khi lập tài liệu**: `main` — không tạo/chuyển branch.  
**Created**: 2026-11-05 (Asia/Saigon)  
**Status**: Planning baseline — chưa triển khai, chưa có bằng chứng nghiệm thu.

## Input và thẩm quyền

Đầu vào là bản đề xuất 9 mục người dùng đính kèm ở lượt yêu cầu `$speckit-plan` rồi `$speckit-tasks`, cùng kết quả rà soát P1–P10 trong hội thoại. Yêu cầu này cho phép lập tài liệu từ baseline; không phải bằng chứng đã triển khai hoặc đã nghiệm thu và không cấp phép chạy Excel/workbook thật.

Các ký hiệu B01–B09, US1–US9 và S01–S27 dưới đây chỉ là alias cục bộ của feature để truy vết. Không cấp lại FR/AC hoặc BPMN task ID. Khi triển khai, cập nhật hợp đồng tại `docs/current/ASSISTANT_V2_BUILD_SPEC.md`, `PQ_CODE_M_SPEC.md`, `PROBLEM_CHAIN_SPEC.md`, `TYPED_STEP_DIAGNOSTICS_SPEC.md` và `TASKPANE_UI.md`; giữ các ID hiện có. `CURRENT_STATUS.md` tiếp tục sở hữu trạng thái kiểm chứng. Không có yêu cầu trong tài liệu này tự động thay thế hợp đồng hiện hành.

## Scope

Làm rõ quyền duyệt ngưỡng, câu hỏi bắt buộc, khóa nối thiếu; thống nhất mức xác minh ghi và phục hồi chỉ đọc; báo giới hạn trước duyệt; nói rõ tác động Quay về, khả năng tái sử dụng và nhãn kết quả. Giữ kiến trúc hiện có, catalog 15 operation/10 expression/8 function, Decimal dạng Text, approval dùng một lần và ngoại lệ Advanced M đã được chốt.

Không làm scheduler, tự Refresh, nhập JSON thành pipeline mới, tăng catalog/giới hạn, sandbox M, backup/rollback, cộng tác nhiều người, DB hoặc lưu raw result vào lịch sử. Không phục hồi annotation/runtimeSummary đã hủy. Live verification Advanced M vẫn Deferred theo chỉ dẫn hiện hành; không tự khởi động lại hạng mục đó. Việc thiết kế và kiểm tra mô phỏng không đóng gate live.

## User Scenarios & Testing

### US1 — Duyệt ngưỡng có hiểu biết (Priority: P1; B01; audit P1)

Là người làm data, tôi cần thấy cơ sở và ngưỡng đánh giá trước khi một nhánh được dùng để chốt, để AI không tự đặt mức sai lệch chấp nhận được.

**Independent Test**: một đơn KH01/100 nối hai bản ghi KH01; đánh giá hai policy khác nhau trên cùng fixture, với và không có xác nhận đúng policy.

**Acceptance Scenarios**:

- **S01** Given ngưỡng AI đề xuất chưa được duyệt, When engine tính/hiện A/B, Then có thể xem số nhưng không mang nhãn đạt theo policy đã duyệt và không freeze/approve/write.
- **S02** Given policy đã được người dùng duyệt đúng nhánh, When đổi tolerance, đơn vị, rationale, ngưỡng fan-out, câu trả lời, nguồn hoặc plan, Then review cũ hết hiệu lực; không tự nâng ngưỡng để đạt.
- **S03** Given không có tổng kiểm soát áp dụng, When người dùng xác nhận riêng, Then vẫn `unverified`; không biến hard failure thành pass và không tự chèn tolerance mặc định 0,01.

### US2 — Biết chính xác mức kiểm sau ghi (Priority: P1; B02; audit P2)

Tôi cần phân biệt đã đọc mẫu với đã đối chiếu toàn bộ kết quả, trên Trợ lý, Typed và M nâng cao.

**Independent Test**: 25 dòng dữ liệu, giá trị sai ở dòng 25; luồng đọc mẫu không được báo toàn bộ khớp, luồng full verification phải phát hiện sai lệch.

**Acceptance Scenarios**:

- **S04** Given kết quả đúng, When đọc lại toàn bộ header/values/đích và marker nếu có, Then chỉ báo fully verified khi từng giá trị khớp chuẩn so sánh có phiên bản; không lấy số chiều dự kiến làm số đo thực.
- **S05** Given dòng 25 sai, marker sai, formula xuất hiện hoặc old tail còn dữ liệu, When xác minh, Then không báo đầy đủ khớp, không promote final cache hoặc Record thành công.
- **S06** Given kết quả có hàng cuối toàn null, Decimal dài và literal bắt đầu bằng `=`, When ghi/kiểm, Then không mất hàng logic, không mất chữ số và không tạo formula; không dùng usedRange để suy diễn số hàng toàn null.

### US3 — Xử lý lần ghi chưa rõ mà không ghi lặp (Priority: P1; B03; audit P3/P8)

Tôi cần biết lần ghi có thể đã bắt đầu ở đâu và có thể kiểm lại chỉ đọc, thay vì được hướng dẫn ghi lại trong trạng thái chưa rõ.

**Independent Test**: ngắt tại trước dispatch, sau dispatch, sau một chunk, sau marker và sau read-back nhưng trước receipt; đếm mọi write/Save và lần cấp quyền.

**Acceptance Scenarios**:

- **S07** Given có bằng chứng chưa dispatch mutation, When lỗi, Then có thể nói chưa ghi. Nếu đã dispatch hoặc không đủ chứng cứ, Then giữ unknown/partial với workbook và đích đúng, không khẳng định workbook nguyên trạng.
- **S08** Given attempt unknown và còn expected result đáng tin trong phiên, When bấm kiểm tra lại, Then chỉ đọc đúng đích và trả matches/mismatch/insufficient tại thời điểm kiểm; không ghi, không cấp approval, không tự replay hay nâng cache/Record.
- **S09** Given hết phiên, mất expected result, đổi workbook hoặc chỉ còn XML metadata, When kiểm lại/mở lại, Then giữ insufficient/unknown; không tái tính rồi coi đó là expected result đã được duyệt.

### US4 — Giải quyết câu hỏi ảnh hưởng kết quả (Priority: P1; B04; audit P4)

Tôi cần chốt gross/net, tiền tệ, kỳ, khóa, trùng và dữ liệu thiếu trước khi duyệt kết quả có thể phụ thuộc vào những lựa chọn đó.

**Independent Test**: cùng Amount=100, Discount=10 có câu hỏi gross/net chưa trả lời, đã trả lời và trả lời “chưa rõ”.

**Acceptance Scenarios**:

- **S10** Given còn câu hỏi bắt buộc, When xem/tính A/B, Then cho xem để lựa chọn nhưng chặn freeze/approve/write. “Chưa rõ”, ô trống hoặc ID câu hỏi cũ không giải quyết blocker.
- **S11** Given nguồn full phát hiện vấn đề mới dù schema giữ nguyên, When chuyển discover→compute, Then tái lập question-set và vô hiệu review phụ thuộc; không giữ kết luận chỉ vì schema bằng nhau.
- **S12** Given chỉ có lưu ý trình bày, When người dùng tiếp tục, Then không chặn vô ích. Câu hỏi tự do của planner mặc định blocking tới khi được phân loại có lý do; không cho AI tự hạ một chủ đề nghiệp vụ trọng yếu thành advisory.

### US5 — Không nối nhầm các đối tượng thiếu khóa (Priority: P1; B05; audit P5)

Tôi cần quyết định cách xử lý mã thiếu, đồng thời thấy dữ liệu bị nhân theo khóa, mà không đổi âm thầm ngữ nghĩa join hiện có.

**Independent Test**: hai nguồn có KH01 trùng, null, chuỗi rỗng, số 0 và mã hợp lệ; chạy đủ sáu join kinds với kỳ vọng viết tay.

**Acceptance Scenarios**:

- **S13** Given khóa định danh thiếu, When chưa chọn policy, Then chặn chốt. Keep-unmatched không ghép hai đối tượng thiếu mã; exclude báo số bị loại; alternative-key phải xác nhận khóa/cột cụ thể; explicit missing-group phải được duyệt có lý do.
- **S14** Given policy làm đổi pipeline, When áp dụng, Then tạo plan/revision mới với các bước thuộc catalog hiện có, được review; không thay compiler/executor join hoặc revision cũ. Helper columns/steps tính vào giới hạn và không rò ra output cuối.
- **S15** Given một khóa nhân dòng nhưng tổng số dòng bị che bởi các dòng không khớp, When review, Then vẫn hiện số khóa không duy nhất, dòng thiếu/không khớp và mức nhân theo khóa; không diễn giải ratio tổng là quan hệ một-một.

### US6 — Biết có ghi được trước khi duyệt (Priority: P2; B06; audit P6)

Tôi cần biết giới hạn của hành động sắp làm, không tính/duyệt xong mới biết kết quả chắc chắn không thể ghi.

**Independent Test**: hai nguồn workbook 60.000 dòng; nguồn 100.000×4; kết quả 399.996/400.000/400.004 ô tính cả header; diagnostics 75/76 cột.

**Acceptance Scenarios**:

- **S16** Given nhiều nguồn workbook đọc cùng lượt, When cộng dồn vượt 100.000 dòng hoặc 400.000 ô dữ liệu, Then chặn đúng scope và nói rõ cách tính. Không tự áp trần cộng dồn này cho file/folder chưa có cùng contract.
- **S17** Given kết quả (rows+1)×columns >400.000, When đã tính A/B, Then hiển thị write-ineligible trước freeze/approval; Apply vẫn recheck. Helper projection và header không bị bỏ quên.
- **S18** Given chuyển luồng/hành động, When xem giới hạn, Then phân biệt đọc 512 cột, planning 200, output 256, diagnostics 75; 20/50 steps, sample/preview và result cap không được mô tả như một trần chung.

### US7 — Hiểu Quay về có thể thay sheet kết quả (Priority: P2; B07; audit P7)

Tôi cần biết đích bị thay khi khôi phục revision; xem lịch sử không được tự ghi.

**Independent Test**: View, Quay về cache hit, cache stale và lựa chọn giữ/xóa descendants trên cùng synthetic chain.

**Acceptance Scenarios**:

- **S19** Given cache có thể khôi phục, When xác nhận Quay về, Then nêu revision, sheet bị thay và phạm vi ghi; không chỉ nói đổi HEAD.
- **S20** Given cache miss/stale hoặc đích thay đổi sau xác nhận, When checkout, Then không ghi kết quả cũ; Preview mới cần duyệt riêng. View luôn zero write.
- **S21** Given chọn giữ descendants hoặc xóa tường minh, When checkout/delete, Then hành động đúng lựa chọn, CAS vẫn có hiệu lực và mọi revision còn lại không đổi bytes.

### US8 — Hiểu giới hạn báo cáo định kỳ (Priority: P2; B08; audit P9)

Tôi cần biết cái gì dùng lại được kỳ sau, không tưởng values-only là query Refresh.

**Independent Test**: mở lại Assistant metadata, đọc Typed history trên nguồn kỳ mới và xem Advanced preview note.

**Acceptance Scenarios**:

- **S22** Given Assistant Record metadata, When reopen, Then không hứa khôi phục pipeline/approval/result; JSON download phục vụ audit, chưa có import/re-run.
- **S23** Given Typed pipeline kỳ trước, When nguồn kỳ mới được nạp, Then cần kiểm schema/fingerprint, Preview và duyệt mới; không tự Refresh/Save/write.
- **S24** Given M nâng cao values-only, When xem kết quả, Then nêu không lưu query/connection. Scheduler và báo cáo tái chạy là backlog riêng, không thuộc pass của baseline.

### US9 — Đọc đúng nhãn tin cậy (Priority: P2; B09; audit P10 và giả thuyết 2/3/6/10)

Tôi cần đọc riêng đối soát, chất lượng dữ liệu, parity, mức xác minh ghi và Save, thay vì một chữ “đạt” cho tất cả.

**Independent Test**: tổng khớp nhưng ngày lỗi→null; parity none; sample read-back; người dùng đã Save ngoài add-in; yêu cầu tách cột ngoài catalog.

**Acceptance Scenarios**:

- **S25** Given tổng khớp và có ngày lỗi, When hiển thị, Then tổng có thể đạt nhưng quality warning/count vẫn rõ; không suy ra nghiệp vụ đúng hay parity runtime.
- **S26** Given add-in không gọi Save nhưng không quan sát trạng thái Save, When hiển thị, Then nói “Add-in không tự Save; chưa xác định trạng thái lưu hiện tại”, không khẳng định người dùng chưa lưu.
- **S27** Given yêu cầu ngoài catalog, When lập kế hoạch, Then báo thiếu khả năng, không tự chuyển Advanced M. Decimal Text, known differences và trạng thái parity được giữ; trạng thái thực hiện lấy từ CURRENT_STATUS.

## Requirements

| Alias | Yêu cầu | Story | Ràng buộc không được nới |
|---|---|---|---|
| B01 | Ngưỡng có đơn vị/rationale và explicit user review ràng buộc exact revision | US1 | Hard blockers không override; không auto-tune để xanh |
| B02 | Full verification khác sample verification, bao phủ ba writer và Typed restore | US2 | Chỉ đọc mẫu không promote fully verified/cache |
| B03 | Unknown-write latch + bounded read-only recheck | US3 | No retry, no approval reissue, no persisted result |
| B04 | Mandatory questions và full-source re-evaluation trước chốt | US4 | Schema bằng nhau không đủ; AI không tự bỏ blocker |
| B05 | Explicit missing-key policy + per-key evidence | US5 | Giữ sáu join semantics và catalog đóng |
| B06 | Giới hạn theo giai đoạn và eligibility trước approval | US6 | Không tăng cap; recheck tại write vẫn bắt buộc |
| B07 | Consent mô tả đúng cache restore/đích và không gộp xóa lịch sử | US7 | HEAD/CAS/source fingerprint/one-shot giữ nguyên |
| B08 | Phân biệt audit/values-only/pipeline reuse và backlog tái chạy | US8 | Không thêm scheduler/query persistence/import |
| B09 | Năm trục tin cậy độc lập, copy có bằng chứng | US9 | Không dùng static/fake evidence thay live |

## Key Entities

BusinessReview; ControlPolicy; QuestionResolution; JoinKeyDecision; WriteExpectation; WriteAttempt; VerificationObservation; ActionEligibility; TrustPresentation. Chi tiết và state transitions ở `data-model.md`.

## Success Criteria

Tất cả S01–S27 có oracle và task phụ trách; dữ liệu lỗi sau dòng 20 được phát hiện khi tuyên bố full verification; zero write/Save/approval mới ở recovery; mọi thay đổi ý nghĩa vô hiệu quyền cũ; fixtures kiểm source và revision preservation. B01–B05 là safety increment bắt buộc. Hoàn thành US1 riêng chỉ là MVP nội bộ, không phải đủ release. Full baseline gồm cả B06–B09 và gate exact-current tương ứng.

## Assumptions và các giới hạn được giữ

1. Người dùng là người duyệt workbook hiện tại; không thêm role/authentication system.
2. Chọn phương án nhỏ nhất trong kiến trúc đang có; không sửa schema lịch sử Typed hoặc hash cũ để thêm evidence.
3. Mức tolerance theo từng phép tổng, không tự chia theo dòng; trường hợp khác đơn vị cần clarification. Không tự đặt trần nghiệp vụ mới ngoài giới hạn cứng hiện hành.
4. Read-only recovery chỉ có thể xác nhận dữ liệu đang quan sát khi còn expected result đáng tin trong phiên, không chứng minh chính xác thời điểm viết trong quá khứ.
5. Chuỗi rỗng/null và whitespace được định nghĩa theo policy ở `data-model.md`; không suy rằng 0/false là thiếu.
6. Thiết kế/task dành cho Advanced M là công việc dự kiến; gate live của nó Deferred và chặn tuyên bố hoàn tất toàn bộ ba luồng tới khi được mở lại.
7. Mọi product/runtime check cho baseline này hiện là Not run. Chỉ kiểm tính đầy đủ/nhất quán của tài liệu ở lượt lập plan/tasks.
