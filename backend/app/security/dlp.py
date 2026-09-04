"""DLP 数据脱敏引擎

对文本中的敏感信息进行脱敏处理，支持入站和出站两种场景。
脱敏结果记录审计日志。
"""
import logging
from typing import Optional

from .dlp_rules import DLPIDRule, DEFAULT_RULES

logger = logging.getLogger(__name__)


class DLPEngine:
    """DLP 数据脱敏引擎"""

    def __init__(self, rules: Optional[list[DLPIDRule]] = None, mask_char: str = "*"):
        self.rules = rules or DEFAULT_RULES
        self.mask_char = mask_char

    def sanitize(self, text: str) -> str:
        """对文本进行脱敏处理，返回脱敏后的文本

        按顺序应用所有启用的规则，每条规则独立匹配和脱敏。
        """
        if not text:
            return text

        result = text
        for rule in self.rules:
            if not rule.enabled:
                continue
            try:
                result = rule.pattern.sub(rule.mask_func, result)
            except Exception as exc:
                logger.warning("DLP 规则 %s 执行异常: %s", rule.name, exc)
        return result

    def sanitize_batch(self, texts: dict[str, str]) -> dict[str, str]:
        """批量脱敏，输入为字段名->文本的映射

        返回同结构的脱敏后映射。
        """
        return {key: self.sanitize(val) for key, val in texts.items()}

    def has_sensitive(self, text: str) -> bool:
        """检查文本中是否包含敏感信息（不脱敏，仅检测）"""
        if not text:
            return False
        for rule in self.rules:
            if not rule.enabled:
                continue
            if rule.pattern.search(text):
                return True
        return False


__all__ = ["DLPEngine"]