import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import require_role
from ...domain.exceptions import ConcurrencyConflict
from ...models import AgentRun, AuditLog, CaseEvidence, IdempotencyRecord, RefundCase, ReviewTask, RiskAssessment, User
from ...schemas import CaseCreateRequest, DecisionRequest, OcrCorrectionRequest, UploadResponse
from ...security.mime import verify_upload_mime
from ...services.case_service import create_case as create_case_service
from ...services.idempotency import approval_key, compute_request_hash
from ...services.locks import acquire_lock, release_lock

router = APIRouter()

# 文件上传配置
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "./uploads"))
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "10")) * 1024 * 1024
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/jpg", "application/pdf", "image/webp"}


def _ensure_upload_dir(user_id: int) -> Path:
    """创建用户上传目录（按 user_id 分目录，避免跨用户文件混乱）。"""
    d = UPLOAD_DIR / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _require_case_access(db: Session, user: User, case_id: str) -> RefundCase:
    """案件访问控制：案件必须存在（404）；客服可见"本人建案 ∪ 用户端案件"（定稿 C3）。"""
    case = db.query(RefundCase).filter(RefundCase.case_id == case_id).first()
    if case is None:
        raise HTTPException(404, "案件不存在")
    if user.role == "agent" and case.user_id != user.id and case.source != "customer_portal":
        raise HTTPException(403, "无权访问该案件")
    return case


