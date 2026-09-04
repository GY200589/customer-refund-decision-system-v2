"""安全模块 — 零信任安全防护与 AI 治理

提供 CriticAgent（注入拦截）、DLP（数据脱敏）、Tool-calling 过滤三项能力。
同时保留原有 JWT/auth 安全函数。
"""
import sys
sys.path.insert(0, __file__)

from .critic import CriticAgent, CriticResult
from .critic_rules import CriticEngine, CriticRule, CriticResult, CRITIC_RULES
from .critic_llm import CriticLLMEngine
from .dlp import DLPEngine
from .dlp_rules import DLPIDRule, DEFAULT_RULES
from .tool_filter import ToolFilter, ValidationResult, ToolSchema, TOOL_SCHEMAS
from .provider import SecurityProvider
from .config import SecurityConfig, security_config

# 重新导出原 app/auth.py 中的函数，保持兼容
from app.auth import decode_token, create_access_token, hash_password, verify_password

__all__ = [
    # CriticAgent
    "CriticAgent", "CriticEngine", "CriticRule", "CriticResult", "CRITIC_RULES",
    # Critic LLM
    "CriticLLMEngine",
    # DLP
    "DLPEngine", "DLPIDRule", "DEFAULT_RULES",
    # ToolFilter
    "ToolFilter", "ValidationResult", "ToolSchema", "TOOL_SCHEMAS",
    # Provider
    "SecurityProvider",
    # Config
    "SecurityConfig", "security_config",
    # Auth (from original app/security.py)
    "decode_token", "create_access_token", "hash_password", "verify_password",
]