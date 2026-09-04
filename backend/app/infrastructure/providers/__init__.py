from ...config import settings


def get_ocr_provider(redis_client=None):
    from .ocr import CachedOcrProvider, MockOcrProvider, PaddleOcrProvider

    if settings.ocr_provider == "paddle":
        inner = PaddleOcrProvider(lang=settings.paddleocr_lang, use_angle_cls=settings.paddleocr_use_angle_cls)
    else:
        inner = MockOcrProvider()

    # 包一层缓存装饰器：upload 实时预览的结果供 EvidenceAgent 复用，避免二次推理
    if getattr(settings, "ocr_cache_enabled", True):
        return CachedOcrProvider(
            inner,
            redis_client=redis_client,
            ttl=getattr(settings, "ocr_cache_ttl", 3600),
            enabled=True,
        )
    return inner


def get_llm_provider():
    from .llm import MockLLMProvider, OllamaLLMProvider

    if settings.llm_provider == "ollama":
        return OllamaLLMProvider(base_url=settings.ollama_base_url, model=settings.ollama_model)
    return MockLLMProvider()


def get_risk_provider():
    from .risk import LLMRiskProvider, MockRiskProvider

    if settings.risk_provider == "ollama":
        return LLMRiskProvider(get_llm_provider())
    return MockRiskProvider()


def get_sentiment_provider():
    from .sentiment import LLMSentimentProvider, MockSentimentProvider

    if settings.sentiment_provider == "ollama":
        return LLMSentimentProvider(get_llm_provider())
    return MockSentimentProvider()


def get_combined_risk_provider():
    """获取合并风险提供者（优化改造：合并 Fraud + Sentiment）

    通过 combined_risk_provider 配置选择 mock 或 llm 模式。
    此 provider 同步返回 fraud_score + sentiment_score + risk_level。
    """
    from .combined import LLMCombinedRiskProvider, MockCombinedRiskProvider

    if settings.combined_risk_provider == "llm":
        return LLMCombinedRiskProvider(get_llm_provider())
    return MockCombinedRiskProvider()


def get_refund_provider():
    from .refund import MockRefundProvider

    return MockRefundProvider()


def get_order_verify_provider():
    from .order_verify import ShopOrderAwareOrderVerificationProvider

    return ShopOrderAwareOrderVerificationProvider()


def get_product_consistency_provider():
    from .product_consistency import MockProductConsistencyProvider

    return MockProductConsistencyProvider()


def get_asr_provider():
    """语音转写 Provider（定稿 §4.8）：mock 明示演示模式，dashscope 为真实云端转写。"""
    from .asr import DashScopeASRProvider, MockASRProvider

    if settings.asr_provider == "dashscope":
        return DashScopeASRProvider(
            api_key=settings.dashscope_api_key,
            model=settings.asr_model,
            base_url=settings.asr_api_base,
        )
    return MockASRProvider()


def get_vision_provider():
    """男装图片分类 Provider（定稿 §4.3）：mock 明示待复核，ollama_vl 为本地视觉模型。"""
    from .vision import MockVisionProvider, OllamaVisionProvider

    if settings.vision_provider == "ollama_vl":
        return OllamaVisionProvider(
            base_url=settings.ollama_base_url,
            model=settings.vision_model,
            threshold=settings.vision_confidence_threshold,
        )
    return MockVisionProvider()
