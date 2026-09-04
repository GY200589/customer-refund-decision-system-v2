"""路径净化与边界检查

功能：
- 路径规范化（resolve）
- 拒绝 ../ 穿越
- 拒绝绝对路径逃逸
- 拒绝符号链接逃逸
- 限制写回路径必须在 data/output 前缀内
"""

import os
import logging
from pathlib import Path
from typing import Optional

from .exceptions import PathEscapeError

logger = logging.getLogger(__name__)

# 宿主允许的 data 目录前缀
ALLOWED_DATA_PREFIXES = [
    os.path.abspath("data"),
    os.path.abspath("data/input"),
    os.path.abspath("data/output"),
]


def sanitize_path(
    user_path: str,
    allowed_base: Optional[str] = None,
    allow_absolute: bool = False,
    check_symlink: bool = True,
) -> str:
    """对用户传入的路径做安全检查和规范化。

    Args:
        user_path: 用户传入的原始路径。
        allowed_base: 允许的基准目录，解析后的路径必须在此目录下。
        allow_absolute: 是否允许绝对路径（默认 False，禁止）。
        check_symlink: 是否检查符号链接逃逸（默认 True）。

    Returns:
        规范化后的安全路径字符串。

    Raises:
        PathEscapeError: 路径穿越、逃逸或非法。
    """
    if not user_path or not isinstance(user_path, str):
        raise PathEscapeError(f"路径为空或类型错误: {user_path!r}")

    # 去除空白和尾部分隔符
    user_path = user_path.strip().rstrip("/\\")

    if not user_path:
        raise PathEscapeError("路径为空字符串")

    # 检查是否包含空字节
    if "\0" in user_path:
        raise PathEscapeError("路径包含空字节")

    # 检查是否包含 shell 控制字符
    forbidden_chars = set("|;&$`'\"()")
    if forbidden_chars.intersection(user_path):
        raise PathEscapeError("路径包含非法字符")

    # 绝对路径检查
    if not allow_absolute and os.path.isabs(user_path):
        raise PathEscapeError(f"禁止使用绝对路径: {user_path!r}")

    # 规范化路径
    # 对于相对路径，先拼接到 allowed_base 再 resolve
    if allowed_base:
        base = os.path.abspath(allowed_base)
        combined = os.path.join(base, user_path)
    else:
        base = os.path.abspath(".")
        combined = os.path.join(base, user_path)

    resolved = os.path.realpath(combined)

    # 检查解析后的路径是否在 allowed_base 内
    if allowed_base:
        base_real = os.path.realpath(os.path.abspath(allowed_base))
        if not resolved.startswith(base_real + os.sep) and resolved != base_real:
            raise PathEscapeError(
                f"路径逃逸: {user_path!r} -> {resolved!r} 不在允许的基准目录 {base_real!r} 内"
            )

    # 如果 allowed_base 未指定，检查是否在允许的 data 前缀内
    else:
        allowed = [os.path.realpath(p) for p in ALLOWED_DATA_PREFIXES]
        if not any(resolved.startswith(p + os.sep) or resolved == p for p in allowed):
            raise PathEscapeError(
                f"路径逃逸: {resolved!r} 不在允许的 data 目录前缀内: {allowed}"
            )

    # 符号链接逃逸检查
    if check_symlink and allowed_base:
        # 检查每一级父目录是否都是符号链接指向 allowed_base 内
        _check_symlink_chain(user_path, allowed_base, resolved)

    return resolved


def _check_symlink_chain(user_path: str, allowed_base: str, resolved: str) -> None:
    """检查符号链接链是否逃逸出 allowed_base。

    遍历从 allowed_base 到 resolved 的中间路径，检查是否有符号链接
    指向了 allowed_base 外部。
    """
    base_real = os.path.realpath(allowed_base)
    # 计算 resolved 相对于 base_real 的相对路径
    try:
        rel = os.path.relpath(resolved, base_real)
    except ValueError:
        raise PathEscapeError(f"无法计算相对路径: {resolved}")

    parts = rel.split(os.sep)
    current = base_real
    for part in parts:
        if part == "..":
            raise PathEscapeError(f"符号链接链包含 '..' 逃逸: {user_path!r}")
        current = os.path.join(current, part)
        if os.path.islink(current):
            link_target = os.readlink(current)
            if not os.path.isabs(link_target):
                link_target = os.path.join(os.path.dirname(current), link_target)
            link_target = os.path.realpath(link_target)
            if not link_target.startswith(base_real + os.sep) and link_target != base_real:
                raise PathEscapeError(
                    f"符号链接逃逸: {current} -> {link_target} 不在基准目录内"
                )


def validate_output_path(file_path: str, output_base: str = "data/output") -> str:
    """验证写回路径必须在 data/output 目录内。

    Args:
        file_path: 写回文件路径。
        output_base: 输出基准目录。

    Returns:
        规范化后的安全输出路径。
    """
    safe = sanitize_path(file_path, allowed_base=output_base, allow_absolute=False)
    return safe


def validate_input_path(file_path: str, input_base: str = "data/input") -> str:
    """验证输入路径必须在 data/input 目录内。

    Args:
        file_path: 输入文件路径。
        input_base: 输入基准目录。

    Returns:
        规范化后的安全输入路径。
    """
    safe = sanitize_path(file_path, allowed_base=input_base, allow_absolute=False)
    return safe