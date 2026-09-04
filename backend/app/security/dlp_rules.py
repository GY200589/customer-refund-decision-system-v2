"""安全模块 — DLP 数据脱敏规则集

正则规则定义，覆盖身份证、手机号、银行卡、邮箱、IP、支付凭证等敏感信息。
每条规则包含：名称、模式、脱敏方式、脱敏函数。
"""
import re
from dataclasses import dataclass, field
from typing import Callable, Pattern


@dataclass
class DLPIDRule:
    """单条脱敏规则"""
    name: str
    pattern: Pattern
    mask_func: Callable[[str], str]
    description: str = ""
    enabled: bool = True


def _mask_id_card(match: re.Match) -> str:
    """身份证号：保留前6后4"""
    s = match.group(0)
    if len(s) >= 14:
        return s[:6] + "****" + s[-4:]
    return s


def _mask_phone(match: re.Match) -> str:
    """手机号：保留前3后4"""
    s = match.group(0)
    if len(s) == 11:
        return s[:3] + "****" + s[-4:]
    return s


def _mask_bank_card(match: re.Match) -> str:
    """银行卡号：保留前4后4"""
    s = match.group(0)
    if len(s) >= 12:
        return s[:4] + "********" + s[-4:]
    return s


def _mask_email(match: re.Match) -> str:
    """邮箱：保留域名，用户名部分脱敏"""
    s = match.group(0)
    parts = s.split("@")
    if len(parts) == 2:
        return "***@" + parts[1]
    return s


def _mask_ip(match: re.Match) -> str:
    """IP 地址：保留前两段"""
    s = match.group(0)
    parts = s.split(".")
    if len(parts) == 4:
        return parts[0] + "." + parts[1] + ".*.*"
    return s


def _mask_payment(match: re.Match) -> str:
    """支付凭证：完全脱敏"""
    return "pay_********"


def _mask_generic(match: re.Match) -> str:
    """通用脱敏（保留前3后4，不足则全脱敏）"""
    s = match.group(0)
    if len(s) >= 10:
        return s[:3] + "****" + s[-4:]
    return "****"


# ── 预编译规则集 ──

DEFAULT_RULES: list[DLPIDRule] = [
    DLPIDRule(
        name="id_card",
        pattern=re.compile(r"\b\d{17}[\dXx]\b"),
        mask_func=_mask_id_card,
        description="身份证号（18位）",
    ),
    DLPIDRule(
        name="phone",
        pattern=re.compile(r"\b1[3-9]\d{9}\b"),
        mask_func=_mask_phone,
        description="手机号",
    ),
    DLPIDRule(
        name="bank_card",
        pattern=re.compile(r"\b\d{16,19}\b"),
        mask_func=_mask_bank_card,
        description="银行卡号",
    ),
    DLPIDRule(
        name="email",
        pattern=re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
        mask_func=_mask_email,
        description="邮箱地址",
    ),
    DLPIDRule(
        name="ip_address",
        pattern=re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
        mask_func=_mask_ip,
        description="IP 地址",
    ),
    DLPIDRule(
        name="payment_voucher",
        pattern=re.compile(r"pay_\w{16,}"),
        mask_func=_mask_payment,
        description="支付凭证",
    ),
    DLPIDRule(
        name="generic_long_number",
        pattern=re.compile(r"\b\d{12,}\b"),
        mask_func=_mask_generic,
        description="长数字串（兜底）",
    ),
]

__all__ = ["DLPIDRule", "DEFAULT_RULES"]