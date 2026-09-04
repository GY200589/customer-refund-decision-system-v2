"""CriticAgent — 注入检测 Workflow 节点

在 IntakeAgent 之后、EvidenceAgent 之前执行，
对投诉文本进行注入检测，拦截恶意输入。
"""
import logging

logger = logging.getLogger(__name__)


def run(state, deps):
    """CriticAgent：注入检测与拦截

    检查投诉文本中是否存在注入攻击（SQL 注入、XSS、Prompt 注入等）。
    结果写入 state.errors 或 risk_flags。
    """
    case_id = state["case_id"]
    complaint_text = state.get("complaint_text", "")
    risk_flags = state.get("risk_flags", {})

    result = deps.security.check_injection(complaint_text, risk_flags)

    if result.action == "REJECT":
        deps.record_agent_run(
            case_id, "CriticAgent", "BLOCKED",
            input_summary=f"检测到注入攻击",
            output_summary=result.reason,
        )
        deps.publish_event(case_id, {
            "agent": "CriticAgent",
            "status": "blocked",
            "reason": result.reason,
            "matched_rules": result.matched_rules,
        })
        # 写入审计日志
        from ..models import AuditLog
        from ..db import SessionLocal
        with SessionLocal() as db:
            db.add(AuditLog(
                case_id=case_id,
                actor_id=None,
                action="critic:blocked",
                before_value={"complaint_text": complaint_text[:200]},
                after_value={"reason": result.reason, "matched_rules": result.matched_rules},
            ))
            db.commit()
        return {"errors": [f"CriticAgent: {result.reason}"]}

    if result.action == "REVIEW":
        deps.record_agent_run(
            case_id, "CriticAgent", "REVIEW",
            output_summary=f"需人工复核: {result.reason}",
        )
        # 标记 risk_flags 需要人工复核
        return {
            "risk_flags": {
                **risk_flags,
                "critic_review": True,
                "critic_review_reason": result.reason,
            },
        }

    deps.record_agent_run(
        case_id, "CriticAgent", "SUCCESS",
        output_summary="注入检测通过",
    )
    deps.publish_event(case_id, {"agent": "CriticAgent", "status": "passed"})
    return {}