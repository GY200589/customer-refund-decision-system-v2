"""沙箱解析审批后的 Excel

SANDBOX_MODE=on  → Docker 沙箱隔离解析（真隔离）
SANDBOX_MODE=off → 宿主机直接解析（漏洞基线，仅路径校验兜底）
"""
import io
import json
import logging
import os
import tempfile
import uuid
from typing import List

from app.batch.models import ApprovalRow

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"同意", "拒绝"}


def parse_approval_excel(file_content: bytes, sandbox_mode: str = "off") -> List[ApprovalRow]:
    """解析审批后的 Excel 文件

    Args:
        file_content: Excel 文件二进制内容
        sandbox_mode: "on"=Docker 沙箱, "off"=宿主机直读

    Returns:
        List[ApprovalRow]: 解析结果

    Raises:
        ValueError: 文件格式错误或内容无效
    """
    if sandbox_mode == "on":
        return _parse_in_sandbox(file_content)
    return _parse_direct(file_content)


def _parse_direct(file_content: bytes) -> List[ApprovalRow]:
    """宿主机直接解析（路径校验兜底）"""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
    except Exception as e:
        raise ValueError(f"无法解析 Excel 文件: {e}")

    ws = wb.active
    if ws is None:
        raise ValueError("Excel 文件无活动工作表")

    rows: List[ApprovalRow] = []
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        if not row or not row[0]:  # 跳过空行
            continue

        case_id = str(row[0]).strip()
        action_raw = str(row[5]).strip() if len(row) > 5 and row[5] else ""
        comment = str(row[6]).strip() if len(row) > 6 and row[6] else ""

        if not action_raw:
            logger.warning("第 %d 行：审批动作为空，跳过", row_idx)
            continue

        if action_raw not in VALID_ACTIONS:
            logger.warning("第 %d 行：无效审批动作 '%s'，跳过", row_idx, action_raw)
            continue

        rows.append(ApprovalRow(case_id=case_id, action=action_raw, comment=comment))

    wb.close()
    logger.info("解析完成：共 %d 条有效记录", len(rows))
    return rows


def _parse_in_sandbox(file_content: bytes) -> List[ApprovalRow]:
    """Docker 沙箱隔离解析 Excel

    将文件写入临时目录，挂载到 ContainerOfficeCLI 沙箱内解析，
    解析完成后立即清理临时文件。
    """
    from app.sandbox.container_office_cli import ContainerOfficeCLI

    sandbox_dir = os.environ.get("SANDBOX_DIR", os.path.join(tempfile.gettempdir(), "sandbox_work"))
    os.makedirs(sandbox_dir, exist_ok=True)

    filename = f"approval_{uuid.uuid4().hex}.xlsx"
    filepath = os.path.join(sandbox_dir, filename)

    try:
        # 写入临时文件
        with open(filepath, "wb") as f:
            f.write(file_content)

        # 沙箱解析
        cli = ContainerOfficeCLI(sandbox_dir)
        result = cli.read_excel(filename)

        # 解析返回数据
        data = result
        if isinstance(result, str):
            data = json.loads(result)

        rows: List[ApprovalRow] = []
        for item in data:
            if not item.get("case_id"):
                continue

            case_id = str(item["case_id"]).strip()
            action_raw = str(item.get("审批动作", "") or "").strip()
            comment = str(item.get("审批意见", "") or "").strip()

            if not action_raw:
                continue
            if action_raw not in VALID_ACTIONS:
                logger.warning("沙箱解析：无效动作 '%s'，跳过", action_raw)
                continue

            rows.append(ApprovalRow(case_id=case_id, action=action_raw, comment=comment))

        logger.info("沙箱解析完成：共 %d 条有效记录", len(rows))
        return rows

    except Exception as e:
        raise ValueError(f"沙箱解析失败: {e}")
    finally:
        # 清理临时文件
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.debug("已清理临时文件: %s", filepath)