"""文件魔数（Magic Number）校验 — 防 Content-Type 伪造上传

仅校验 HTTP 头 Content-Type 无法防御「.exe 伪装成 image/jpeg」类攻击，
本模块通过读取文件头部字节判定真实类型，与声明的 MIME 交叉验证。
纯 Python 实现，无外部依赖（Windows 环境避免 python-magic 的 libmagic 依赖）。

用法::

    ok, reason = verify_upload_mime(declared_mime, content)
    if not ok:
        raise HTTPException(400, reason)
"""
from typing import Optional, Tuple

# ── 允许上传的类型：魔数签名 ──
# 格式: {mime: (bytes 前缀, 名称)}
MAGIC_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff", "JPEG"),
    "image/png": (b"\x89PNG\r\n\x1a\n", "PNG"),
    "image/webp": (b"RIFF", "WEBP"),  # 需二次校验 'WEBP' 四字节
    "application/pdf": (b"%PDF-", "PDF"),
}


def _detect_mime(content: bytes) -> Optional[str]:
    """根据魔数识别文件真实 MIME 类型；无法识别返回 None。"""
    if not content:
        return None
    for mime, (magic, _name) in MAGIC_SIGNATURES.items():
        if content.startswith(magic):
            # WEBP 特例：RIFF....WEBP（第 8-11 字节为 'WEBP'）
            if mime == "image/webp":
                if len(content) >= 12 and content[8:12] == b"WEBP":
                    return mime
                continue
            return mime
    return None


def verify_upload_mime(declared_mime: Optional[str], content: bytes) -> Tuple[bool, str]:
    """校验上传文件真实性。

    - 声明 MIME 不在允许列表 → 拒绝（保持原有 400 语义）
    - 魔数无法识别 → 拒绝（疑似伪造/未知类型）
    - 魔数可识别但与声明不兼容 → 拒绝（防伪装上传）
    - 魔数可识别且兼容 → 通过

    兼容规则：声明的 jpeg/jpg 与 image/jpeg 等价；其余按精确匹配。
    """
    if not declared_mime or declared_mime not in set(MAGIC_SIGNATURES) | {"image/jpg"}:
        return False, f"不支持的文件类型: {declared_mime}，仅支持图片和 PDF"

    detected = _detect_mime(content)
    if detected is None:
        return False, "文件内容与声明的类型不符（魔数校验失败），疑似伪装文件"

    declared_norm = "image/jpeg" if declared_mime == "image/jpg" else declared_mime
    if detected != declared_norm:
        return False, (
            f"文件内容为 {detected}，与声明的 {declared_mime} 不一致，拒绝上传"
        )
    return True, ""
