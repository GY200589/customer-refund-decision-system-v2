from app.policy.decision_policy import (
    APPROVE,
    HUMAN_REVIEW,
    REJECT,
    DecisionInput,
    decide,
)


def _input(**kw):
    base = dict(
        amount_cent=12800,
        ocr_confidence=0.95,
        fraud_score=20,
        sentiment_score=20,
        risk_level="LOW",
        risk_flags={},
        evidence_present=True,
    )
    base.update(kw)
    return DecisionInput(**base)


def test_low_amount_low_risk_auto_approve():
    assert decide(_input()).decision == APPROVE


def test_amount_over_threshold_goes_human_review():
    r = decide(_input(amount_cent=35000))
    assert r.decision == HUMAN_REVIEW
    assert "金额超过阈值" in r.reason


def test_low_ocr_confidence_goes_human_review():
    assert decide(_input(ocr_confidence=0.55)).decision == HUMAN_REVIEW


def test_ocr_none_goes_human_review():
    assert decide(_input(ocr_confidence=None)).decision == HUMAN_REVIEW


def test_fraud_reject_threshold():
    assert decide(_input(fraud_score=85)).decision == REJECT


def test_fraud_review_threshold():
    assert decide(_input(fraud_score=60)).decision == HUMAN_REVIEW


def test_high_risk_flag_goes_human_review():
    assert decide(_input(risk_flags={"media_exposure": True})).decision == HUMAN_REVIEW
    assert decide(_input(risk_flags={"regulatory_escalation": True})).decision == HUMAN_REVIEW


def test_high_risk_level_goes_human_review():
    assert decide(_input(risk_level="HIGH")).decision == HUMAN_REVIEW


def test_no_evidence_goes_human_review():
    r = decide(_input(evidence_present=False))
    assert r.decision == HUMAN_REVIEW
    assert "证据不足" in r.reason


def test_injected_threshold_overrides_amount():
    # 默认阈值 30000 分，350 元应转人工；注入更高阈值后应自动批准
    assert decide(_input(amount_cent=35000)).decision == HUMAN_REVIEW
    r = decide(
        _input(amount_cent=35000),
        thresholds={"amount_human_review_threshold_cent": 100000},
    )
    assert r.decision == APPROVE


def test_injected_threshold_overrides_ocr():
    # 默认 OCR 阈值 0.80，0.70 转人工；注入更宽松阈值后自动批准
    assert decide(_input(ocr_confidence=0.70)).decision == HUMAN_REVIEW
    r = decide(
        _input(ocr_confidence=0.70),
        thresholds={"ocr_confidence_threshold": 0.60},
    )
    assert r.decision == APPROVE


def test_ocr_amount_mismatch_always_goes_human_review():
    r = decide(_input(risk_flags={"ocr_amount_mismatch": True, "ocr_detected_amounts_cent": [9900]}))
    assert r.decision == HUMAN_REVIEW
    assert "OCR 凭证金额" in r.reason


def test_amount_above_recommendation_goes_human_review():
    r = decide(_input(risk_flags={"amount_exceeds_recommendation": True, "recommended_amount_cent": 2000}))
    assert r.decision == HUMAN_REVIEW
    assert "系统建议金额" in r.reason


def test_high_history_rate_does_not_block_low_ratio_partial_refund():
    r = decide(_input(refund_rate=0.9, risk_flags={"requested_ratio": 0.15}))
    assert r.decision == APPROVE


def test_high_history_rate_with_full_refund_is_rejected():
    r = decide(_input(refund_rate=0.9, risk_flags={"requested_ratio": 1.0}))
    assert r.decision == REJECT


def test_optional_evidence_reason_can_auto_approve_without_upload():
    r = decide(_input(
        evidence_present=False,
        ocr_confidence=None,
        risk_flags={"evidence_required": False, "requested_ratio": 1.0},
    ))
    assert r.decision == APPROVE
