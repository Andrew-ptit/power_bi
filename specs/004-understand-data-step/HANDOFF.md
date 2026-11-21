# Bàn giao trọn vẹn — đưa nền về `main` và triển khai feature 004

Ngày: 2026-11-22 (Asia/Saigon), đã rà soát lần 2 cùng ngày. Workspace: `C:\Users\COLAIG\Downloads\power_bi`.
Người nhận: agent triển khai (DeepSeek). Người duyệt: chủ repo.

Tài liệu này tự đủ để bắt đầu. Nó không thay `AGENTS.md`; khi mâu thuẫn, `AGENTS.md` và chỉ dẫn trực tiếp của người dùng thắng.

## 1. Việc cần làm

Hai giai đoạn, làm tuần tự:

- **Giai đoạn A — hoàn tất nền**: commit phần còn dở trên `main`, merge `integration/source-import-003` vào `main`, gate fast xanh.
- **Giai đoạn B — feature 004**: thêm bước `2. Hiểu dữ liệu` và sơ đồ quan hệ nối dây, theo [spec.md](spec.md), [plan.md](plan.md), [tasks.md](tasks.md) (T400–T408), [contracts/model-view.md](contracts/model-view.md), [data-model.md](data-model.md).

Không làm gì ngoài hai giai đoạn này.

## 2. Bối cảnh ngắn

Sản phẩm là trợ lý local cho Excel. Hành trình hiện tại (sau feature 003) là `1. Nguồn → 2. Đề bài`. Người dùng phải viết đề bài khi chưa thấy dữ liệu có hình dạng gì. Feature 004 chèn một bước ở giữa:

```text
1. Nguồn → 2. Hiểu dữ liệu → 3. Đề bài → (như hiện có) phương án A/B → chốt → duyệt → ghi
```

Bước mới tự đo cấu trúc (không gọi AI), cho thấy mỗi sheet là gì, có cột gì, nối với sheet nào qua cột nào, nối có nhân dòng hay có mã không khớp không, và cho người dùng xác nhận/từ chối ngay tại chỗ. Quan hệ được vẽ dạng nối dây như Model view của Power BI; nút `Mở rộng` mở cửa sổ riêng bố cục 1 : 3.

Bản thiết kế đầy đủ (gồm cả phần làm sau và phần hoãn): `docs/superpowers/specs/2026-11-21-understand-and-suggest-design.md`. Mockup tĩnh để tham khảo hình thức, không phải nguồn yêu cầu: `.superpowers/brainstorm/1590-1795275786/content/flow-overview-v4.html`.

## 3. Trạng thái đã kiểm ngày 2026-11-22

| Mục | Giá trị |
|---|---|
| `main` | `4a20bb4`, đi trước `origin/main` 7 commit, chưa push |
| Working tree `main` | 39 file sửa, 3 file test bị xóa, 10 mục untracked |
| `integration/source-import-003` | `3e84b17`, đi trước `main` 25 commit, chứa trọn `codex/source-import-003`, worktree sạch tại `.artifacts/worktrees/integration-source-import-003` |
| Gate fast trên nhánh tích hợp | `run=1293 failed=0 errors=0 skipped=3` (chạy lại độc lập, 206 giây) |
| Gate fast trên `main` + working tree (trước khi có nhánh tích hợp) | `run=1242 failed=0 errors=0 skipped=3` |
| `tools/excel_addin/manifest.xml` trên `main` (bản local, cổng 3075) | SHA-256 `334c165060a43372d50064c0fab0b147d7069f5c9bf88d54dc557fad52424a86`, **trùng** `C:\AddinManifests\manifest.xml` |
| Manifest trên nhánh tích hợp | Khác (cổng 3079, cấu hình của worktree 003) |
| `docs/proposals/` | Untracked, chưa từng vào commit nào |

Danh sách đầy đủ 39 file sửa chưa commit trên `main` (đọc ngày 2026-11-22):

