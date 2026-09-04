from datetime import datetime, timezone

from sqlalchemy import update

from .db import SessionLocal
from .domain.exceptions import ConcurrencyConflict
from .domain.state_machine import assert_transition
from .infrastructure import streams
from .infrastructure.providers import (
    get_combined_risk_provider,
    get_ocr_provider,
    get_order_verify_provider,
    get_product_consistency_provider,
    get_refund_provider,
    get_risk_provider,
    get_sentiment_provider,
)
from .models import AgentRun, AuditLog, CaseEvidence, RefundCase, ReviewTask, RiskAssessment, User
from .security import SecurityProvider
from .security.config import security_config
from .services import config_store, refund_guard


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Deps:
    """工作流与 API 共享的依赖容器。"""

    def __init__(self, redis_client, checkpointer=None):
        self.redis = redis_client
        # 传入 redis_client：OCR 结果缓存（upload 预览 -> EvidenceAgent 复用）
        self.ocr = get_ocr_provider(redis_client=redis_client)
        self.risk = get_risk_provider()
        self.sentiment = get_sentiment_provider()
        self.combined_risk = get_combined_risk_provider()
        self.refund = get_refund_provider()
        self.order_verify = get_order_verify_provider()
        self.product_consistency = get_product_consistency_provider()
        self.checkpointer = checkpointer
        self.security = SecurityProvider()

    def session(self):
        return SessionLocal()

    # ---- 事件 ----
    def publish_event(self, case_id: str, event: dict) -> None:
        streams.publish_event(self.redis, case_id, event)

    # ---- Agent 执行记录 ----
    def record_agent_run(self, case_id, agent_name, status, input_summary=None, output_summary=None, error=None):
        with self.session() as db:
            run = AgentRun(
                case_id=case_id,
                agent_name=agent_name,
                status=status,
                input_summary=input_summary,
                output_summary=output_summary,
                error=error,
            )
            if status in ("SUCCESS", "FAILED"):
                run.finished_at = _utcnow()
            db.add(run)
            db.commit()

    # ---- 状态流转（乐观锁 + 审计）----
    def transition(self, case_id, from_status, to_status, **fields):
        with self.session() as db:
            case = db.query(RefundCase).filter(RefundCase.case_id == case_id).one()
            if case.status != from_status:
                raise ConcurrencyConflict(f"状态已变更: 期望 {from_status}, 实际 {case.status}")
            assert_transition(case.status, to_status)
            # 状态、版本号和审计日志放在同一事务里，保证每次流转都可追溯。
            before = {"status": case.status, "version": case.version}
            result = db.execute(
                update(RefundCase)
                .where(
                    RefundCase.case_id == case_id,
                    RefundCase.status == from_status,
                    RefundCase.version == case.version,
                )
                .values(status=to_status, version=case.version + 1, updated_at=_utcnow(), **fields)
            )
            if result.rowcount == 0:
                raise ConcurrencyConflict(f"乐观锁失败: {case_id}")
            db.add(
                AuditLog(
                    case_id=case_id,
                    actor_id=None,
                    action=f"transition:{from_status}->{to_status}",
                    before_value=before,
                    after_value={"status": to_status, "version": case.version + 1},
                )
            )
            db.commit()

    def get_case_status(self, case_id) -> str:
        with self.session() as db:
            return db.query(RefundCase.status).filter(RefundCase.case_id == case_id).scalar()

    def persist_case(self, case_id, **fields):
        with self.session() as db:
            db.execute(
                update(RefundCase).where(RefundCase.case_id == case_id).values(updated_at=_utcnow(), **fields)
            )
            db.commit()

    # ---- 证据 / 风险 ----
    def update_evidence(self, case_id, file_name, ocr_text, ocr_confidence):
        with self.session() as db:
            row = (
                db.query(CaseEvidence)
                .filter(CaseEvidence.case_id == case_id, CaseEvidence.file_name == file_name)
                .first()
            )
            if row:
                row.ocr_text = ocr_text
                row.ocr_confidence = ocr_confidence
                db.commit()

    def persist_risk(self, case_id, fraud, sentiment, risk_level, factors):
        with self.session() as db:
            db.add(
                RiskAssessment(
                    case_id=case_id,
                    fraud_score=fraud,
                    sentiment_score=sentiment,
                    risk_level=risk_level,
                    risk_factors=factors,
                    rule_version="v1",
                )
            )
            db.commit()

    # ---- 运行时阈值配置 ----
    def get_thresholds(self) -> dict:
        with self.session() as db:
            return config_store.get_thresholds(db)

    # ---- 用户长期退款画像（反薅羊毛）----
    def get_user_refund_rate(self, user_id: int) -> float:
        """返回用户当前长期退款率（0~1）。新用户或无历史时为 0。"""
        with self.session() as db:
            user = db.get(User, user_id)
            if user is None:
                return 0.0
            if user.role == "customer":
                return float(refund_guard.customer_refund_profile(db, user_id)["refund_rate"])
            return float(user.refund_rate or 0.0)

    def refresh_user_refund_rate(self, user_id: int | None) -> None:
        """根据用户历史案件终态重新计算退款率并落库（幂等，可安全重复调用）。"""
        if user_id is None:
            return
        with self.session() as db:
            user = db.get(User, user_id)
            if user is None:
                return
            if user.role == "customer":
                refund_guard.refresh_customer_refund_profile(db, user)
                db.commit()
                return
            total = db.query(RefundCase).filter(RefundCase.user_id == user_id).count()
            refunded = (
                db.query(RefundCase)
                .filter(RefundCase.user_id == user_id, RefundCase.refund_status == "EXECUTED")
                .count()
            )
            user.total_cases = total
            user.refund_count = refunded
            user.reject_count = total - refunded
            user.refund_rate = refunded / total if total > 0 else 0.0
            db.commit()

    # ---- 人工审核任务（Least Active 派单）----
    def create_review_task(self, case_id):
        with self.session() as db:
            supervisor = self._least_active_supervisor(db)
            db.add(ReviewTask(case_id=case_id, assigned_to=supervisor.id if supervisor else None, status="PENDING"))
            db.commit()

    def update_review_task(self, case_id, actor_id, status, comment):
        with self.session() as db:
            task = (
                db.query(ReviewTask)
                .filter(ReviewTask.case_id == case_id, ReviewTask.status == "PENDING")
                .order_by(ReviewTask.id.desc())
                .first()
            )
            if task:
                task.status = status
                task.comment = comment
                task.decided_at = _utcnow()
                task.assigned_to = actor_id
                db.commit()

    def _least_active_supervisor(self, db):
        supervisors = db.query(User).filter(User.role == "supervisor", User.is_active.is_(True)).all()
        if not supervisors:
            return None
        counts = {
            s.id: db.query(ReviewTask)
            .filter(ReviewTask.assigned_to == s.id, ReviewTask.status == "PENDING")
            .count()
            for s in supervisors
        }
        return min(supervisors, key=lambda s: (counts[s.id], s.id))

    # ---- 退款执行（幂等）----
    def is_refund_executed(self, case_id) -> bool:
        with self.session() as db:
            return db.query(RefundCase.refund_status).filter(RefundCase.case_id == case_id).scalar() == "EXECUTED"

    def mark_refund_executed(self, case_id, refund_ref):
        with self.session() as db:
            db.execute(
                update(RefundCase)
                .where(RefundCase.case_id == case_id)
                .values(refund_status="EXECUTED", refund_ref=refund_ref, updated_at=_utcnow())
            )
            db.add(
                AuditLog(
                    case_id=case_id,
                    actor_id=None,
                    action="refund:executed",
                    after_value={"refund_ref": refund_ref},
                )
            )
            db.commit()
