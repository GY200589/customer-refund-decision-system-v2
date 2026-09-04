"""CombinedRiskProvider — 合并欺诈评分与情绪分析为一次 LLM 调用

成本优化：原方案分别调用 LLM 做 Fraud 和 Sentiment → 2 次 LLM 调用，
合并后 1 次调用同时返回 fraud_score + sentiment_score + risk_level + risk_factors。

返回结构与原 RiskProvider + SentimentProvider 保持一致，确保下游 DecisionPolicy 无感知。
"""
from dataclasses import dataclass, field
from typing import List, Optional

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")


@dataclass
class CombinedRiskResult:
    fraud_score: int                     # 0-100
    sentiment_score: int                 # 0-100
    risk_level: str                      # LOW / MEDIUM / HIGH
    risk_factors: List[str] = field(default_factory=list)


class MockCombinedRiskProvider:
    """确定性合并评分（Mock 模式，用于测试）"""

    def assess(self, order_id: str, amount_cent: int, complaint_text: str, risk_flags: dict,
               evidence_present: bool = True, ocr_confidence: float = 1.0) -> CombinedRiskResult:
        factors = []
        flags = risk_flags or {}

        # 欺诈评分
        malicious = any(k in (complaint_text or "") for k in ("恶意", "薅羊毛", "刷单", "套现"))
        if malicious or flags.get("group_complaint"):
            fraud_score = 85
            factors.append("疑似恶意退款/薅羊毛")
        elif not evidence_present:
            fraud_score = 60
            factors.append("证据缺失")
        elif amount_cent >= 20000:
            fraud_score = 45
            factors.append("金额较大，需关注")
        else:
            fraud_score = 20
            factors.append("无异常")

        # 情绪评分
        high_risk_flags = ("regulatory_escalation", "litigation", "media_exposure",
                           "privacy_breach", "group_complaint")
        if any(flags.get(f) for f in high_risk_flags):
            sentiment_score = 90
            risk_level = "HIGH"
            factors.append("舆情风险高")
        elif any(k in (complaint_text or "") for k in ("监管", "曝光", "起诉", "诉讼", "媒体")):
            sentiment_score = 85
            risk_level = "HIGH"
            factors.append("舆情风险中等")
        elif any(k in (complaint_text or "") for k in ("生气", "投诉", "不满", "愤怒")):
            sentiment_score = 55
            risk_level = "MEDIUM"
        else:
            sentiment_score = 20
            risk_level = "LOW"

        return CombinedRiskResult(
            fraud_score=fraud_score,
            sentiment_score=sentiment_score,
            risk_level=risk_level,
            risk_factors=factors,
        )


class LLMCombinedRiskProvider:
    """LLM 合并评分（一次调用同时返回 fraud + sentiment）"""

    def __init__(self, llm):
        self.llm = llm

    def assess(self, order_id: str, amount_cent: int, complaint_text: str, risk_flags: dict,
               evidence_present: bool = True, ocr_confidence: float = 1.0) -> CombinedRiskResult:
        prompt = (
            "请评估以下退款申请的欺诈风险和舆情情绪，只返回 JSON：\n"
            "{\n"
            '  "fraud_score": 0-100 的整数（越高越可疑），\n'
            '  "sentiment_score": 0-100 的整数（越高越负面），\n'
            '  "risk_level": "LOW|MEDIUM|HIGH",\n'
            '  "risk_factors": ["字符串数组"]\n'
            "}\n"
            f"订单={order_id} 金额分={amount_cent} 证据={evidence_present} "
            f"投诉文本={complaint_text} 风险信号={risk_flags}"
        )
        data = self.llm.complete_json(prompt)
        return CombinedRiskResult(
            fraud_score=max(0, min(100, int(data.get("fraud_score", 20)))),
            sentiment_score=max(0, min(100, int(data.get("sentiment_score", 20)))),
            risk_level=data.get("risk_level", "LOW").upper() if data.get("risk_level", "LOW").upper() in RISK_LEVELS else "LOW",
            risk_factors=data.get("risk_factors", []),
        )