Nhóm 1 — tài liệu, khác với nhánh tích hợp (15 file):

```text
AGENTS.md
README.md
docs/current/DEEPSEEK_HANDOFF.md
docs/current/EXCEL_MCP_SPEC.md
docs/current/PROBLEM_CHAIN_SPEC.md
docs/current/TASKPANE_UI.md
specs/002-data-preparation/acceptance.md
specs/002-data-preparation/contracts/preparation.md
specs/002-data-preparation/plan.md
specs/002-data-preparation/quickstart.md
specs/002-data-preparation/research.md
specs/002-data-preparation/spec.md
specs/002-data-preparation/tasks.md
tests/live/README.md
tools/excel_addin/README.md
```

Nhóm 2 — mã/test, khác với nhánh tích hợp (3 file):

```text
pbip_assistant/excel_addin/taskpane.css
tests/contracts/test_coordinator_dispatch.py
tests/fixtures/contracts/route_paths.json
```

Nhóm 3 — mã/test, trùng từng byte với nhánh tích hợp tại thời điểm kiểm (18 file):

```text
examples/make_sample.py
pbip_assistant/coordinator/endpoints/__init__.py
pbip_assistant/excel/connector.py
pbip_assistant/powerquery/typed/store.py
tests/contracts/test_pbip_fixtures.py
tests/contracts/test_pbir.py
tests/contracts/test_pq_typed_schema.py
tests/contracts/test_pq_typed_schema_crosscheck.py
tests/contracts/test_source_fixtures.py
tests/integration/test_excel_addin_server.py
tests/integration/test_fixture_integration.py
tests/integration/test_webapp.py
tests/live/create_fixture.py
tests/runtime/test_tmdl.py
tests/unit/test_xlsx_advanced.py
tools/excel_connector/Invoke-ExcelConnector.ps1
tools/excel_connector/Invoke-PQCodeM.ps1
tools/live_excel_gate.py
```

Nhóm 4 — manifest (1 file): `tools/excel_addin/manifest.xml`.

Nhóm 5 — feature 004 (2 file sửa + 2 file mới): `specs/004-understand-data-step/plan.md`, `tasks.md`, `spec.md`, `contracts/model-view.md` (những file nào `git status` báo sửa), `HANDOFF.md`, `PROMPT.txt`.

Ba file bị xóa chưa commit: `tests/taskpane/taskpane_code_blocks.js`, `taskpane_live_analyze.js`, `taskpane_shortcut.js`.

Mục untracked: `.agents/`, `.specify/`, `.superpowers/`, `.vscode/`, `reports/`, `docs/proposals/`, `docs/current/CODEX_HANDOFF_2026-11-22.md`, hai file mới của 004, và một file tên `nul` ở thư mục gốc (file rác do một lệnh `2>nul` tạo; `nul` là tên dành riêng của Windows).

Số liệu trên là ảnh chụp. Bước A0 phải đọc lại trạng thái thật trước khi làm; nếu một file ở nhóm 3 không còn trùng nhánh tích hợp thì xử lý nó như nhóm 2.


## 4. Quyết định mặc định của người dùng

Người dùng sửa bảng này trước khi gửi nếu không đồng ý. Agent không tự đổi.

