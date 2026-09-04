from app.services.refund_guard import amount_exceeds_recommendation, quote_refund


def test_minor_quality_issue_recommends_partial_refund():
    quote = quote_refund(20_000, "quality", "minor")
    assert quote["recommended_amount_cent"] == 3_000
    assert quote["recommended_rate"] == 15
    assert quote["is_partial"] is True


def test_severe_quality_issue_can_recommend_full_refund():
    quote = quote_refund(20_000, "quality", "severe")
    assert quote["recommended_amount_cent"] == 20_000
    assert quote["is_partial"] is False


def test_small_overage_is_tolerated_but_full_claim_is_flagged():
    assert amount_exceeds_recommendation(3_400, 3_000) is False
    assert amount_exceeds_recommendation(20_000, 3_000) is True
