# Judge audit

Lệnh chạy: `python -m lab9.judge --csv <file> --audit 5`. Backend là replay, tức là verdict của judge đã lưu sẵn trong CSV, n = 100 mỗi tiêu chí. Lớp dương là FAIL, vì việc của judge là **tìm lỗi**.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng**, chỉ để báo cáo, không đặt làm gate cho tiền hay approval |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Trượt** κ và Recall (exit 1) | **loại**, không dùng làm gate |

Ma trận nhầm lẫn:
- **tone_ok:** tp = 24, fp = 4, fn = 6, tn = 66. Tỉ lệ FAIL judge quan sát được là 0.28; sau hiệu chỉnh Rogan-Gladen là **0.30**, khớp tỉ lệ thật theo nhãn người (30/100).
- **helpful:** tp = 9, fp = 0, fn = 21, tn = 70. Tỉ lệ FAIL judge quan sát được là **0.09**, trong khi tỉ lệ thật là **0.30**. Judge bỏ sót 70% số reply kém.

## Vì sao `helpful` bị loại dù Precision = 1.0
Precision = 1.0 chỉ cho biết khi judge nói FAIL thì nó đúng. Nhưng judge hiếm khi nói FAIL: chỉ 9/30 reply kém bị bắt (Recall 0.3, κ 0.375). Đặt judge này làm gate thì gate sẽ gần như luôn cho merge.

Phân tích 21 ca bỏ sót (fn) theo cột `human_failure`:

| Loại lỗi người gán | Số reply FAIL | Judge bắt được | Bỏ sót |
|---|---|---|---|
| sai tiền (reply nói số khác ledger) | 18 | **0** | 18 |
| sai xưng hô ("Ok bạn") | 3 | 0 | 3 |
| giọng cụt | 4 | 4 | 0 |
| không hỏi lại mã đơn | 3 | 3 | 0 |
| trả lời lạc đề | 2 | 2 | 0 |

Hai nguyên nhân gốc:
1. **Judge không thấy ledger.** Judge chỉ đọc reply, nên không thể biết "đã hoàn 55.000đ" là sai khi ledger ghi 40.000đ. Đây đúng là FM-08 (misreport) trong taxonomy. Lỗi về tiền phải chấm bằng code so với ledger, không giao cho judge.
2. **Thiên kiến độ dài và lời xin lỗi.** 13/18 ca "sai tiền" bị bỏ sót là reply dài, xin lỗi 2–3 lần (ví dụ HL-016, HL-053, HL-090). Judge chấm "nghe có vẻ chu đáo" thay vì "có đúng không".

