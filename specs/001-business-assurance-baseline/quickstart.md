# Validation guide: baseline tin cậy nghiệp vụ

Tài liệu dành cho người thi công/kiểm chứng, không giao việc xác minh cho người dùng workbook. **Chưa chạy các lệnh product dưới đây trong lượt lập plan.** Test module mới chỉ tồn tại sau task tương ứng; commands được ghi như acceptance targets, không là lệnh đã xác minh chạy xanh.

## Prerequisites và phạm vi

- Python 3.13, Node và Windows PowerShell 5.1 như repo; Excel/Office.js cho gate live, Codex auth cho gate opt-in riêng. Không cài dependency mới theo baseline.
- Dùng synthetic fixtures trong tests/support và disposable marked workbook; cấm workbook người dùng. Không restart/stop coordinator của người dùng hoặc đổi production manifest/catalog để chạy thử.
- Code đang có thay đổi chưa commit: trước thi công ghi revision và exact working-tree snapshot; không reset/stash hay ghi đè thay đổi ngoài feature.
- Chốt canonical contracts ở task setup trước sửa source. Tuân module owner/locks/schema aliases; không bump app/npm/HTTP/manifest cho tới khi release gates đạt.

## 0. Live readiness sớm và chọn test theo cụm

Thực hiện readiness ở đầu C00 khi bắt đầu implementation, ghi kết quả riêng trong acceptance-matrix.md. Lượt sửa kế hoạch 2026-11-10 không chạy các bước product/live này. Không suy readiness hiện tại từ báo cáo cũ; CURRENT_STATUS.md đang ghi parity timeout và Office.js chưa đủ evidence.

1. Kiểm read-only: Python 3.13 (`py --version`), Node (`node --version`), Codex CLI (`Get-Command codex`), sự hiện diện harness/certs và quyền sử dụng Excel/Office.js. Không in token, auth file, certificate key hoặc dữ liệu workbook. Không suy auth hoạt động chỉ từ việc CLI tồn tại.
2. Đọc tests/live/README.md và harness trước khi chọn probe. `tools/live_excel_gate.py` chỉ khởi động server; không mở Excel hay tự sideload/run UI. Server ready không chứng minh taskpane handler chạy được. Dùng disposable synthetic workbook có Gate_Run_Id và manifest unique của gate, không đổi catalog/manifest production hay dừng process người dùng.
3. Nếu thực thi đã được phép, thử một smoke nhỏ có giới hạn bằng harness hiện có để xác định workbook creation, add-in/taskpane và callback có dùng được không. Đặt timeout hữu hạn theo runner hiện có; chỉ dọn process/workbook thuộc gate. Nếu không đủ UI/auth, ghi Blocked/Not run và lỗi/layer cụ thể. Không mở Advanced M live.
4. Real Codex cần opt-in riêng `PQPC_LIVE_CODEX=1` và auth hợp lệ; chưa được phép thì chỉ ghi Not run, không tự tạo request hoặc bật opt-in. Deterministic planner không chứng minh real Codex readiness.
5. Ghi snapshot, probe/command, layer, elapsed, result/error và ảnh hưởng tới cụm nào. Probe cũ không chứng minh baseline mới; T055/T057 vẫn cần exact-current qualification. Không retry blocker lặp lại khi không có thay đổi liên quan; tiếp tục phần không phụ thuộc.

| Cụm / thay đổi | Focused trong lúc sửa | Tại ranh giới |
|---|---|---|
| C00 | Characterization contracts, synthetic fixture/guard tests liên quan T004–T007 | Contract checkpoint + routing/compatibility integration; readiness ghi riêng |
| C01, C04 | `tests.unit.test_assistant_review`, `tests.integration.test_business_assurance` khi module đã tồn tại | Assistant flow; C04 thêm Problem Chain; full regression/affected live khi thay đổi xuyên lớp |
| C02, C03 | `tests.unit.test_write_verification`, `tests.integration.test_write_verification_journey`, business assurance contracts theo task | PQ write/source apply + Assistant/Typed success/recovery; full regression/affected live vì nhiều owners/writers |
| C05, C06 | `tests.unit.test_join_policy` và boundary/journey cases ở task tương ứng | Assistant/Typed UI, affected integration, parity/Codex/Office.js theo thay đổi; full regression khi xuyên lớp |
| C07 | Restore consent/owner tests và write-verification journey | Problem Chain restore success/recovery, source/prior revisions; affected live + full regression |
| C08, C09 | XML/reopen hoặc presentation/unsupported-request cases của task | Các taskpane scripts và integration bị ảnh hưởng; mở rộng theo dependency diff thực tế |
| C10, C11 | Required-case registry, bounds và docs coverage | Toàn bộ automated/runtime/live bắt buộc + rà độc lập, exact-current; giữ Advanced live Deferred |

