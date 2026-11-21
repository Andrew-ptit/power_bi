# Data model và state transitions

Thiết kế dự kiến, không phải model đã triển khai. Tất cả new structures đóng schema, từ chối unknown fields/nonfinite numbers và bound kích thước. Không DB/migration Typed history.

## 1. BusinessReview (Assistant decisions schema 3.0)

| Field | Ràng buộc |
|---|---|
| schemaVersion | `1.0` của review envelope, độc lập Spec/Record 3.0 |
| branchId, snapshotHash, planningHash, planHash | Exact current compute branch và canonical hashes |
| questionSetHash, evidenceHash | Bao phủ current questions và full-source measurements liên quan; không chỉ schema |
| resolutions | Tối đa 200 entries; questionId duy nhất, current; selected option/definition và resolution status |
| controlPolicy | Khai R2 applicable hay unavailable; tolerance/measureUnit/rationale khi áp dụng; maxFanOut và rationale từng join policy |
| joinKeyDecisions | Current merge stepId, ordered key refs, missing handling và blank/trim policy; hash cùng review |
| acknowledgeMissingControl | Boolean user action riêng; không substitute policy approval |
| reviewedBy | Chỉ `user`, từ explicit action của handler/owner; AI không set authority |
| reviewedAt | ISO timezone do caller truyền, validate; không ảnh hưởng purity engine |
| reviewHash | SHA-256 canonical toàn review trừ chính reviewHash |

Question/answer text tối đa 3.000 ký tự/entry, giữ các existing request caps; tổng canonical review tối đa 512 KiB, không truncate. Cấm raw profile/sample arrays, source file paths và credentials; không tự nhận biết/redact mọi dữ liệu người dùng gõ. Review text chỉ dùng cho yêu cầu hiện tại và theo disclosure; không log raw text. If privacy-safe Record projection không thể giữ được, fail explicitly thay vì tự bỏ/hash field rồi gọi đó là full record.

**Relations**: Review→Decisions3.decisionsHash→Spec3.fingerprint→approval `{specFingerprint,previewHash}`. User review không là write approval. Đổi bất kỳ policy/answer/evidence/branch/source/plan liên quan thì review, reconciliation authority, frozen spec và approval bị invalidate; numeric execution cache có thể giữ nhưng phải đối soát lại dưới policy mới.

## 2. QuestionResolution

Category: `kpiBasis`, `unit`, `period`, `joinKey`, `duplicate`, `missingValue`, `presentation`, `other`. Required status là deterministic classification; unknown planner question mặc định required. Không cho advisory override một hard blocker hoặc critical category còn chưa rõ.

Resolution gồm `questionId`, `questionHash`, `status=resolved|unresolved`, `selectedOption` hoặc `definition`, `reason`, `source=user`. Advisory classification có lý do; free-form resolved phải là explicit user confirmation đúng definition, không chỉ nonempty input. “Chưa rõ”, “Cần làm rõ”, empty và stale IDs giữ unresolved. Branch A/B có thể biểu diễn hai definitions, nhưng người dùng phải chọn definition có ý nghĩa để close question trước freeze.

State: `detected → unresolved → resolved`; change evidence/question/definition → `unresolved`. Không cấp revision/approval chỉ vì AI trả text.

## 3. ControlPolicy

- Tổng nguồn/result phải có basis truy vết duy nhất; đơn vị (VND/USD/count/ratio hoặc user-defined explicit unit) phải nhất quán. Tolerance là decimal string hữu hạn ≥0 theo cùng đơn vị, rationale không rỗng và áp trên total difference, không tùy ý per-row.
- `maxFanOut` decimal 1..100000 như existing hard range; default 1 chỉ proposal, user vẫn review. Global ratio không là bằng chứng one-to-one; per-key metrics được hiện riêng.
- Không áp dụng control total: `applicable=false`, reason rõ, tolerance/unit không bị dựng giả; user ack riêng và `unverified`. Hard failure không được ack override.
- Khớp `A−B=delta` chỉ áp dụng cùng source/measure basis và unit. Không dùng cùng tên output column để suy unit.

## 4. JoinKeyDecision và JoinEvidence

Mỗi current merge step: ordered pairs, handling=`keepUnmatched|exclude|alternativeKey|explicitMissingGroup`, `trimBeforeMissingCheck`, rationale và user confirmation. Alternative key chứa exact field IDs thuộc nguồn và types hợp lệ; no fuzzy matching.

Missing: null hoặc text rỗng; whitespace chỉ thiếu khi user chọn trim; composite thiếu nếu một component thiếu. Numeric 0, boolean false, text "0" không thiếu. Không tự đổi case, leading zeros, Unicode normalization hoặc key type. Trim (nếu chọn) là visible semantic operation, không mutate source cells.

JoinEvidence đo trên full sources: left/right rows, missing-key rows, nonunique complete-key groups, unmatched rows, projected expanded matches, maximum multiplicity và counts by multiplicity. Không trả raw key groups; aggregate bounded histograms (tối đa 20 buckets, remainder bucket), không để mất exact total/max. Actual per-key data được dùng cục bộ rồi bỏ.

Keep-unmatched tạo fresh helper bằng deterministic collision-free tên theo schema hiện tại; kiểm thêm cột/steps. Nonmissing helper `present`, missing left/right khác nhau. Original pairs giữ nguyên; cuối loại helper. Với Typed, user chọn proposal mới qua CAS; old history bytes không đổi. Với Assistant, new planHash/review bắt buộc. Group-missing giữ merge semantics hiện có sau consent.

## 5. WriteExpectation (volatile, immutable)

