"""用户长期退款率（反薅羊毛）策略单测。"""
from app.policy.decision_policy import APPROVE, HUMAN_REVIEW, REJECT, DecisionInput, decide


def _input(**kw):
    base = dict(
        amount_cent=12800,
        ocr_confidence=0.95,
        fraud_score=20,
        sentiment_score=20,
        risk_level="LOW",
        risk_flags={},
        evidence_present=True,
        refund_rate=0.0,
    )
    base.update(kw)
    return DecisionInput(**base)


def test_new_user_auto_approve():
    """新用户退款率为 0，其他条件低风险时应自动批准。"""
    assert decide(_input(refund_rate=0.0)).decision == APPROVE


def test_refund_rate_reject_threshold():
    """高历史退款率叠加本次高比例申请时拒绝。"""
    r = decide(_input(refund_rate=0.85, amount_cent=100, risk_flags={"requested_ratio": 1.0}))
    assert r.decision == REJECT
    assert "退款率" in r.reason
    assert "职业薅羊毛" in r.reason


def test_refund_rate_review_threshold():
    """历史退款率达到复核线且本次申请 80% 以上时转人工。"""
    r = decide(_input(refund_rate=0.6, amount_cent=100, risk_flags={"requested_ratio": 0.8}))
    assert r.decision == HUMAN_REVIEW
    assert "退款率" in r.reason


def test_refund_rate_does_not_block_low_ratio_request():
    """历史记录多不能单独定罪，建议范围内的部分退款仍可自动通过。"""
    r = decide(_input(refund_rate=0.85, amount_cent=100, risk_flags={"requested_ratio": 0.15}))
    assert r.decision == APPROVE


def test_refund_rate_injected_thresholds():
    """阈值可被运行时覆盖。"""
    r = decide(
        _input(refund_rate=0.4, risk_flags={"requested_ratio": 1.0}),
        thresholds={"refund_rate_review_threshold": 0.3, "refund_rate_reject_threshold": 0.5},
    )
    assert r.decision == HUMAN_REVIEW
    r2 = decide(
        _input(refund_rate=0.55, risk_flags={"requested_ratio": 1.0}),
        thresholds={"refund_rate_review_threshold": 0.3, "refund_rate_reject_threshold": 0.5},
    )
    assert r2.decision == REJECT
