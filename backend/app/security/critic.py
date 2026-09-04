"""CriticAgent — 注入检测引擎（统一入口）

组合规则快速路 + LLM 深度检测两级检测。
"""
import logging
from typing import Optional

from .critic_rules import CriticEngine as CriticRuleEngine
from .critic_llm import CriticLLMEngine
from .critic_rules import CriticResult, CRITIC_RULES

logger = logging.getLogger(__name__)


class CriticAgent:
    """CriticAgent — 注入检测引擎

    两级检测：
    1. 规则快速路（inline）：预编译正则，O(1) 匹配
    2. LLM 深度检测（可选）：语义级分析
    """

    def __init__(self, rule_engine: Optional[CriticRuleEngine] = None,
                 llm_engine: Optional[CriticLLMEngine] = None,
                 enabled: bool = True):
        self.rule_engine = rule_engine or CriticRuleEngine(rules=CRITIC_RULES)
        self.llm_engine = llm_engine
        self.enabled = enabled

    def check(self, text: str, risk_flags: Optional[dict] = None) -> CriticResult:
        """注入检测入口

        先走规则快速路，PASS 后走 LLM 深度检测。
        """
        if not self.enabled or not text:
            return CriticResult(action="PASS")

        # 第一级：规则快速路
        rule_result = self.rule_engine.check(text, risk_flags)
        if rule_result.action != "PASS":
            logger.info("CriticAgent 规则检测拦截: %s", rule_result.reason)
            return rule_result

        # 第二级：LLM 深度检测
        llm_result = self.llm_engine.deep_check(text, risk_flags) if self.llm_engine else CriticResult(action="PASS")
        if llm_result.action != "PASS":
            logger.info("CriticAgent LLM 检测拦截: %s", llm_result.reason)
            return llm_result

        return CriticResult(action="PASS")


__all__ = ["CriticAgent", "CriticResult"]