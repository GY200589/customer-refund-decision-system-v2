"""上传凭证共享工具：客服后台与用户端退款共用同一套安全校验（定稿 §6）。

校验链与原 cases.py 一致：HTTP 头声明 + 文件魔数双重校验、大小上限、
按用户分目录存储，防止跨用户文件混乱与伪装上传。
"""
import hashlib
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from ..security.mime import verify_upload_mime

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "./uploads"))
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "10")) * 1024 * 1024
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/jpg", "application/pdf", "image/webp"}


def save_upload(file: UploadFile, user_id: int) -> dict:
    """校验并保存上传文件，返回 EvidenceIn 兼容的字段字典。"""
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"不支持的文件类型: {file.content_type}，仅支持图片和 PDF")

    content = file.file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"文件过大，最大 {MAX_UPLOAD_SIZE // 1024 // 1024}MB")

    # 魔数校验：拒绝 .exe 伪装成图片/PDF 的伪造上传
    mime_ok, mime_reason = verify_upload_mime(file.content_type, content)
    if not mime_ok:
        raise HTTPException(400, mime_reason)

    upload_dir = UPLOAD_DIR / str(user_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_ext = Path(file.filename or "upload").suffix or ".bin"
    unique_name = f"{uuid.uuid4().hex}{file_ext}"
    file_path = upload_dir / unique_name
    file_path.write_bytes(content)

    return {
        "file_name": file.filename or unique_name,
        # 内容指纹用于识别同一凭证在同账号或跨账号重复提交，不记录图片内容到日志。
        "file_hash": hashlib.sha256(content).hexdigest(),
        "file_path": str(file_path.absolute()),
        "mime_type": file.content_type or "application/octet-stream",
        "file_size": len(content),
    }


def validate_uploaded_evidence(evidence: list[dict], user_id: int) -> list[dict]:
    """校验凭证路径归属并由服务端重算指纹，拒绝客户端伪造 hash 或跨账号引用。"""
    user_dir = (UPLOAD_DIR / str(user_id)).resolve()
    validated = []
    for item in evidence:
        raw_path = item.get("file_path")
        if not raw_path:
            raise HTTPException(422, "凭证缺少有效文件路径，请重新上传")
        path = Path(raw_path).resolve()
        try:
            path.relative_to(user_dir)
        except ValueError:
            raise HTTPException(422, "凭证不属于当前账号，请重新上传")
        if not path.is_file():
            raise HTTPException(422, "凭证文件不存在，请重新上传")
        validated.append(
            {
                "file_name": item.get("file_name") or path.name,
                "file_path": str(path),
                "file_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return validated