Các tên test mới vẫn là planned targets cho tới task tạo xong. Không chạy module chưa có để lấy “module missing” làm behavioral red. Dùng tests hiện có liên quan khi characterization/resume; sau khi tạo test mới phải quan sát fail đúng hành vi. Danh sách trên là điểm bắt đầu, không thay đọc diff/dependency để chọn đủ checks. Các lệnh cụ thể bên dưới vẫn là entrypoints chuẩn; không mặc định chạy toàn bộ chúng sau mỗi edit.

Shared fixture/oracle thuộc tests/support; một data vector dùng lại được ở nhiều layer nhưng expected không lấy từ implementation. Giữ retained behavioral replacements. Tái dùng một run cho nhiều T/S criteria chỉ khi scope đủ và relevant code/dependencies/fixtures/environment không đổi; full release gates vẫn exact-current.

## 1. Kiểm từng lát (sau khi có implementation)

Các module dưới đây là **planned new tests**. Unit có oracle viết tay, không suy expected từ implementation.

```powershell
py -m unittest tests.unit.test_assistant_review tests.unit.test_write_verification tests.unit.test_join_policy -v
py -m unittest tests.integration.test_business_assurance tests.integration.test_write_verification_journey -v
py -m unittest tests.taskpane.test_taskpane_js -v
```

Expected: S01–S21 đúng cả success/failure, body/chunk budgets, forged/stale/replay denied; no source writes ngoài Advanced consent; prior cache/history giữ. 12 retained JS scripts phải chạy, không drop case để green.

Story UI contracts dùng các script hiện có được mở rộng, tránh tự đặt một gate thay thế:

```powershell
node tests/taskpane/taskpane_assistant_flow.js
node tests/taskpane/taskpane_pq_typed.js
node tests/taskpane/taskpane_pq_write.js
node tests/taskpane/taskpane_pq_source_apply.js
node tests/taskpane/taskpane_problem_chain.js
node tests/taskpane/taskpane_advanced_policy.js
node tests/taskpane/taskpane_advanced_policy_crosscheck.js
```

Expected: handlers thật trong fake Office host chứng minh button state và write/runner/Save counts. Đây vẫn là simulation, không Office.js live. Check unknown latch tại mỗi dispatch/sync boundary, không chỉ lỗi API trước ghi.

## 2. Full automated regression

Các commands này đã là entrypoint repo, nhưng baseline chưa được chạy:

```powershell
py tools/run_checks.py fast
py -m unittest discover -s tests -v
```

Required-case registry phải bằng actual retained cases, không missing/duplicate hoặc xóa test không có behavioral replacement. Full discovery có thể gồm external gates; report auth/runtime unavailable riêng, không tự đổi environment để coi skip là pass. Fast không thay runtime/live evidence.

## 3. Runtime và real Codex — tách hai lớp

```powershell
py tools/run_checks.py runtime
$env:PQPC_LIVE_CODEX = '1'
py tools/run_checks.py codex
```

Không chạy Codex nếu chưa có opt-in/auth. Runtime gate không được dùng để âm thầm mở Advanced M live deferral; đọc test selection/current instructions trước chạy. Changed planner phải có synthetic real request, đúng bounded samples và no raw paths/full workbook. M parity kiểm helper-backed join plans và comparison cases trên synthetic workbook; mismatch giải thích bằng contract/known differences, không sửa oracle cho xanh.

## 4. Actual Office.js synthetic journeys

Existing harness entrypoints (chạy trong lượt implementation/qualification được phép, không ở lượt planning này):

```powershell
py -m tests.live.create_fixture .artifacts/gate-assurance-001/fixture assurance-001
py tools/live_excel_gate.py --run-id assurance-001 --out .artifacts/gate-assurance-001
```

