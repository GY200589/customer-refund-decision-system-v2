"""CriticAgent — 规则快速路注入检测

预编译正则规则集，O(1) 匹配，覆盖常见注入模式：
- SQL 注入、XSS、Prompt 注入、路径遍历、命令注入、模板注入
"""
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CriticRule:
    """单条检测规则"""
    name: str
    pattern: re.Pattern
    weight: str  # HIGH / MEDIUM / LOW
    category: str  # sql_injection / xss / prompt_injection / path_traversal / cmd_injection / template_injection
    description: str = ""
    enabled: bool = True


# ── 预编译规则集 ──

CRITIC_RULES: list[CriticRule] = [
    # SQL 注入
    CriticRule(
        name="sql_select_from",
        pattern=re.compile(r"SELECT\s+.*\s+FROM", re.IGNORECASE),
        weight="HIGH", category="sql_injection",
        description="SQL SELECT 查询",
    ),
    CriticRule(
        name="sql_drop_table",
        pattern=re.compile(r"DROP\s+TABLE", re.IGNORECASE),
        weight="HIGH", category="sql_injection",
        description="SQL DROP TABLE",
    ),
    CriticRule(
        name="sql_union_select",
        pattern=re.compile(r"UNION\s+.*\s+SELECT", re.IGNORECASE),
        weight="HIGH", category="sql_injection",
        description="SQL UNION SELECT",
    ),
    CriticRule(
        name="sql_or_1_1",
        pattern=re.compile(r"'\s*OR\s+1\s*=\s*1", re.IGNORECASE),
        weight="HIGH", category="sql_injection",
        description="SQL OR 1=1 注入",
    ),
    CriticRule(
        name="sql_delete",
        pattern=re.compile(r"DELETE\s+FROM", re.IGNORECASE),
        weight="HIGH", category="sql_injection",
        description="SQL DELETE",
    ),
    CriticRule(
        name="sql_insert",
        pattern=re.compile(r"INSERT\s+INTO", re.IGNORECASE),
        weight="HIGH", category="sql_injection",
        description="SQL INSERT",
    ),
    CriticRule(
        name="sql_alter",
        pattern=re.compile(r"ALTER\s+TABLE", re.IGNORECASE),
        weight="HIGH", category="sql_injection",
        description="SQL ALTER TABLE",
    ),
    # XSS
    CriticRule(
        name="xss_script_tag",
        pattern=re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
        weight="HIGH", category="xss",
        description="XSS script 标签",
    ),
    CriticRule(
        name="xss_javascript",
        pattern=re.compile(r"javascript\s*:", re.IGNORECASE),
        weight="HIGH", category="xss",
        description="XSS javascript: 伪协议",
    ),
    CriticRule(
        name="xss_onload",
        pattern=re.compile(r"\bon\w+\s*=", re.IGNORECASE),
        weight="MEDIUM", category="xss",
        description="XSS 事件处理器",
    ),
    CriticRule(
        name="xss_iframe",
        pattern=re.compile(r"<iframe[^>]*>", re.IGNORECASE),
        weight="HIGH", category="xss",
        description="XSS iframe 标签",
    ),
    # Prompt 注入
    CriticRule(
        name="prompt_ignore_previous",
        pattern=re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|prompts|commands)", re.IGNORECASE),
        weight="HIGH", category="prompt_injection",
        description="Prompt 注入：忽略先前指令",
    ),
    CriticRule(
        name="prompt_system_prompt",
        pattern=re.compile(r"(system|new)\s+prompt\s*:", re.IGNORECASE),
        weight="HIGH", category="prompt_injection",
        description="Prompt 注入：覆盖系统提示",
    ),
    CriticRule(
        name="prompt_forget_all",
        pattern=re.compile(r"(forget|ignore|override)\s+(all|everything|your)", re.IGNORECASE),
        weight="HIGH", category="prompt_injection",
        description="Prompt 注入：遗忘/覆盖",
    ),
    CriticRule(
        name="prompt_you_are",
        pattern=re.compile(r"你是一个|你是\s*一个|扮演", re.IGNORECASE),
        weight="MEDIUM", category="prompt_injection",
        description="Prompt 注入：角色扮演（中文）",
    ),
    # 路径遍历
    CriticRule(
        name="path_traversal_unix",
        pattern=re.compile(r"\.\./|\.\.\\"),
        weight="MEDIUM", category="path_traversal",
        description="路径遍历 ../",
    ),
    CriticRule(
        name="path_traversal_etc",
        pattern=re.compile(r"/etc/passwd|/etc/shadow|/etc/hosts", re.IGNORECASE),
        weight="MEDIUM", category="path_traversal",
        description="路径遍历 /etc/ 敏感文件",
    ),
    CriticRule(
        name="path_traversal_windows",
        pattern=re.compile(r"C:\\[A-Za-z]|C:/[A-Za-z]", re.IGNORECASE),
        weight="MEDIUM", category="path_traversal",
        description="路径遍历 Windows 盘符",
    ),
    # 命令注入
    CriticRule(
        name="cmd_rm_rf",
        pattern=re.compile(r";\s*rm\s+(-rf?|--recursive)", re.IGNORECASE),
        weight="HIGH", category="cmd_injection",
        description="命令注入：rm -rf",
    ),
    CriticRule(
        name="cmd_backtick",
        pattern=re.compile(r"`[^`]+`"),
        weight="HIGH", category="cmd_injection",
        description="命令注入：反引号执行",
    ),
    CriticRule(
        name="cmd_subshell",
        pattern=re.compile(r"\$\([^)]+\)"),
        weight="HIGH", category="cmd_injection",
        description="命令注入：$() 子 shell",
    ),
    CriticRule(
        name="cmd_powershell",
        pattern=re.compile(r"powershell\s+", re.IGNORECASE),
        weight="MEDIUM", category="cmd_injection",
        description="命令注入：PowerShell",
    ),
    CriticRule(
        name="cmd_wget_curl",
        pattern=re.compile(r"\b(wget|curl)\s+", re.IGNORECASE),
        weight="MEDIUM", category="cmd_injection",
        description="命令注入：wget/curl",
    ),
    # 模板注入
    CriticRule(
        name="tpl_jinja2",
        pattern=re.compile(r"\{\{.*?\}\}|\{%\s+.*?\s*%\}|{#.*?#}"),
        weight="MEDIUM", category="template_injection",
        description="模板注入：Jinja2 语法",
    ),
    CriticRule(
        name="tpl_dollar_brace",
        pattern=re.compile(r"\$\{.*?\}"),
        weight="MEDIUM", category="template_injection",
        description="模板注入：${} 语法",
    ),
]