Fields: `expectationId`, `comparisonPolicy=excel-values-v1`, `mode`, exact workbook identity, approved artifact/preview/review binding, target scope, header, logical data dimensions, expected canonical cells/digest, marker requirement nếu có, old-tail rectangles cần trống, package fingerprint.

Scopes: `assistantNewSheet`, `typedResult`, `typedCacheRestore`, `advancedPreview`, `advancedSourceTable`, `advancedSourceRange`. Source Table dùng exact descriptor/identity và dimensions; source range giữ original anchor, new rectangle và old tails. Không thêm marker cells vào source để phục vụ recovery. Managed result dùng marker property/cell theo existing contract.

Expected lấy từ validated full values-only package hoặc approved Assistant result. Không display sample, không recompute từ nguồn mới khi recovery. Budget: ≤5 outstanding entries và ≤64 MiB canonical encoded expected data/owner/session; reusable immutable refs chỉ charge một lần; không nhân final/step caches. Không đủ budget thì chặn trước mutation; không evict evidence của active uncertain attempt để cấp write mới. Khi TTL/session close, xóa raw expected; UI giữ warning metadata trong pane đang sống, reopen chỉ có metadata không đủ proof.

## 6. Comparison policy `excel-values-v1`

| Value/scope | Chuẩn đối chiếu |
|---|---|
| Assistant Decimal/text | Chuỗi đúng từng ký tự/chữ số; giữ Text format và literal `=`; không ép numeric |
| Boolean | Type+value, không coi true là 1 |
| PQ numeric | Canonical IEEE754 binary64 bits từ XML numeric được parse theo cùng binary64 transport với Office.js. Không monetary tolerance cho write equality; chuẩn normalize -0 thành +0 |
| Date/time PQ | Underlying Excel numeric serial cùng workbook epoch; không parse chuỗi theo locale để tự đoán bằng nhau; declared schema/format semantics nêu riêng |
| Null/empty cell | Office empty value chấp nhận như empty transport token; digest giữ expected logical type khi hợp đồng cần (Assistant null được recover chỉ khi actual empty) |
| Text vs number | `"100"` khác numeric 100, trừ null/empty equivalence đã định nghĩa; không trim/casefold |
| Formula/error | No formula trong destination values-only; unexpected error mismatch/unavailable, không coi null; source formulas ngoài allowed write scope giữ nguyên |
| Logical dimensions | Explicit rectangle gồm header và all-null tails; Table actual dimensions phải đo. UsedRange vật lý có thể nhỏ hơn logical result nên không thay logical count |

Canonical policy phục vụ kiểm vận chuyển/ghi, không thay Decimal arithmetic, M semantics hoặc business null definitions. UTF-8 canonical encoding/version dùng chung expected và observed, với oracle viết tay cho Python/JS; không chỉ so hai implementation giống nhau.

## 7. WriteAttempt

Server-owned attempt ID, expectation ref/digest, exact approval/consumed binding, target, disposition và stored completion receipt nếu có. Owner: AssistantSessionStore, TypedPlanStore, AdvancedAttemptStore. Một attempt không dùng lẫn modes. Advanced preview consent và source-overwrite consent không thay thế nhau.

| State | Hành vi và transition |
|---|---|
| prepared | Có expectation/budget và preflight; chưa dispatch mutation; no claim applied |
| mutationPossible | Set latch trước khi dispatch Office mutation; bắt đầu từ đây không khẳng định zero write nếu lỗi |
| verifying | Đọc full expected scope trong chunks; incomplete là chưa verified |
| completed | Full matched observation + exact bindings và normal completion thành công; completion replay chỉ trả stored receipt |
| unknown | Write có thể xảy ra hoặc response lost; no write retry/approval reissue |
| mismatch | Current full observation khác expected; no rollback hay repair write |
| expired | Expected authority không còn; insufficient proof, no restore from XML |

`unknown/mismatch` được gắn observations mới nhưng recovery không chuyển thành một normal completion mới, không promote cache/Record và không cấp quyền. Nếu server đã completed trước mất phản hồi, lookup được stored receipt; historical success không có nghĩa target hiện tại còn khớp. Error trước dispatch chứng minh được mới trả `provenNotWritten`.

## 8. VerificationObservation

`observationId`, `attemptId`, timestamp, expectedDigest, current target identity, chunk coverage, formula/marker/structural/tail checks và `status=matches|mismatch|incomplete|insufficient`. Không giữ actual raw rows sau compare ngoài bounded current chunk. Observation cập nhật session verification evidence, không sửa immutable history/Record.

Max một active observation/attempt; begin có nonce chống trộn hai cửa sổ; chunks phải đúng ordinal/range, no gap/overlap/duplicate. Bị ngắt → incomplete. Finalize bắt buộc recheck identity/marker/source binding phù hợp; target/source version đổi trong quá trình thì incomplete/mismatch, không snapshot-atomic guarantee cho coauthoring. Unsupported concurrent workbook editing vẫn ngoài scope.

## 9. ActionEligibility và TrustPresentation

Eligibility chứa action, rows/columns/cells, headerIncluded, scope, policy cap/reason, supported API, review freshness và writeEligible. Actual result được re-evaluate trước freeze/approval; no new authority từ eligibility flag client. Trust axes độc lập: reconciliation, data quality, engine parity, write verification, save knowledge.

Save knowledge = observed state nếu có reliable host evidence; nếu không, `unknown` cùng thông báo add-in không tự Save. Quality count không đo được là unavailable, không thay 0. Reopen Assistant là metadata-only; Typed history có semantics nhưng không có old approval/preview/result.