Dùng run ID mới cho mỗi lần chạy; sideload đúng unique manifest vào disposable fixture có Gate_Run_Id. Harness server có vòng đời riêng. Mở rộng `tests/live/assistant_v2_gate_driver.js`, `tests/live/taskpane_gate_driver.js` và `tests/live/server_support.py` theo tasks; không dùng production coordinator/token hoặc workaround giảm guard.

Hành trình bắt buộc:

1. Assistant: load→discover→mandatory Q&A→review thresholds→compute A/B→freeze/approve→write/read-back→Record→XML metadata→reopen. Test source đổi cùng schema, lost response và only-read recheck.
2. Typed: persisted root/child/HEAD→Preview/staging→Confirm→full verification/cache→checkout hit→stale miss→cancel/recovery→reopen. Assert old revision hashes, cache bytes và source fingerprints.
3. Wrong cell sau dòng20; cột201 dùng Assistant (output cho phép tới256), PQ dùng cột200 và chặn output201 theo cap. Thêm Table shrink/tails, formula/marker mismatch, workbook switch, session expiry và two-client contention. Không tuyên bố coauthoring supported.
4. Advanced automated/shared writer checks có thể được phát triển; **Advanced M actual live vẫn Deferred**, giữ default includeAdvancedM=false. Không đổi cờ để chạy nếu chưa có yêu cầu mở lại. Full-three-mode baseline chưa Complete khi gate này còn deferred.

## 5. Oracle nghiệp vụ mẫu

| Scenario | Expected độc lập |
|---|---|
| Order KH01=100, lookup KH01 có 2 dòng | Projected join có 2 matches; policy chưa duyệt không freeze. Không auto nâng tolerance/fan-out |
| Gross=100, Discount=10 | Gross và net90 là hai definition khác; “chưa rõ” vẫn blocking |
| Null keys mỗi bên một bản ghi | Keep-unmatched không ghép hai đối tượng thiếu mã; explicitMissingGroup có thể ghép sau consent |
| 0, false, "0", "", null, " " | Ba giá trị đầu không missing; whitespace phụ thuộc explicit trim policy |
| 25 rows, tamper row25 | Full verification mismatch; sample-only không được báo full |
| Assistant Decimal "12345678901234567890.01" | Text giữ nguyên chữ số, không formula/numeric coercion |
| 100000×4 data cells, header 4 cells | Read có thể pass; result 400004 cells không đủ write eligibility trước approval |
| Mất response sau server completed | Inspect có thể trả stored historical receipt; không ghi/promote cache lần hai; current target cần đọc lại |
| Reopen chỉ XML metadata | Không expected full result/approval; recovery insufficient, không rerun M |

## 6. Evidence format và pass rules

Mỗi lượt: exact revision + working-tree hash, command/run ID, layer, scenario aliases, pass/fail/skip/blocked/deferred/not-run, wall time, error codes, revision/step changes, result dimensions, source before/after fingerprints, write/Save/runner counts và max bytes. Không raw cells/prompt, credential, private paths hoặc workbook binaries trong report; synthetic artifacts dưới ignored .artifacts.

Một story pass khi mọi scenario của nó có evidence đúng lớp và negative paths không cấp authority; một simulated pass không đóng gate live. Scope delivered phải nêu Advanced Deferred. Product metadata chưa được đổi chỉ vì tài liệu/fast xanh. Acceptance-matrix.md giữ kết quả hiện tại là Not run/Deferred cho tới có evidence thật.

## 7. Prompts tiếp tục theo kế hoạch đã chỉnh

Spec Kit là bộ skill/workflow được agent thực hiện trong repository, không phải dịch vụ giao việc bên ngoài. Lượt 2026-11-10 đã áp dụng plan/tasks tại chỗ, giữ nguyên spec/contracts và checklist. Không cần chạy lại specify/plan/tasks từ đầu khi bắt đầu code. Với các lệnh Spec Kit trong PowerShell, dùng `$env:SPECIFY_FEATURE = '001-business-assurance-baseline'`; đây là chọn feature context, không tạo/checkout branch. Kiểm branch thật bằng git, không suy branch từ context override.

### Prompt bắt đầu hoặc tiếp tục implementation