| # | Quyết định |
|---|---|
| Q1 | Manifest: giữ bản local cổng 3075 (đang trùng catalog). Không lấy bản của nhánh tích hợp. Không ghi vào `C:\AddinManifests\`. |
| Q2 | Ba file test bị xóa (`taskpane_code_blocks.js`, `taskpane_live_analyze.js`, `taskpane_shortcut.js`): commit việc xóa. Căn cứ: `docs/current/ASSISTANT_INTEGRATION_SPEC.md` ghi chúng được thay bằng case F-JS-11/12/13. |
| Q3 | `docs/proposals/`: không bao giờ `git add`. Thêm một dòng `/docs/proposals/` vào `.gitignore`. Người dùng tự chuyển thư mục ra ngoài repo. |
| Q4 | Không commit `.superpowers/`, `.vscode/`, `reports/`, `.agents/`, `.specify/`, `docs/current/CODEX_HANDOFF_2026-11-22.md` trong đợt này. Không add và không tự xóa file `nul` ở thư mục gốc; báo lại để người dùng xử lý. |
| Q5 | Không push, không tạo PR, không xóa nhánh hay worktree nào. |
| Q6 | Merge nhánh tích hợp vào `main` được phép, sau khi A1–A3 xong. |
| Q7 | Feature 004 làm trên nhánh mới `feature/004-understand-data-step` tách từ `main` sau giai đoạn A. Không merge nhánh này vào `main`; người dùng duyệt rồi mới merge. |
| Q8 | Bước Hiểu đo trên toàn bộ dòng (nạp `compute`), vượt giới hạn thì lùi về mẫu 20 dòng kèm cảnh báo (spec H19–H21). Đây là thay đổi hành vi so với hiện tại (đang nạp mẫu `discover`). **Mặc định: duyệt.** Nếu người dùng đổi thành không duyệt: bỏ H19 và H21, giữ `discover`, `measuredOn` luôn là `sample` và cảnh báo luôn hiện. |

## 5. Giai đoạn A — hoàn tất nền

Mỗi bước: chạy, ghi lệnh và output chính vào báo cáo. Sai khác với mô tả → dừng.

**A0. Đọc lại trạng thái.** `git status --short`, `git log --oneline -8 main`, `git rev-list --count main..integration/source-import-003`, SHA-256 của `tools/excel_addin/manifest.xml` và `C:\AddinManifests\manifest.xml`. Nếu hai SHA không còn trùng nhau, hoặc danh sách file dở khác đáng kể với mục 3 → dừng, báo.

**A1. Mốc an toàn.** `git branch backup/main-before-004 main`. Không dùng `git stash`, `git reset`, `git clean`, `git checkout -- .`, `git restore .`.

**A2. `.gitignore`.** Thêm dòng `/docs/proposals/`. Kiểm `git status --short` không còn liệt kê `docs/proposals/`.

**A3. Commit phần dở trên `main`, add từng đường dẫn cụ thể** (không `git add -A`, không `git add .`, không `git add -u`). Gợi ý chia commit:

1. `.gitignore`.
2. Ba file test bị xóa (`git rm` đúng ba đường dẫn).
3. Tài liệu: 15 file nhóm 1 ở mục 3.
4. Mã và test còn dở: 3 file nhóm 2 và 18 file nhóm 3 ở mục 3.
5. `tools/excel_addin/manifest.xml` (bản local, một commit riêng, message nêu rõ đây là cấu hình đang dùng và trùng catalog).
6. `specs/004-understand-data-step/`: mọi file `git status` báo sửa hoặc mới trong thư mục này.

Sau A3: `git status --short` chỉ còn các mục untracked ở Q4 (gồm `nul`). Nếu còn file sửa nào khác → dừng, báo.

**A4. Merge.** Trên `main`: `git merge --no-ff integration/source-import-003`.

- Xung đột ở `tools/excel_addin/manifest.xml`: giữ bản của `main` (Q1).
- Xung đột ở tài liệu: giữ nội dung của cả hai bên khi chúng nói về việc khác nhau; khi cùng một đoạn bị sửa khác nhau thì giữ bản `main` cho phần mô tả quy tắc/quyết định của người dùng và bản nhánh tích hợp cho phần mô tả feature 003. Riêng `AGENTS.md`: phải giữ nguyên mục `## Installed development workflows` của `main`; nếu có xung đột khác trong file này → dừng, hỏi.
- Xung đột ở mã/test/fixture (`taskpane.css`, `test_coordinator_dispatch.py`, `route_paths.json`, …): bản nhánh tích hợp chứa phần của 003 và đã qua gate; lấy bản đó trừ khi `main` có thay đổi không có ở nhánh tích hợp, khi đó gộp và giải thích trong báo cáo.
- Không còn dấu `<<<<<<<`/`>>>>>>>` trong cây.

