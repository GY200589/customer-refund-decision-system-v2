from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import require_role
from ...models import RefundCase, ReviewTask, User

router = APIRouter()


def _serialize(
    task: ReviewTask,
    case_flags: dict | None = None,
    applicant: User | None = None,
    case: RefundCase | None = None,
) -> dict:
    flags = case_flags or {}
    return {
        "id": task.id,
        "case_id": task.case_id,
        "assigned_to": task.assigned_to,
        "status": task.status,
        "comment": task.comment,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        # SUSPENDED 超时自动升级标记（risk_flags.escalated），前端展示「已升级」
        "escalated": bool(flags.get("escalated")),
        "review_reason": case.decision_reason if case else None,
        "refund_guard": {
            "amount_yuan": f"{case.amount_cent / 100:.2f}" if case else None,
            "recommended_amount_yuan": (
                f"{flags['recommended_amount_cent'] / 100:.2f}"
                if flags.get("recommended_amount_cent") is not None
                else None
            ),
            "partial_refund": bool(flags.get("partial_refund")),
            "ocr_amount_mismatch": bool(flags.get("ocr_amount_mismatch")),
            "ocr_order_mismatch": bool(flags.get("ocr_order_mismatch")),
            "abuse_signal_count": sum(
                bool(flags.get(key))
                for key in (
                    "duplicate_evidence",
                    "cross_account_evidence_reuse",
                    "refund_velocity_24h",
                    "refund_velocity_7d",
                    "repeated_high_ratio",
                )
            ),
        },
        # 申请人画像（反薅羊毛），主管审批时一眼看到历史退款率
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
    }


@router.get("")
def list_review_tasks(db: Session = Depends(get_db), user=Depends(require_role("supervisor", "admin"))):
    tasks = db.query(ReviewTask).filter(ReviewTask.status == "PENDING").order_by(ReviewTask.id).all()
    # 一次查询取出关联案件的 risk_flags + 申请人信息，避免 N+1
    case_flags_map = {}
    case_user_map = {}
    case_map = {}
    applicant_map = {}
    if tasks:
        case_ids = [t.case_id for t in tasks]
        cases = db.query(RefundCase).filter(RefundCase.case_id.in_(case_ids)).all()
        user_ids = {c.user_id for c in cases}
        applicant_map = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
        for c in cases:
            case_map[c.case_id] = c
            case_flags_map[c.case_id] = c.risk_flags or {}
            case_user_map[c.case_id] = c.user_id
    return [
        {
            "task": _serialize(
                t,
                case_flags_map.get(t.case_id),
                applicant_map.get(case_user_map.get(t.case_id)),
                case_map.get(t.case_id),
            )
        }
        for t in tasks
    ]
