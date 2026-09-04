"""Provider 行为测试：ASR（mock 诚实标注）、Vision（mock 待复核）、评测报告（定稿 §4.3/§4.8/§4.9）。"""
import pytest

from app.config import settings
from app.infrastructure.providers.asr import ASRError, DashScopeASRProvider, MockASRProvider
from app.infrastructure.providers.vision import MockVisionProvider


def test_mock_asr_is_honest_demo():
    """mock ASR 必须明示演示模式，不得伪装真实转写（C11）。"""
    result = MockASRProvider().transcribe(b"fake-audio", "audio/webm")
    assert result["demo"] is True
    assert result["provider"] == "mock"
    assert "演示模式" in result["text"]


def test_dashscope_asr_requires_key():
    provider = DashScopeASRProvider(api_key="", model="fun-asr-flash", base_url="http://localhost:9")
    with pytest.raises(ASRError):
        provider.transcribe(b"x", "audio/wav")


def test_mock_vision_needs_review():
    result = MockVisionProvider().classify("whatever.jpg")
    assert result["main_category"] == "unknown"
    assert result["needs_review"] is True
    assert result["demo"] is True


def test_assistant_eval_report(db_setup):
    """评测 runner 可跑完 40 条样本并输出全部指标（定稿 §7.3）。"""
    from app.eval.run_assistant_eval import run_eval

    report = run_eval()
    assert report["total"] >= 40
    m = report["metrics"]
    for key in (
        "intent_micro_f1", "intent_macro_f1", "multi_intent_exact_rate",
        "entity_accuracy", "rag_retrieval_hit_rate", "citation_coverage",
        "unsupported_answer_rate", "action_accuracy", "avg_latency_ms", "voice_vs_text",
    ):
        assert key in m, f"缺少指标 {key}"
    assert m["voice_vs_text"]["text"]["n"] > 0
    assert m["voice_vs_text"]["voice"]["n"] > 0
    # 验收下限：核心指标必须达到可演示水平（规则引擎口径）
    assert m["intent_micro_f1"] >= 0.7
    assert m["rag_retrieval_hit_rate"] >= 0.8
    assert m["action_accuracy"] >= 0.7


def test_assistant_report_persisted(db_setup):
    from app.eval.run_assistant_eval import list_reports, load_report, run_eval

    report = run_eval()
    items = list_reports()
    assert any(i["report_id"] == report["report_id"] for i in items)
    loaded = load_report(report["report_id"])
    assert loaded["total"] == report["total"]


def test_asr_provider_config_defaults():
    """配置默认 mock；密钥从 .env 读入但 provider 开关不受影响。"""
    assert settings.asr_provider in ("mock", "dashscope")
    assert settings.vision_provider in ("mock", "ollama_vl")
    assert 0 < settings.vision_confidence_threshold < 1