```text
$speckit-implement Tiếp tục feature specs/001-business-assurance-baseline theo plan.md và mục Execution batches của tasks.md đã điều chỉnh ngày 2026-11-10.

Đọc AGENTS.md, spec/plan/tasks/contracts, quickstart và execution checkpoint/evidence trong acceptance-matrix.md. Kiểm git diff/source liên quan để phân biệt code đang có với việc đã đủ evidence; giữ nguyên thay đổi ngoài scope, không reset/stash/ghi đè. Chọn feature context SPECIFY_FEATURE=001-business-assurance-baseline cho scripts, kiểm branch thật; không tự tạo/đổi branch hoặc commit/merge.

Tìm cụm đầu tiên còn thiếu tiêu chí và prerequisites đã đủ, tiếp tục phần dang dở thay vì làm lại toàn bộ. Nếu chưa có checkpoint đáng tin thì bắt đầu đối chiếu C00, không mặc định US1 đã xong từ code Assistant v2. Thực hiện inline theo thứ tự C00→C01→C02→C03→C04→C05→C06→C07→C08→C09→C10→C11, giữ dependency và từng T-ID/pass criterion. Không mặc định spawn agents. Contract T002/T006 phải được review trước behavior implementation.

Đầu implementation kiểm live readiness theo quickstart; actual probe chỉ dùng synthetic disposable fixtures và quyền hiện có. Không tự bật real Codex opt-in, không dùng workbook người dùng, không đổi catalog production. Advanced actual live vẫn Deferred. Readiness không thay qualification; missing gates ghi Blocked/Not run, tiếp tục task độc lập.

Trong mỗi cụm làm test-first theo hành vi, dùng chung tests/support với expected độc lập, chạy focused checks khi sửa; tích hợp xong chạy affected success/recovery journey và review cụm. Thay đổi xuyên lớp và release vẫn full regression + applicable live gates, đủ 12 taskpane scripts. Không chạy lại suite không đổi chỉ để đóng checkbox khác, không lập lại plan hoặc hỏi xác nhận sau mỗi task nhỏ. Chỉ dừng vì material ambiguity, blocking concern hoặc prerequisite thật sự thiếu theo AGENTS.md; giữ nguyên checklist-quality approval gates nếu phát sinh.

Ghi command/snapshot/layer/result/time/T-S coverage và checkpoint tiếp tục trong acceptance-matrix.md; chỉ check T-ID khi đủ mọi tiêu chí đúng lớp. Sau một cụm tiếp tục cụm kế tiếp khi prerequisites đủ và trong phạm vi được phép. Khi cần bàn giao ghi rõ cụm/task đang dở, tests đã/chưa chạy, evidence cần chạy lại và bước tiếp theo. Không tuyên bố baseline/release Complete khi live-required gates còn thiếu, không bump version.
```

### Prompt nối lại sau khi phiên bị ngắt

```text
$speckit-implement Resume specs/001-business-assurance-baseline. Đọc Execution batches và acceptance-matrix.md execution checkpoint, kiểm git diff/source/evidence để xác định phần đã làm. Tiếp tục task thiếu tiêu chí trong cụm đang dở; nếu cụm đã đủ thì sang cụm kế tiếp đủ prerequisites. Không regenerate spec/plan/tasks, không lặp tests có evidence còn hợp lệ; thay relevant code/dependencies/fixtures/environment thì chạy lại phần bị ảnh hưởng. Tuân quickstart mục 0 và 7, giữ test-first, review theo cụm, full regression/live-required gates, Advanced live Deferred, không tự bật Codex opt-in hoặc commit/merge. Ghi checkpoint và kết quả đúng lớp trước khi kết thúc.
```

### Prompt kiểm tra coverage sau một mốc tích hợp

```text
$speckit-analyze Phân tích read-only specs/001-business-assurance-baseline với feature context SPECIFY_FEATURE=001-business-assurance-baseline. Đối chiếu spec/plan/tasks, dependencies C00–C11, T001–T060 và S01–S27; xem acceptance-matrix.md để phân biệt plan coverage với evidence thực. Báo orphan/contradiction, contract/authority regressions và gate thiếu. Không sửa file, không regenerate tasks, không gọi test/mock pass là live pass. Chỉ dùng $speckit-converge sau này nếu thực sự phát hiện requirement chưa có task; không thêm task cho phần đã được T-ID hiện có bao phủ.
```
