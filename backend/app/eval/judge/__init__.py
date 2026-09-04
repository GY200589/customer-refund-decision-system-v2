"""Judge 评测基类 — 所有评分器的公共接口

三维度评分体系（面向客诉退赔决策领域）：
- 决策正确性 (40分)：预期决策是否与实际决策一致
- 金额边界安全 (30分)：是否正确处理金额阈值边界
- 理由质量 (30分)：决策理由是否清晰、完整、合规
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseJudge(ABC):
    """Judge 基类"""

    def __init__(self):
        self.name = "base"

    @abstractmethod
    def evaluate(self, case: Dict[str, Any], actual_decision: str, actual_reason: str = "") -> float:
        """评测单个用例，返回 0-100 的分数"""
        pass

    def score_to_grade(self, score: float) -> str:
        """将分数转换为等级"""
        if score >= 90:
            return "S"
        elif score >= 80:
            return "A"
        elif score >= 70:
            return "B"
        elif score >= 60:
            return "C"
        else:
            return "D"

    def get_dimension_scores(self, case: Dict[str, Any], actual_decision: str, actual_reason: str) -> Dict[str, float]:
        """计算各维度评分"""
        return {
            "decision_accuracy": 0.0,   # 决策正确性 (0-40)
            "amount_boundary": 0.0,     # 金额边界安全 (0-30)
            "reason_quality": 0.0,      # 理由质量 (0-30)
        }