def _serialize_case(db: Session, case: RefundCase, request: Request = None) -> dict:
    agent_runs = (
        db.query(AgentRun).filter(AgentRun.case_id == case.case_id).order_by(AgentRun.id).all()
    )
    evidences = db.query(CaseEvidence).filter(CaseEvidence.case_id == case.case_id).all()
    risk = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.case_id == case.case_id)
        .order_by(RiskAssessment.id.desc())
        .first()
    )
    review = (
        db.query(ReviewTask).filter(ReviewTask.case_id == case.case_id).order_by(ReviewTask.id.desc()).first()
    )
    applicant = db.get(User, case.user_id)

    # DLP 出站脱敏
    dlp = getattr(request.app.state.deps, "security", None) if request else None
    complaint_text = case.complaint_text
    ocr_text = None
    if dlp:
        complaint_text = dlp.sanitize(complaint_text) if complaint_text else complaint_text
        if evidences:
            ocr_text = dlp.sanitize(evidences[0].ocr_text) if evidences[0].ocr_text else None

    return {
        "case_id": case.case_id,
        "order_id": case.order_id,
        "source": case.source,
        "source_label": "用户端" if case.source == "customer_portal" else "客服后台",
        "product_name": case.product_name,
        "product_sub_category": case.product_sub_category,
        "amount_cent": case.amount_cent,
        "amount_yuan": f"{case.amount_cent / 100:.2f}",
        "currency": case.currency,
        "status": case.status,
        "version": case.version,
        "decision": case.decision,
        "decision_reason": case.decision_reason,
        "risk_level": case.risk_level,
        "fraud_score": case.fraud_score,
        "sentiment_score": case.sentiment_score,
        "ocr_confidence": case.ocr_confidence,
        "ocr_corrected": case.ocr_corrected or False,
        "risk_flags": case.risk_flags,
        "complaint_text": complaint_text,
        "review_comment": case.review_comment,
        "refund_status": case.refund_status,
        "refund_ref": case.refund_ref,
        "trace_id": case.trace_id,
        "is_verified_order": case.is_verified_order,
        "order_verify_error": case.order_verify_error,
        "verified_order_amount": case.verified_order_amount,
        "product_match": case.product_match,
        "claimed_product": case.claimed_product,
        "purchased_product": case.purchased_product,
        "product_consistency_risk": case.product_consistency_risk,
        "refund_rate": case.refund_rate,
        "applicant": (
            {
                "user_id": applicant.id,
                "username": applicant.username,
                "display_name": applicant.display_name,
                "total_cases": applicant.total_cases,
                "refund_count": applicant.refund_count,
                "refund_rate": applicant.refund_rate,
            }
            if applicant
            else None
        ),
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        "agent_runs": [
            {
                "agent_name": r.agent_name,
                "status": r.status,
                "output_summary": r.output_summary,
                "error": r.error,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in agent_runs
        ],
        "evidences": [
            {
                "file_name": e.file_name,
                "evidence_id": e.id,
                "ocr_text": ocr_text if e == evidences[0] else (
                    dlp.sanitize(e.ocr_text) if (dlp and e.ocr_text) else e.ocr_text
                ),
                "ocr_confidence": e.ocr_confidence,
                "ocr_corrected": e.ocr_corrected_at is not None,
            }
            for e in evidences
        ],
        "risk": (
            {
                "fraud_score": risk.fraud_score,
                "sentiment_score": risk.sentiment_score,
                "risk_level": risk.risk_level,
                "risk_factors": risk.risk_factors,
            }
            if risk
            else None
        ),
        "review_task": (
            {"id": review.id, "assigned_to": review.assigned_to, "status": review.status, "comment": review.comment}
            if review
            else None
        ),
    }


@router.post("/upload", status_code=201)
def upload_file(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("agent", "supervisor", "admin")),
):
    """上传退款凭证文件。支持图片和 PDF，最大 10MB。

    保存成功后同步执行实时 OCR 预览（OCR_PROVIDER 为 paddle 时为真实识别），
    返回识别文本、整体置信度与抽取的结构化字段（金额/日期/订单号）。
    OCR 失败或超时不影响上传本身，对应字段返回 None。
    """
    # 校验文件类型（HTTP 头声明 + 文件魔数双重校验，防伪装上传）
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"不支持的文件类型: {file.content_type}，仅支持图片和 PDF")

    # 读取文件内容（校验大小）
    content = file.file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"文件过大，最大 {MAX_UPLOAD_SIZE // 1024 // 1024}MB")

    # 魔数校验：拒绝 .exe 伪装成图片/PDF 的伪造上传
    mime_ok, mime_reason = verify_upload_mime(file.content_type, content)
    if not mime_ok:
        raise HTTPException(400, mime_reason)

    # 保存文件
    upload_dir = _ensure_upload_dir(user.id)
    # 文件按用户隔离保存，后续案件只引用自己的证据路径。
    file_ext = Path(file.filename or "upload").suffix or ".bin"
    unique_name = f"{uuid.uuid4().hex}{file_ext}"
    file_path = upload_dir / unique_name
    file_path.write_bytes(content)

    resp = UploadResponse(
        file_name=file.filename or unique_name,
        file_path=str(file_path.absolute()),
        mime_type=file.content_type or "application/octet-stream",
        file_size=len(content),
    )

    # ── 实时 OCR 预览（上传即识别，供前端回填表单）──
    from ...config import settings

    if getattr(settings, "upload_ocr_preview", True):
        ocr_text, ocr_confidence, ocr_fields = None, None, None
        try:
            deps = request.app.state.deps
            result = _run_ocr_with_timeout(deps.ocr.extract, resp.file_name, resp.file_path)
            if result is not None:
                ocr_text = result.text or None
                ocr_confidence = result.overall_confidence
                ocr_fields = result.fields or None
        except Exception as exc:  # noqa: BLE001  OCR 失败不影响上传
            import logging

            logging.getLogger(__name__).warning("上传实时 OCR 失败 %s: %s", resp.file_name, exc)
        resp.ocr_text = ocr_text
        resp.ocr_confidence = ocr_confidence
        resp.ocr_fields = ocr_fields

    return resp.model_dump()


# 共享单线程执行器：串行化 OCR 调用，避免并发加载多份 Paddle 模型撑爆内存
_OCR_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="upload-ocr")


def _run_ocr_with_timeout(extract_fn, file_name: str, file_path: str, timeout_s: int = 60):
    """在线程池中执行 OCR，超时返回 None（避免大 PDF 长时间阻塞上传请求）。"""
    future = _OCR_EXECUTOR.submit(extract_fn, file_name, file_path, None, 0)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout:
        future.cancel()
        return None


