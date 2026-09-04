"""工作台统计数据接口：KPI 概览、趋势、分布。"""
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import require_role
from ...models import RefundCase, User

router = APIRouter()

agent_and_above = require_role("agent", "supervisor", "admin")


def _base_query(db: Session, user: User):
    q = db.query(RefundCase)
    if user.role == "agent":
        # 客服可见范围与案件列表一致：本人建案 ∪ 用户端案件（定稿 C3）
        q = q.filter(or_(RefundCase.user_id == user.id, RefundCase.source == "customer_portal"))
    return q


def _calc_stats(rows: list[RefundCase]) -> dict[str, Any]:
    total = len(rows)
    completed = sum(1 for r in rows if r.status == "COMPLETED")
    rejected = sum(1 for r in rows if r.status == "REJECTED")
    suspended = sum(1 for r in rows if r.status == "SUSPENDED")
    failed = sum(1 for r in rows if r.status == "FAILED")
    running = sum(1 for r in rows if r.status in ("CREATED", "RUNNING"))

    # 自动审批率：decision=APPROVE 且无人工审批记录的案件占比
    auto_approved = sum(1 for r in rows if r.decision == "APPROVE" and r.status == "COMPLETED")
    auto_rate = auto_approved / total if total > 0 else 0.0

    # 平均处理时长（仅已完结案件，秒）
    durations = []
    for r in rows:
        if r.status in ("COMPLETED", "REJECTED", "FAILED") and r.created_at and r.updated_at:
            delta = (r.updated_at - r.created_at).total_seconds()
            durations.append(delta)
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    total_amount = sum(r.amount_cent for r in rows if r.status == "COMPLETED")

    return {
        "total": total,
        "completed": completed,
        "rejected": rejected,
        "suspended": suspended,
        "failed": failed,
        "running": running,
        "auto_approved": auto_approved,
        "auto_rate": round(auto_rate, 3),
        "avg_duration_seconds": round(avg_duration, 1),
        "total_amount_cent": total_amount,
        "total_amount_yuan": round(total_amount / 100, 2),
    }


@router.get("/overview")
def stats_overview(db: Session = Depends(get_db), user: User = Depends(agent_and_above)):
    """工作台统计概览。

    - 客服：仅统计自己创建的案件
    - 主管/管理员：统计全量案件
    """
    base = _base_query(db, user)

    # 今日（UTC+8 本地时区边界）
    now = datetime.now(timezone.utc)
    local_offset = timedelta(hours=8)
    local_now = now + local_offset
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - local_offset

    today_rows = base.filter(RefundCase.created_at >= today_start).all()
    overall_rows = base.all()

    # 近 7 日趋势
    trend = []
    for i in range(6, -1, -1):
        day_start = today_start - timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        day_rows = [
            r for r in overall_rows
            if r.created_at and day_start <= r.created_at.replace(tzinfo=timezone.utc) < day_end
        ]
        label = (day_start + local_offset).strftime("%m-%d")
        trend.append(
            {
                "date": label,
                "total": len(day_rows),
                "completed": sum(1 for r in day_rows if r.status == "COMPLETED"),
                "rejected": sum(1 for r in day_rows if r.status == "REJECTED"),
                "suspended": sum(1 for r in day_rows if r.status == "SUSPENDED"),
            }
        )

    # 状态分布
    status_dist = {"CREATED": 0, "RUNNING": 0, "SUSPENDED": 0, "COMPLETED": 0, "REJECTED": 0, "FAILED": 0}
    for r in overall_rows:
        status_dist[r.status] = status_dist.get(r.status, 0) + 1

    # 风险分布（仅已评估）
    risk_dist = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "UNSET": 0}
    for r in overall_rows:
        if r.risk_level:
            risk_dist[r.risk_level] = risk_dist.get(r.risk_level, 0) + 1
        else:
            risk_dist["UNSET"] += 1

    return {
        "today": _calc_stats(today_rows),
        "overall": _calc_stats(overall_rows),
        "trend": trend,
        "status_distribution": status_dist,
        "risk_distribution": risk_dist,
    }
