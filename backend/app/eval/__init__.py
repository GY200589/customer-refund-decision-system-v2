"""Eval 评测模块 — LLM-as-a-Judge 自动化评测

面向客诉退赔决策领域，提供：
- Golden Dataset（10 条客诉退赔测试用例）
- 三维度评分体系（决策正确性、金额边界安全、理由质量）
- MockJudge（离线确定性评分）& LLMJudge（DeepSeek API 评分）
- 评测指标计算与报告生成
"""

from .golden_dataset import load_golden_dataset
from .judge.base import BaseJudge
from .judge.mock_judge import MockJudge
from .judge.llm_judge import LLMJudge
from .metrics import compute_metrics

__all__ = [
    "load_golden_dataset",
    "BaseJudge",
    "MockJudge",
    "LLMJudge",
    "compute_metrics",
]