"""Tool-calling 过滤 — 参数校验器

在退款执行前校验参数合法性，白名单 + Schema 校验。
"""
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ValidationResult:
    """校验结果"""
    valid: bool
    reason: str = ""


@dataclass
class ToolSchema:
    """工具调用参数 Schema"""
    name: str
    params: dict[str, dict]  # 参数名 -> 校验规则
    description: str = ""


# UUID v4 正则
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


# ── 工具 Schema 定义 ──

TOOL_SCHEMAS: dict[str, ToolSchema] = {
    "execute_refund": ToolSchema(
        name="execute_refund",
        params={
            "case_id": {"type": "uuid", "required": True, "description": "案件 ID"},
            "amount_cent": {
                "type": "int",
                "required": True,
                "min": 1,
                "max": 10_000_000,
                "description": "退款金额（分），上限 10 万元",
            },
            "reason": {"type": "string", "required": False, "max_length": 500},
        },
        description="执行退款",
    ),
    "cancel_refund": ToolSchema(
        name="cancel_refund",
        params={
            "case_id": {"type": "uuid", "required": True, "description": "案件 ID"},
            "reason": {"type": "string", "required": False, "max_length": 500},
        },
        description="取消退款",
    ),
}


class ToolFilter:
    """Tool-calling 参数校验器

    白名单机制：仅允许已注册的工具调用。
    参数校验：类型、范围、格式、必填项。
    """

    def __init__(self, schemas: Optional[dict[str, ToolSchema]] = None,
                 enabled: bool = True,
                 amount_max: int = 10_000_000):
        self.schemas = schemas or TOOL_SCHEMAS
        self.enabled = enabled
        self.amount_max = amount_max

    def validate(self, tool_name: str, params: dict[str, Any]) -> ValidationResult:
        """校验工具调用参数

        Args:
            tool_name: 工具名称
            params: 参数字典

        Returns:
            ValidationResult: 校验结果
        """
        if not self.enabled:
            return ValidationResult(valid=True)

        # 白名单检查
        if tool_name not in self.schemas:
            return ValidationResult(
                valid=False,
                reason=f"工具 '{tool_name}' 不在白名单中，已拒绝",
            )

        schema = self.schemas[tool_name]

        # 逐参数校验
        for param_name, rules in schema.params.items():
            value = params.get(param_name)
            required = rules.get("required", False)

            # 必填检查
            if required and value is None:
                return ValidationResult(
                    valid=False,
                    reason=f"参数 '{param_name}' 为必填项",
                )

            if value is None:
                continue

            # 类型检查
            param_type = rules.get("type", "string")
            if param_type == "int":
                if not isinstance(value, int):
                    return ValidationResult(
                        valid=False,
                        reason=f"参数 '{param_name}' 应为整数，实际为 {type(value).__name__}",
                    )
                min_val = rules.get("min")
                max_val = rules.get("max", self.amount_max) if param_name == "amount_cent" else rules.get("max")
                if min_val is not None and value < min_val:
                    return ValidationResult(
                        valid=False,
                        reason=f"参数 '{param_name}' 最小值 {min_val}，实际 {value}",
                    )
                if max_val is not None and value > max_val:
                    return ValidationResult(
                        valid=False,
                        reason=f"参数 '{param_name}' 最大值 {max_val}，实际 {value}",
                    )

            elif param_type == "string":
                if not isinstance(value, str):
                    return ValidationResult(
                        valid=False,
                        reason=f"参数 '{param_name}' 应为字符串，实际为 {type(value).__name__}",
                    )
                max_length = rules.get("max_length")
                if max_length is not None and len(value) > max_length:
                    return ValidationResult(
                        valid=False,
                        reason=f"参数 '{param_name}' 长度超过上限 {max_length}",
                    )

            elif param_type == "uuid":
                if not isinstance(value, str):
                    return ValidationResult(
                        valid=False,
                        reason=f"参数 '{param_name}' 应为 UUID 字符串",
                    )
                if not UUID_PATTERN.match(value):
                    return ValidationResult(
                        valid=False,
                        reason=f"参数 '{param_name}' 格式非法（非 UUID v4）",
                    )

        return ValidationResult(valid=True)


__all__ = ["ToolFilter", "ValidationResult", "ToolSchema", "TOOL_SCHEMAS"]