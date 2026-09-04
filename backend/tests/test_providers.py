from app.infrastructure.providers.ocr import MockOcrProvider
from app.infrastructure.providers.risk import MockRiskProvider
from app.infrastructure.providers.sentiment import MockSentimentProvider


def test_mock_ocr_high_confidence():
    r = MockOcrProvider().extract("invoice.jpg", "h1", "hash1", 12800)
    assert r.overall_confidence == 0.95
    assert "128.00" in r.text


def test_mock_ocr_low_confidence():
    r = MockOcrProvider().extract("blur.jpg", "h2", "hash2", 12800)
    assert r.overall_confidence == 0.55


def test_mock_risk_malicious():
    r = MockRiskProvider().assess("o1", 12800, True, "这是恶意薅羊毛", {})
    assert r.fraud_score == 85


def test_mock_risk_low():
    r = MockRiskProvider().assess("o1", 12800, True, "系统故障导致错误扣费", {})
    assert r.fraud_score == 20


def test_mock_sentiment_high_flag():
    r = MockSentimentProvider().analyze("", {"media_exposure": True})
    assert r.risk_level == "HIGH"


def test_mock_sentiment_low():
    r = MockSentimentProvider().analyze("系统故障导致错误扣费", {})
    assert r.risk_level == "LOW"