@router.put("/{case_id}/evidence/{evidence_id}/ocr")
def update_ocr_result(
    case_id: str,
    evidence_id: int,
    body: OcrCorrectionRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("supervisor", "admin")),
):
    """人工修正 OCR 结果。仅 SUSPENDED 状态的案件可修正。"""
    case = _require_case_access(db, user, case_id)
    if case.status != "SUSPENDED":
        raise HTTPException(409, f"案件当前状态为 {case.status}，不可修正 OCR")

    evidence = db.query(CaseEvidence).filter(CaseEvidence.id == evidence_id, CaseEvidence.case_id == case_id).first()
    if evidence is None:
        raise HTTPException(404, "证据记录不存在")

    before = {"ocr_text": evidence.ocr_text, "ocr_confidence": evidence.ocr_confidence}
    evidence.ocr_text = body.ocr_text
    evidence.ocr_confidence = body.ocr_confidence
    evidence.ocr_corrected_at = datetime.now(timezone.utc)
    evidence.ocr_corrected_by = user.id

    # 同时标记案件级 ocr_corrected，供决策规则跳过 OCR 置信度检查
    case.ocr_corrected = True

    db.add(
        AuditLog(
            case_id=case_id,
            actor_id=user.id,
            action="evidence:ocr_corrected",
            before_value=before,
            after_value={"ocr_text": body.ocr_text, "ocr_confidence": body.ocr_confidence},
        )
    )
    db.commit()

    deps = request.app.state.deps
    deps.publish_event(case_id, {"agent": "EvidenceAgent", "status": "ocr_corrected", "evidence_id": evidence_id})

    return {"evidence_id": evidence_id, "ocr_text": body.ocr_text, "ocr_confidence": body.ocr_confidence}


@router.post("", status_code=202)
def create_case(
    body: CaseCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("agent", "supervisor", "admin")),
    idempotency_key: str = Header(None, alias="X-Idempotency-Key"),
):
    """客服后台建案：幂等/DLP/审计/画像累计/Stream 投递统一在 case_service 生效。

    与用户端退款共用同一建案服务，仅 source 不同（agent_console），
    保证两条入口的决策链与保护机制完全一致（定稿 §4.5）。
    """
    return create_case_service(
        db,
        redis_client=request.app.state.redis,
        user=user,
        order_id=body.order_id,
        amount_cent=body.amount_cent,
        currency=body.currency,
        complaint_text=body.complaint_text,
        risk_flags=body.risk_flags,
        evidence=[e.model_dump() for e in body.evidence],
        idempotency_key=idempotency_key,
        source="agent_console",
    )


@router.get("")
def list_cases(
    status: str = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("agent", "supervisor", "admin")),
):
    query = db.query(RefundCase).order_by(RefundCase.created_at.desc())
    if user.role == "agent":
        # 客服可见范围：本人建案 ∪ 全部用户端案件（定稿 C3）
        query = query.filter(
            or_(RefundCase.user_id == user.id, RefundCase.source == "customer_portal")
        )
    if status:
        query = query.filter(RefundCase.status == status)
    total = query.count()
    cases = query.offset(offset).limit(min(limit, 200)).all()
    return {
        "total": total,
        "items": [
            {
                "case_id": c.case_id,
                "order_id": c.order_id,
                "source": c.source,
                "source_label": "用户端" if c.source == "customer_portal" else "客服后台",
                "product_name": c.product_name,
                "amount_yuan": f"{c.amount_cent / 100:.2f}",
                "status": c.status,
                "risk_level": c.risk_level,
                "decision": c.decision,
                "refund_status": c.refund_status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in cases
        ],
    }


@router.get("/{case_id}")
def get_case(case_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("agent", "supervisor", "admin"))):
    case = _require_case_access(db, user, case_id)
    return _serialize_case(db, case, request)


