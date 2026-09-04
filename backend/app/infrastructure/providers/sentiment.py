from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SentimentResult:
    sentiment_score: int  # 0-100，越高越负面
    risk_level: str  # LOW / MEDIUM / HIGH


HIGH_RISK_FLAGS = (
    "regulatory_escalation",
    "litigation",
    "media_exposure",
    "privacy_breach",
    "group_complaint",
)


class SentimentProvider(ABC):
    @abstractmethod
    def analyze(self, complaint_text: str, risk_flags: dict) -> SentimentResult:
        raise NotImplementedError


class MockSentimentProvider(SentimentProvider):
    def analyze(self, complaint_text: str, risk_flags: dict) -> SentimentResult:
        flags = risk_flags or {}
        if any(flags.get(f) for f in HIGH_RISK_FLAGS):
            return SentimentResult(90, "HIGH")
        text = complaint_text or ""
        if any(k in text for k in ("监管", "曝光", "起诉", "诉讼", "媒体")):
            return SentimentResult(85, "HIGH")
        if any(k in text for k in ("生气", "投诉", "不满", "愤怒")):
            return SentimentResult(55, "MEDIUM")
        return SentimentResult(20, "LOW")


class LLMSentimentProvider(SentimentProvider):
    def __init__(self, llm):
        self.llm = llm

    def analyze(self, complaint_text: str, risk_flags: dict) -> SentimentResult:
        prompt = (
            "请分析以下客诉文本的情绪与舆情风险，只返回 JSON："
            '{"sentiment_score": 0-100 的整数, "risk_level": "LOW|MEDIUM|HIGH"}。'
            f"文本={complaint_text} 风险信号={risk_flags}"
        )
        data = self.llm.complete_json(prompt)
        score = int(data.get("sentiment_score", 20))
        return SentimentResult(
            sentiment_score=max(0, min(100, score)),
            risk_level=data.get("risk_level", "LOW").upper(),
        )
