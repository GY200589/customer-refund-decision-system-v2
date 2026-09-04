from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RiskResult:
    fraud_score: int
    risk_factors: list = field(default_factory=list)


class RiskProvider(ABC):
    @abstractmethod
    def assess(
        self,
        order_id: str,
        amount_cent: int,
        evidence_present: bool,
        complaint_text: str,
        risk_flags: dict,
    ) -> RiskResult:
        raise NotImplementedError


class MockRiskProvider(RiskProvider):
    """确定性欺诈风险评估：含恶意关键字/群体信号判高风险，金额较大判中风险。"""

    def assess(self, order_id, amount_cent, evidence_present, complaint_text, risk_flags):
        factors = []
        score = 20
        flags = risk_flags or {}
        malicious = any(k in (complaint_text or "") for k in ("恶意", "薅羊毛", "刷单", "套现"))
        if malicious or flags.get("group_complaint"):
            score = 85
            factors.append("疑似恶意退款/薅羊毛")
        elif not evidence_present:
            score = 60
            factors.append("证据缺失")
        elif amount_cent >= 20000:
            score = 45
            factors.append("金额较大，需关注")
        else:
            factors.append("无异常")
        return RiskResult(fraud_score=score, risk_factors=factors)


class LLMRiskProvider(RiskProvider):
    def __init__(self, llm):
        self.llm = llm

    def assess(self, order_id, amount_cent, evidence_present, complaint_text, risk_flags):
        prompt = (
            "请评估以下退款申请的欺诈风险，只返回 JSON："
            '{"fraud_score": 0-100 的整数, "risk_factors": ["字符串数组"]}。'
            f"订单={order_id} 金额分={amount_cent} 证据={evidence_present} "
            f"投诉文本={complaint_text} 风险信号={risk_flags}"
        )
        data = self.llm.complete_json(prompt)
        score = int(data.get("fraud_score", 50))
        return RiskResult(fraud_score=max(0, min(100, score)), risk_factors=data.get("risk_factors", []))