@dataclass
class CriticResult:
    """Critic 检测结果"""
    action: str  # PASS / REJECT / REVIEW
    reason: str = ""
    matched_rules: list[dict] = field(default_factory=list)


class CriticEngine:
    """CriticAgent 规则引擎 — 注入检测快速路

    使用预编译正则规则集，对输入文本进行多维度注入检测。
    支持按权重分级决策：HIGH → REJECT，MEDIUM → REVIEW。
    """

    def __init__(self, rules: Optional[list[CriticRule]] = None,
                 reject_on_high: bool = True,
                 review_on_medium: bool = True):
        self.rules = rules or CRITIC_RULES
        self.reject_on_high = reject_on_high
        self.review_on_medium = review_on_medium

    def check(self, text: str, risk_flags: Optional[dict] = None) -> CriticResult:
        """对输入文本进行注入检测

        返回检测结果，包含动作（PASS/REJECT/REVIEW）和匹配的规则详情。
        """
        if not text:
            return CriticResult(action="PASS")

        matched = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            try:
                if rule.pattern.search(text):
                    matched.append({
                        "name": rule.name,
                        "weight": rule.weight,
                        "category": rule.category,
                        "description": rule.description,
                    })
            except Exception:
                continue

        if not matched:
            return CriticResult(action="PASS")

        # 按权重最高级别决策
        has_high = any(r["weight"] == "HIGH" for r in matched)
        has_medium = any(r["weight"] == "MEDIUM" for r in matched)

        if has_high and self.reject_on_high:
            names = [r["name"] for r in matched if r["weight"] == "HIGH"]
            return CriticResult(
                action="REJECT",
                reason=f"检测到高风险注入: {', '.join(names)}",
                matched_rules=matched,
            )

        if has_medium and self.review_on_medium:
            names = [r["name"] for r in matched if r["weight"] == "MEDIUM"]
            return CriticResult(
                action="REVIEW",
                reason=f"检测到中风险注入: {', '.join(names)}",
                matched_rules=matched,
            )

        # LOW 权重或无决策配置，放行
        return CriticResult(action="PASS", matched_rules=matched)


__all__ = ["CriticEngine", "CriticRule", "CriticResult", "CRITIC_RULES"]