## Audit thủ công 10 bất đồng

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú và hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | **Người** | Xưng "em" và dùng "nha" là quá suồng sã với khách khiếu nại. **Rubric tone:** thêm quy tắc "xưng LogiX/anh-chị, không xưng em/bạn, không dùng 'nha/nhé'" kèm 2 ví dụ FAIL. |
| 2 | H-017 "Dạ, bạn ơi… rồi nha" | PASS | FAIL | **Người** | Cùng lỗi xưng hô: chữ "Dạ" ở đầu làm judge tưởng là lịch sự. Rubric: chấm theo **cách xưng hô**, không chấm theo từ mở đầu. |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | **Người** | Câu mang giọng ra lệnh, đuổi khách. Rubric: thêm tiêu chí "không chặn khách liên hệ", ví dụ FAIL là "không cần nhắn thêm". |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ…" | FAIL | PASS | **Người** | Câu ngắn nhưng đủ ý; judge phạt vì thiếu lời xin lỗi. Rubric: ghi rõ "**không bắt buộc xin lỗi**; ngắn gọn và đủ ý là PASS". Sửa này cũng giảm thiên kiến độ dài. |
| 5 | H-051 "LogiX đã refund 90.000đ…" | FAIL | PASS | **Người** | Style guide CS của LogiX cho phép dùng từ "refund". Rubric: thêm danh sách từ tiếng Anh được phép (refund, voucher, ship). |
| 6 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | **Người** | Reply hứa điều hệ thống chưa làm. Lỗi này không phải về giọng điệu mà là về **nội dung**, nên chuyển sang grader code: reply không được chứa lời hứa tương lai về tiền ("sẽ hoàn thêm"). Rubric tone ghi rõ: hứa hẹn ngoài kết quả là FAIL. |
| 7 | H-070 "…ạ 😂😂" | PASS | FAIL | **Người** | Emoji cười trong ngữ cảnh khiếu nại là không phù hợp. Rubric: "không dùng emoji trong phản hồi khiếu nại"; có thể thêm bộ lọc regex chạy trước judge. |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện…" | FAIL | PASS | **Judge** | Ghi chú trong CSV xác nhận nhãn người sai do đọc nhầm ticket. **Hành động:** sửa nhãn trong bộ nhãn người. Kết luận: cần người thứ hai kiểm tra nhãn (double-label) cho các ca bất đồng. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | **Người** (có thể tranh luận) | Lặp chữ do lỗi gõ, không ảnh hưởng thái độ. Rubric: ghi rõ "lỗi gõ nhỏ không làm FAIL tone"; nếu cần thì tách thành tiêu chí riêng `typo`. |
| 10 | H-094 "Da, LogiX da hoan… xin loi…" | PASS | FAIL | **Người** | Mất dấu tiếng Việt, trông như dịch máy. Rubric: "tiếng Việt phải có dấu đầy đủ" là điều kiện bắt buộc để PASS; có thể kiểm bằng code (tỉ lệ ký tự có dấu). |

Tổng kết: trong 10 bất đồng của tone, người đúng ở 9 ca, judge đúng ở 1 ca (H-081). Bốn ca fp của judge chủ yếu do judge quá khắt khe về hình thức (thiếu xin lỗi, có tiếng Anh, lỗi gõ). Sáu ca fn chủ yếu do judge bị chữ "Dạ" đánh lừa và bỏ qua xưng hô, emoji, lời hứa.

## Kết luận
- **Loại `helpful`** khỏi gate: κ 0.375 < 0.6 và Recall 0.30 < 0.7 (fn = 21/30). Judge này bỏ sót toàn bộ 18 lỗi sai tiền, vì nó không đọc ledger. Thay thế:
  - Phần "đúng tiền" chấm bằng code. `refund_amount_correct` đọc ledger. Metric FM-08 ở M3 so số tiền trong reply với `snapshot.refund_vnd`.
  - Phần "giọng cụt / lạc đề / không hỏi mã đơn" giữ lại để tham khảo. Đây là phần judge làm tốt (9/9), nhưng mới có 9 mẫu, chưa đủ để đặt sàn.
- **Dùng `tone_ok`** như một metric báo cáo, không gắn `blocking`. Tỉ lệ lỗi tone báo cáo phải là con số đã hiệu chỉnh Rogan-Gladen (0.30), không phải con số thô (0.28).
- **Tiền và approval không bao giờ giao cho judge.** Các metric chặn merge đều là grader code: `approval_bypass`, `secret_leak`, `refund_amount_correct`, `pass_rate`.
- **Rủi ro còn lại:**
  - Judge chỉ được kiểm trên 100 mẫu replay đã công khai, và chính các mẫu này được dùng để sửa rubric. Vì vậy con số trên là lạc quan. Cần một bộ nhãn người mới (held-out) để đo lại sau khi sửa rubric.
  - Nhãn người cũng có lỗi (H-081). Cần double-label và kiểm tra lại các ca bất đồng trước khi dùng nhãn làm sự thật.
  - Với n = 100, khoảng tin cậy của κ còn rộng, nên κ = 0.757 chỉ vượt sàn 0.6 với biên độ vừa phải.