**A5. Kiểm chứng.**

```powershell
py tools/run_checks.py fast
```

Kỳ vọng: `run ≥ 1293`, `failed=0`, `errors=0`, `skipped=3`. Kiểm thêm: SHA-256 của `tools/excel_addin/manifest.xml` vẫn bằng `334c1650…4a86` và bằng file catalog; `taskpane.html` có đúng hai bước `1. Nguồn`, `2. Đề bài`; `git merge-base --is-ancestor codex/source-import-003 main` thành công.

Gate không xanh → không sang giai đoạn B. Điều tra nguyên nhân gốc; không gỡ/nới test.

**A6. Báo cáo giai đoạn A** (mục 9) rồi tiếp tục giai đoạn B mà không cần chờ, trừ khi có điểm dừng.

## 6. Giai đoạn B — feature 004

1. `git switch -c feature/004-understand-data-step` từ `main` sau A5.
2. Làm đúng thứ tự trong `tasks.md`: `T400 → T401 → (T402 ∥ T405) → T403 → T404 → T406 → T407 → T408`. Mỗi task: test đỏ đúng lý do → implement tối thiểu → xanh → chạy lệnh kiểm chứng của task → một commit mang ID task → một dòng evidence trong `acceptance.md`.
3. Chỉ sửa file trong mục **Files** của từng task.
4. Sau T407: báo cáo cuối (mục 9). Không merge vào `main`.

### Những điểm dễ sai nhất

| # | Điểm | Phải làm |
|---|---|---|
| R1 | `understand` và `understandHash` không được đổi một byte | `modelView` là khóa cấp trên của phản hồi, không thêm trường vào object `understand`, không sửa `_HASH_BASIS` |
| R2 | Xác nhận của người dùng không phải kho dữ liệu mới | Dùng đúng `state.flow.answers[questionId]` và đúng chuỗi `options` của câu hỏi đo được hiện có |
| R3 | Cột ngày: `flowWorkbookCell` đã đổi serial có numberFormat ngày thành chuỗi ISO trước khi gửi | T400 bước 6 chỉ xác nhận lại. Kết quả khác → dừng, báo; không tự đổi cách nhận biết ngày |
| R4 | Câu hỏi `grain` mới có thể làm đổi `requestHash`/`planningHash` mà test cũ ghim | Test cũ fail vì lý do này → dừng, báo tên test; không sửa golden |
| R5 | Script task pane là classic script có thứ tự | File JS mới phải vào `taskpane.html`, bảng asset của `coordinator/server.py`, và hai test `test_taskpane_asset_order`, `test_taskpane_asset_routes` |
| R6 | Hộp thoại mở rộng | Chỉ là view: không `fetch`, không token, không API workbook; dữ liệu qua `messageChild`/`messageParent`. Không hỗ trợ `DialogApi 1.2` → ẩn nút, ghi `Blocked`. Cần sửa manifest → dừng, hỏi |
| R7 | Không đoán nghĩa nghiệp vụ | Câu mô tả dòng dùng tên cột khóa ("Mỗi dòng ứng với một `order_id`"), không viết "1 đơn hàng" |
| R8 | Không lời gọi AI mới | Feature này không gọi Codex, không gửi dữ liệu ra ngoài |
| R9 | Hiện bước chuyển sang Đề bài nạp mẫu 20 dòng mỗi sheet (`discover`); đo quan hệ trên mẫu cho kết quả thiếu/sai với bảng lớn | Theo Q8: bước Hiểu nạp `compute`; chỉ lùi về `discover` khi nhận `AF_UNDERSTAND_LIMIT`/`REQUEST_LIMIT`, đúng một lần, và luôn hiện cảnh báo "đo trên mẫu". Số dòng gửi Codex khi lập kế hoạch vẫn tối đa 20 |
| R10 | Mã lỗi mới duy nhất là `AF_UNDERSTAND_LIMIT` (409) | Không thêm mã lỗi hay route nào khác; không nâng/hạ giới hạn tính toán của WL2 |

