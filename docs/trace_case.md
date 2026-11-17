# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case: `seeded_regression` C-014@11 (FM-05 pre_deducted, kéo theo FM-08)

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, report `E-seeded_regression-20261117-a169` (`src/reports/eval_seeded_regression.json`, eval set `a169423d03e8`) |
| Triệu chứng | Grader Lab 8 trả FAIL (`proposal_mismatch`). `refund_amount_correct` FAIL: ledger ghi **90.000đ**, nhãn là **120.000đ**. `reply_matches_ledger` FAIL: reply "Dạ, LogiX đã hoàn **120.000đ** cho đơn O-515" nhưng ledger chỉ ghi 90.000đ. Status `resolved` vẫn đúng nhãn, nên nếu chỉ nhìn status thì không thấy lỗi. |
| Bước sai đầu tiên | **Event 5 `proposal {"amount_vnd": 120000}`**: agent tự trừ 30.000đ đã hoàn trước đó khỏi quote 150.000đ, rồi mới gửi lên host. |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng hợp đồng, không mang secret. Event 2 `investigator` đọc đúng đơn O-515 (`delivered_late`, thuộc P-100). Event 3 `quote` 150.000đ với clause `SHIP-LATE-03` và `DMG-04`, khớp `proposal_amount` của nhãn và khớp `fixed`. Event 4 `refund_history` đọc đúng dữ kiện (đã hoàn 1 lần, 30.000đ); đọc lịch sử không sai, **dùng nó để tự trừ** mới sai. Từ event 5 trở đi: host (`issue_refund`) lại trừ 30.000đ thêm một lần, ghi 90.000đ, và event 6 `reply` báo số agent tự tính (120.000đ). |
| Failure mode | **FM-05 pre_deducted** là gốc (orchestration/state: agent và host cùng giữ phần "trừ tiền đã hoàn"). **FM-08 misreport** là hệ quả, vì reply báo số đề xuất thay vì số đã ghi vào ledger. Xem `docs/failure_taxonomy.md`. |
| Đối chứng | `fixed C-014@11`: event 3 `quote` 150.000đ, **không có** event `refund_history` hay `proposal`. Agent gửi đúng 150.000đ, host tự trừ 30.000đ nên ledger ghi 120.000đ, bằng nhãn. Event 4 `reply` nói 120.000đ, khớp ledger. Lab 8 PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py`, chạy cùng `pytest -m student -k "lab9 and not advanced"`. `test_lab9_trace_case_pre_deducted_is_caught` kiểm tra rằng `proposal` đứng ngay sau `refund_history`, ledger bằng 90.000, và `RefundAmountCorrect` cùng `ReplyMatchesLedger` đều trả False. `test_lab9_trace_case_fixed_passes` kiểm tra cùng claim@seed trên `fixed`: không có `proposal`, ledger 120.000, cả hai grader trả True. Đã chạy: fail đúng trên variant lỗi, pass trên `fixed` (13/13 test student xanh). Gate trên report đầy đủ cũng chặn: `refund_amount_correct` Δ −0.129, `reply_matches_ledger` Δ −0.214. |
| Chưa chắc chắn | Trace không cho biết agent *vì sao* tự trừ (prompt hay logic). MockLLM là mã cố định, nên ở đây đó là công tắc `pre_deducted`; với LLM thật cần xem prompt và tool schema. Trace cũng không chứng minh host luôn trừ lịch sử hoàn tiền ở mọi chính sách: điều này mới được quan sát trên ca hoàn phí ship cộng bồi thường hỏng hàng (C-013, C-014). |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
