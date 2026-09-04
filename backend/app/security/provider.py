"""SecurityProvider — 统一安全接口

整合 CriticAgent、DLP、ToolFilter 三个安全模块，
作为 Deps 依赖注入的安全组件。
"""
import logging
from typing import Optional

from .critic import CriticAgent, CriticResult
from .critic_llm import CriticLLMEngine
from .critic_rules import CriticEngine as CriticRuleEngine, CRITIC_RULES
from .dlp import DLPEngine
from .tool_filter import ToolFilter, ValidationResult

logger = logging.getLogger(__name__)


class SecurityProvider:
    """统一安全接口

    组合三个安全模块，对外暴露统一接口。
    """

    def __init__(self, critic: Optional[CriticAgent] = None,
                 dlp: Optional[DLPEngine] = None,
                 tool_filter: Optional[ToolFilter] = None,
                 enabled: bool = True):
        self.enabled = enabled
        self.critic = critic or CriticAgent(
            rule_engine=CriticRuleEngine(rules=CRITIC_RULES),
        )
        self.dlp = dlp or DLPEngine()
        self.tool_filter = tool_filter or ToolFilter()
        self._critic_llm: Optional[CriticLLMEngine] = None

    def configure_critic_llm(self, llm_provider, enabled: bool = False) -> None:
        """配置 LLM 深度检测（运行期注入）"""
        self._critic_llm = CriticLLMEngine(llm_provider=llm_provider, enabled=enabled)
        self.critic.llm_engine = self._critic_llm

    def check_injection(self, text: str, risk_flags: Optional[dict] = None) -> CriticResult:
        """注入检测（CriticAgent 入口）"""
        if not self.enabled:
            return CriticResult(action="PASS")
        return self.critic.check(text, risk_flags)

    def sanitize(self, text: str) -> str:
        """数据脱敏（DLP 入口）"""
        if not self.enabled or not text:
            return text
        return self.dlp.sanitize(text)

    def validate_tool_call(self, tool_name: str, params: dict) -> ValidationResult:
        """工具调用参数校验（ToolFilter 入口）"""
        if not self.enabled:
            return ValidationResult(valid=True)
        return self.tool_filter.validate(tool_name, params)


__all__ = ["SecurityProvider"]