@router.get("/{case_id}/trace")
def get_case_trace(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("supervisor", "admin")),
):
    """查询案件 LLM 观测 Trace（Langfuse）。

    返回本地落盘的完整 Trace（span 瀑布数据），并附上报通道信息：
    - 配置了 LANGFUSE_PUBLIC_KEY/SECRET_KEY → backend=langfuse，附云端 Trace URL；
    - 未配置 → backend=file（本地文件降级），答辩演示即用此模式。

    仅主管/管理员可见（客服无需观测数据）。
    """
    from ...config import settings

    case = _require_case_access(db, user, case_id)

    langfuse_on = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
    resp = {
        "trace_id": case.trace_id,
        "backend": "langfuse" if langfuse_on else "file",
        "available": False,
        "spans": [],
    }
    if langfuse_on:
        host = (settings.langfuse_host or "https://cloud.langfuse.com").rstrip("/")
        resp["langfuse_url"] = f"{host}/trace/{case.trace_id}"

    # 本地 Trace 文件（FileBackend / Langfuse 失败缓冲均落此处）
    for base in (Path("logs/traces"), Path("backend/logs/traces")):
        path = base / f"{case.trace_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                break
            resp.update({"available": True, "spans": data.get("spans", [])})
            resp.update({k: data.get(k) for k in ("name", "start_time", "end_time", "duration_ms", "error")})
            break
    return resp


@router.get("/{case_id}/events")
def case_events(
    case_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("agent", "supervisor", "admin")),
):
    _require_case_access(db, user, case_id)
    redis = request.app.state.redis

    def gen():
        pubsub = redis.pubsub()
        pubsub.subscribe(f"case:{case_id}:events")
        yield "event: connected\ndata: {\"case_id\": \"%s\"}\n\n" % case_id
        try:
            while True:
                msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    yield f"event: update\ndata: {msg['data']}\n\n"
                else:
                    yield ": keep-alive\n\n"
        finally:
            pubsub.close()

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/{case_id}/decision")
def decide_case(
    case_id: str,
    body: DecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("supervisor", "admin")),
    idempotency_key: str = Header(None, alias="X-Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(400, "缺少 X-Idempotency-Key")
    if body.action not in ("APPROVE", "REJECT"):
        raise HTTPException(422, "action 必须为 APPROVE 或 REJECT")

    request_hash = compute_request_hash(body.model_dump())
    idem_key = approval_key(user.id, case_id, body.action, idempotency_key)

    existing = db.query(IdempotencyRecord).filter(IdempotencyRecord.key == idem_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(422, "相同幂等键但请求体不一致")
        return json.loads(existing.response_body or "{}")

    redis = request.app.state.redis
    lock_key = f"refund:approval:{case_id}"
    token = acquire_lock(redis, lock_key)
    if token is None:
        raise HTTPException(409, "案件正在被处理，请稍后重试")

    try:
        case = db.query(RefundCase).filter(RefundCase.case_id == case_id).first()
        if case is None:
            raise HTTPException(404, "案件不存在")
        if case.status != "SUSPENDED":
            raise HTTPException(409, f"案件当前状态为 {case.status}，不可审批")
        if user.id == case.user_id:
            raise HTTPException(403, "审批人不能审批自己创建的案件")

        db.add(
            AuditLog(
                case_id=case_id,
                actor_id=user.id,
                action=f"review:{body.action}",
                before_value={"status": case.status},
                after_value={"comment": body.comment},
            )
        )
        db.commit()

        graph = request.app.state.graph
        config = {"configurable": {"thread_id": case_id}}
        # 审批 resume 链路同样开启 Trace，记录 execute_refund / reject 节点 span
        from ...telemetry import begin_case_trace, end_case_trace

        begin_case_trace(
            case.trace_id,
            name="refund_case_analysis:resume",
            metadata={"case_id": case_id, "action": body.action, "reviewer": user.username},
        )
        try:
            result = graph.invoke(
                Command(resume={"action": body.action, "comment": body.comment}), config
            )
        finally:
            end_case_trace(case.trace_id)

        request.app.state.deps.update_review_task(case_id, user.id, body.action, body.comment)

        final_status = request.app.state.deps.get_case_status(case_id)
        resp = {"case_id": case_id, "status": final_status, "action": body.action}
        db.add(
            IdempotencyRecord(
                key=idem_key,
                request_hash=request_hash,
                response_body=json.dumps(resp, ensure_ascii=False),
                status_code=200,
            )
        )
        db.commit()
        return resp
    except ConcurrencyConflict as exc:
        raise HTTPException(409, str(exc))
    finally:
        release_lock(redis, lock_key, token)
