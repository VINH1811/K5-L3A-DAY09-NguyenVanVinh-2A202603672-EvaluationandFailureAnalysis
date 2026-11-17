"""Regression test from docs/trace_case.md: seeded_regression C-014@11 (FM-05 pre_deducted, FM-08 misreport).

The agent subtracts the earlier 30.000đ shipping refund itself (event 5 `proposal` 120.000) and the host
subtracts it again, so the ledger holds 90.000đ while the reply says 120.000đ. The graders must fail it
on the buggy variant and pass the same claim@seed on `fixed`.
"""
import pytest

pytestmark = pytest.mark.student
CLAIM, SEED = "C-014", 11


def _grade(shape: str) -> dict:
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders, trace_case

    case = trace_case.investigate(shape, CLAIM, SEED)
    ctx = EvaluatorContext(name=f"{shape}:{CLAIM}@{SEED}", inputs={}, metadata=None,
                           expected_output=case["label"], output=case["trial"], duration=0.0,
                           _span_tree=None, attributes={}, metrics={})
    kinds = [e.get("kind") for e in case["trial"]["events"]]
    return {"kinds": kinds, "trial": case["trial"],
            "amount_ok": graders.RefundAmountCorrect().evaluate(ctx).value,
            "reply_ok": graders.ReplyMatchesLedger().evaluate(ctx).value}


def test_lab9_trace_case_pre_deducted_is_caught():
    g = _grade("seeded_regression")
    # First wrong step: a `proposal` that differs from the quote, right after reading refund history.
    assert g["kinds"].index("refund_history") + 1 == g["kinds"].index("proposal")
    assert g["trial"]["snapshot"]["refund_vnd"] == 90000
    assert g["amount_ok"] is False      # ledger 90.000 != label 120.000 (FM-05)
    assert g["reply_ok"] is False       # reply says 120.000, ledger holds 90.000 (FM-08)


def test_lab9_trace_case_fixed_passes():
    g = _grade("fixed")
    assert "proposal" not in g["kinds"]
    assert g["trial"]["snapshot"]["refund_vnd"] == 120000
    assert g["amount_ok"] is True and g["reply_ok"] is True
