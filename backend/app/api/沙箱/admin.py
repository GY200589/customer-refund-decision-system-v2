"""管理员路由：阈值配置、用户管理、审计查询（仅 admin 角色可访问）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import require_role
from ...models import AuditLog, User
from ...schemas import ThresholdUpdateRequest, UserCreateRequest, UserUpdateRequest
from ...security import hash_password
from ...services import config_store

router = APIRouter()

admin_only = require_role("admin")


# ---------------- 阈值配置 ----------------

@router.get("/thresholds")
def get_thresholds(db: Session = Depends(get_db), user: User = Depends(admin_only)):
    return config_store.get_thresholds(db)


@router.put("/thresholds")
def update_thresholds(
    body: ThresholdUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(422, "至少提供一个阈值字段")
    before = config_store.get_thresholds(db)
    after = config_store.set_thresholds(db, updates, actor_id=user.id)
    db.add(
        AuditLog(
            case_id=None,
            actor_id=user.id,
            action="config:thresholds:update",
            before_value=before,
            after_value=after,
        )
    )
    db.commit()
    return after


# ---------------- 用户管理 ----------------

def _serialize_user(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "display_name": u.display_name,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(admin_only)):
    users = db.query(User).order_by(User.id).all()
    return [_serialize_user(u) for u in users]


@router.post("/users", status_code=201)
def create_user(
    body: UserCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(409, "用户名已存在")
    new_user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        display_name=body.display_name or body.username,
        is_active=True,
    )
    db.add(new_user)
    db.flush()
    db.add(
        AuditLog(
            actor_id=user.id,
            action="user:created",
            after_value={"username": body.username, "role": body.role},
        )
    )
    db.commit()
    return _serialize_user(new_user)


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(admin_only),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")

    changes = body.model_dump(exclude_unset=True)

    # 防止管理员把自己锁死：不能禁用自己，也不能把自己的角色改成非 admin
    if target.id == actor.id:
        if changes.get("is_active") is False:
            raise HTTPException(409, "不能禁用当前登录账号")
        if changes.get("role") not in (None, "admin"):
            raise HTTPException(409, "不能降级当前登录账号的角色")

    before = _serialize_user(target)
    if "password" in changes:
        target.password_hash = hash_password(changes.pop("password"))
    for field, value in changes.items():
        setattr(target, field, value)
    db.flush()
    db.add(
        AuditLog(
            actor_id=actor.id,
            action="user:updated",
            before_value=before,
            after_value=_serialize_user(target),
        )
    )
    db.commit()
    return _serialize_user(target)


# ---------------- 智能客服评测（定稿 §4.9）----------------

@router.post("/assistant/eval/run")
def run_assistant_eval(user: User = Depends(admin_only)):
    """运行客服能力评测（意图/RAG/动作），返回完整报告并落盘 eval/reports/。"""
    from ...eval.run_assistant_eval import run_eval

    return run_eval()


@router.get("/assistant/eval/reports")
def list_assistant_eval_reports(user: User = Depends(admin_only)):
    from ...eval.run_assistant_eval import list_reports

    return {"items": list_reports()}


@router.get("/assistant/eval/reports/{report_id}")
def get_assistant_eval_report(report_id: str, user: User = Depends(admin_only)):
    from ...eval.run_assistant_eval import load_report

    report = load_report(report_id)
    if report is None:
        raise HTTPException(404, "评测报告不存在")
    return report


# ---------------- 审计查询 ----------------

@router.get("/audit-logs")
def list_audit_logs(
    case_id: str = None,
    actor_id: int = None,
    action: str = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    query = db.query(AuditLog).order_by(AuditLog.id.desc())
    if case_id:
        query = query.filter(AuditLog.case_id == case_id)
    if actor_id is not None:
        query = query.filter(AuditLog.actor_id == actor_id)
    if action:
        query = query.filter(AuditLog.action == action)
    total = query.count()
    logs = query.offset(offset).limit(min(limit, 500)).all()

    actor_ids = {log.actor_id for log in logs if log.actor_id is not None}
    username_map = {
        u.id: u.username
        for u in db.query(User).filter(User.id.in_(actor_ids)).all()
    } if actor_ids else {}

    return {
        "total": total,
        "items": [
            {
                "id": log.id,
                "case_id": log.case_id,
                "actor_id": log.actor_id,
                "actor_username": username_map.get(log.actor_id),
                "action": log.action,
                "before_value": log.before_value,
                "after_value": log.after_value,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
