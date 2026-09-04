"""安全配置项

从 config 读取安全配置，提供类型安全的访问接口。
"""
from ..config import settings


class SecurityConfig:
    """安全配置管理器"""

    @property
    def critic_rule_enabled(self) -> bool:
        return getattr(settings, "critic_rule_enabled", True)

    @property
    def critic_llm_enabled(self) -> bool:
        return getattr(settings, "critic_llm_enabled", False)

    @property
    def critic_reject_on_high(self) -> bool:
        return getattr(settings, "critic_reject_on_high", True)

    @property
    def critic_review_on_medium(self) -> bool:
        return getattr(settings, "critic_review_on_medium", True)

    @property
    def dlp_enabled(self) -> bool:
        return getattr(settings, "dlp_enabled", True)

    @property
    def dlp_sanitize_input(self) -> bool:
        return getattr(settings, "dlp_sanitize_input", True)

    @property
    def dlp_sanitize_output(self) -> bool:
        return getattr(settings, "dlp_sanitize_output", True)

    @property
    def dlp_mask_char(self) -> str:
        return getattr(settings, "dlp_mask_char", "*")

    @property
    def tool_filter_enabled(self) -> bool:
        return getattr(settings, "tool_filter_enabled", True)

    @property
    def tool_filter_amount_max(self) -> int:
        return getattr(settings, "tool_filter_amount_max", 10_000_000)

    @property
    def all_enabled(self) -> bool:
        """安全总开关"""
        return self.critic_rule_enabled or self.critic_llm_enabled or self.dlp_enabled or self.tool_filter_enabled


security_config = SecurityConfig()

__all__ = ["SecurityConfig", "security_config"]