### Không làm trong feature 004

- Mọi mục mang thẻ `[HOÃN-K]` trong bản thiết kế (mục 9.2): danh mục bài toán mẫu, đối chiếu ba mức, nghĩa cột riêng Supply Chain, bỏ ô tick disclosure.
- Quyền cho AI đọc giá trị, gộp nhóm, sheet bảng quy đổi, gợi ý dưới ô đề bài: thuộc feature sau, chưa có spec.
- Người dùng tự thêm quan hệ, đổi vai trò bảng, gán nghĩa cột, kéo thả dây.
- Sửa Typed, Problem Chain, Advanced M, PBIP, Domain Pack, Brief/Spec/Record, backend preparation, bước Nguồn của 003.
- Đổi version, manifest, dependency.

## 7. Quy tắc chung

- Đọc `AGENTS.md` trước. Python 3.13 stdlib; JS thuần; không thêm dependency hay build step.
- Không ghi vào workbook người dùng; không dùng workbook đang mở làm fixture; fixture tổng hợp; expected value từ oracle viết tay không import module đang test.
- Không log giá trị ô, tên sheet/cột, đường dẫn riêng, token.
- UI: tiếng Việt, `textContent`, `aria-live`, dùng được ở 360px và bằng bàn phím.
- Không gỡ test, không nới assert, không sửa golden/hash ghim, không bỏ script task-pane khỏi gate để gate xanh.
- Mô phỏng unit/HTTP/Office.js không phải bằng chứng live Excel. Thiếu Excel/Codex → `Not run` hoặc `Blocked`, không giao phần kiểm chứng cho người dùng.
- Không khởi động lại hay dừng coordinator đang chạy của người dùng.

## 8. Điều kiện dừng

Dừng, không tự xử lý, khi:

1. Trạng thái thật khác mô tả ở mục 3 theo cách ảnh hưởng tới bước đang làm.
2. Cần sửa file ngoài allowlist của task, hoặc cần đổi contract/spec.
3. Một test có sẵn fail vì lý do không thuộc task đang làm.
4. Một thao tác Git có thể làm mất thay đổi chưa commit.
5. Xung đột trong `AGENTS.md` ngoài trường hợp đã nêu ở A4.
6. R3 cho kết quả khác mô tả; R4 xảy ra; R6 cần sửa manifest.
7. Không chắc một thao tác có ghi vào workbook người dùng, catalog add-in, hoặc đẩy dữ liệu ra ngoài hay không.

Khi dừng: báo việc đang làm, lệnh và output, điều đã thử, và các lựa chọn. Ghi `Blocked (§n)` vào `acceptance.md` nếu đang ở giai đoạn B.

## 9. Định dạng báo cáo

Cuối giai đoạn A và cuối giai đoạn B (hoặc khi dừng):

```text
Giai đoạn / task:
Kết quả: Pass | Blocked (§n) | Not run
Commit: <hash> <message>            (mỗi commit một dòng)
Lệnh kiểm chứng và output:          (dòng gate=… nguyên văn; số test, thời gian, exit code)
File đã đổi:
Thay đổi hành vi người dùng thấy:
Chưa kiểm chứng:                    (live Excel, hộp thoại, …)
Sai khác so với spec/plan/handoff:  (kèm lý do; "không có" nếu không)
Cần người dùng quyết định:
```

Không viết "hoàn tất 100%", "đã sẵn sàng phát hành" hay tương đương khi còn mục `Not run`/`Blocked`.

## 10. Sau feature 004

Đợt 2 (quyền đọc giá trị, chuẩn hóa hai tầng, sheet quy đổi) và đợt 3 (cơ chế gợi ý đề bài) sẽ có spec riêng sau khi T407 pass. Không bắt đầu chúng từ tài liệu này.
