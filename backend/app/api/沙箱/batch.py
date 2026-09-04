"""批量审批路由。"""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.batch.exporter import export_suspended_cases
from app.batch.executor import execute_batch_approval
from app.batch.models import BatchApprovalResult
from app.batch.parser import parse_approval_excel
from app.config import settings
from app.deps import require_role
from app.models import User

router = APIRouter(tags=["batch"])


@router.get("/export")
async def export_suspended(
    request: Request,
    user: User = Depends(require_role("supervisor", "admin")),
):
    """导出挂起订单为 Excel 文件

    查库获取所有 SUSPENDED 状态的工单，生成为 Excel 供主管下载。
    无挂起单时返回空表头 Excel。
    """
    from starlette.responses import StreamingResponse

    with request.app.state.deps.session() as session:
        content, count = export_suspended_cases(session)

    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=suspended_cases.xlsx",
            "X-Total-Count": str(count),
        },
    )


@router.post("/upload", response_model=BatchApprovalResult)
async def upload_approval(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_role("supervisor", "admin")),
):
    """上传审批结果并批量执行

    接受主管填写的 Excel 文件，解析审批记录，逐条唤醒挂起工作流。
    支持 SANDBOX_MODE=on/off 双模式。
    """
    # 校验文件类型
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 文件")

    # 读取文件内容
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB 限制
        raise HTTPException(status_code=400, detail="文件过大，最大 10MB")

    # 沙箱解析
    try:
        rows = parse_approval_excel(content, settings.sandbox_mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not rows:
        raise HTTPException(status_code=400, detail="未找到有效审批记录（需要至少一行「同意/拒绝」）")

    # 批量执行
    result = execute_batch_approval(
        rows=rows,
        deps=request.app.state.deps,
        graph=request.app.state.graph,
        operator=user.username,
        operator_id=user.id,
    )
    return result
