from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.container import Deps
from app.db import SessionLocal
from app.infrastructure.redis_client import build_redis
from app.models import RefundCase, ReviewTask, User
from app.workflow.graph import build_graph


def _deps():
    return Deps(build_redis(), MemorySaver())


def _agent_id():
    with SessionLocal() as db:
        return db.query(User.id).filter(User.role == "agent").scalar()


def _create_case(order_id, amount_cent, complaint="", risk_flags=None, evidence=None):
    with SessionLocal() as db:
        case = RefundCase(
            order_id=order_id,
            user_id=_agent_id(),
            amount_cent=amount_cent,
            complaint_text=complaint,
            risk_flags=risk_flags or {},
            status="CREATED",
        )
        db.add(case)
        db.commit()
        db.refresh(case)
        return case.case_id


def _state(case_id, order_id, amount_cent, complaint="", risk_flags=None, evidence=None):
    return {
        "case_id": case_id,
        "trace_id": case_id,
        "order_id": order_id,
        "amount_cent": amount_cent,
        "complaint_text": complaint,
        "risk_flags": risk_flags or {},
        "evidence": evidence or [],
    }


def test_scenario_b_low_amount_auto_complete(db_setup):
    deps = _deps()
    graph = build_graph(deps)
    case_id = _create_case(
        "order-b-1", 12800, complaint="系统故障导致错误扣费",
        evidence=[{"file_name": "clear.jpg", "file_hash": "h1"}],
    )
    deps.transition(case_id, "CREATED", "RUNNING")
    result = graph.invoke(
        _state(case_id, "order-b-1", 12800, "系统故障导致错误扣费", evidence=[{"file_name": "clear.jpg", "file_hash": "h1"}]),
        {"configurable": {"thread_id": case_id}},
    )
    assert "__interrupt__" not in result
    assert deps.get_case_status(case_id) == "COMPLETED"
    with SessionLocal() as db:
        case = db.query(RefundCase).filter(RefundCase.case_id == case_id).one()
        assert case.fraud_score == 20
        assert case.risk_level == "LOW"
        assert case.refund_status == "EXECUTED"


def test_frequency_signal_alone_does_not_force_manual_review(db_setup):
    deps = _deps()
    graph = build_graph(deps)
    flags = {"refund_velocity_24h": True, "requested_ratio": 0.15}
    case_id = _create_case(
        "order-frequency-only", 1500, complaint="轻微线头，按建议部分退款",
        risk_flags=flags, evidence=[{"file_name": "clear-frequency.jpg", "file_hash": "frequency-only"}],
    )
    deps.transition(case_id, "CREATED", "RUNNING")
    result = graph.invoke(
        _state(
            case_id,
            "order-frequency-only",
            1500,
            "轻微线头，按建议部分退款",
            risk_flags=flags,
            evidence=[{"file_name": "clear-frequency.jpg", "file_hash": "frequency-only"}],
        ),
        {"configurable": {"thread_id": case_id}},
    )
    assert "__interrupt__" not in result
    with SessionLocal() as db:
        case = db.query(RefundCase).filter(RefundCase.case_id == case_id).one()
        assert case.status == "COMPLETED"
        assert case.fraud_score < 50
        assert "短期退款申请较频繁" in (case.risk_flags or {}).get("risk_factors", []) or case.fraud_score == 25


def test_scenario_a_high_amount_suspend_then_approve(db_setup):
    deps = _deps()
    graph = build_graph(deps)
    case_id = _create_case(
        "order-a-1", 35000, complaint="商品破损",
        evidence=[{"file_name": "invoice.jpg", "file_hash": "h2"}],
    )
    deps.transition(case_id, "CREATED", "RUNNING")
    result = graph.invoke(
        _state(case_id, "order-a-1", 35000, "商品破损", evidence=[{"file_name": "invoice.jpg", "file_hash": "h2"}]),
        {"configurable": {"thread_id": case_id}},
    )
    assert "__interrupt__" in result
    assert deps.get_case_status(case_id) == "SUSPENDED"
    # 退款动作未执行
    with SessionLocal() as db:
        case = db.query(RefundCase).filter(RefundCase.case_id == case_id).one()
        assert case.refund_status != "EXECUTED"
        assert db.query(ReviewTask).filter(ReviewTask.case_id == case_id).count() == 1

    resumed = graph.invoke(
        Command(resume={"action": "APPROVE", "comment": "情况属实，批准退款"}),
        {"configurable": {"thread_id": case_id}},
    )
    assert deps.get_case_status(case_id) == "COMPLETED"
    assert resumed.get("review_comment") == "情况属实，批准退款"


def test_scenario_a_reject(db_setup):
    deps = _deps()
    graph = build_graph(deps)
    case_id = _create_case("order-a-2", 35000, complaint="商品破损", evidence=[{"file_name": "invoice.jpg"}])
    deps.transition(case_id, "CREATED", "RUNNING")
    graph.invoke(
        _state(case_id, "order-a-2", 35000, "商品破损", evidence=[{"file_name": "invoice.jpg"}]),
        {"configurable": {"thread_id": case_id}},
    )
    graph.invoke(Command(resume={"action": "REJECT", "comment": "不符合退款条件"}), {"configurable": {"thread_id": case_id}})
    assert deps.get_case_status(case_id) == "REJECTED"


def test_no_evidence_goes_human_review(db_setup):
    deps = _deps()
    graph = build_graph(deps)
    case_id = _create_case("order-e-1", 5000, complaint="无凭证")
    deps.transition(case_id, "CREATED", "RUNNING")
    result = graph.invoke(
        _state(case_id, "order-e-1", 5000, "无凭证"),
        {"configurable": {"thread_id": case_id}},
    )
    assert "__interrupt__" in result
    assert deps.get_case_status(case_id) == "SUSPENDED"


def test_optional_evidence_reason_without_upload_auto_completes(db_setup):
    deps = _deps()
    graph = build_graph(deps)
    flags = {"reason_code": "size", "evidence_required": False, "requested_ratio": 1.0}
    case_id = _create_case(
        "order-size-no-proof", 9900, complaint="尺码不合适",
        risk_flags=flags,
    )
    deps.transition(case_id, "CREATED", "RUNNING")
    result = graph.invoke(
        _state(
            case_id,
            "order-size-no-proof",
            9900,
            "尺码不合适",
            risk_flags=flags,
        ),
        {"configurable": {"thread_id": case_id}},
    )
    assert "__interrupt__" not in result
    with SessionLocal() as db:
        case = db.query(RefundCase).filter(RefundCase.case_id == case_id).one()
        assert case.status == "COMPLETED"


def test_ocr_amount_mismatch_suspends_for_manual_review(db_setup):
    deps = _deps()
    graph = build_graph(deps)
    case_id = _create_case(
        "order-ocr-mismatch", 5000, complaint="退款商品有质量问题",
        evidence=[{"file_name": "amount-9.99.jpg", "file_hash": "ocr-mismatch"}],
    )
    deps.transition(case_id, "CREATED", "RUNNING")
    result = graph.invoke(
        _state(
            case_id,
            "order-ocr-mismatch",
            5000,
            "退款商品有质量问题",
            evidence=[{"file_name": "amount-9.99.jpg", "file_hash": "ocr-mismatch"}],
        ),
        {"configurable": {"thread_id": case_id}},
    )
    assert "__interrupt__" in result
    with SessionLocal() as db:
        case = db.query(RefundCase).filter(RefundCase.case_id == case_id).one()
        assert case.status == "SUSPENDED"
        assert case.risk_flags["ocr_amount_mismatch"] is True
        assert "OCR 凭证金额" in case.decision_reason


def test_multiple_professional_abuse_signals_are_rejected(db_setup):
    deps = _deps()
    graph = build_graph(deps)
    risk_flags = {
        "cross_account_evidence_reuse": True,
        "refund_velocity_24h": True,
        "repeated_high_ratio": True,
    }
    case_id = _create_case(
        "order-abuse-signals", 5000, complaint="退款商品有质量问题",
        risk_flags=risk_flags, evidence=[{"file_name": "clear-abuse.jpg", "file_hash": "abuse"}],
    )
    deps.transition(case_id, "CREATED", "RUNNING")
    result = graph.invoke(
        _state(
            case_id,
            "order-abuse-signals",
            5000,
            "退款商品有质量问题",
            risk_flags=risk_flags,
            evidence=[{"file_name": "clear-abuse.jpg", "file_hash": "abuse"}],
        ),
        {"configurable": {"thread_id": case_id}},
    )
    assert "__interrupt__" not in result
    with SessionLocal() as db:
        case = db.query(RefundCase).filter(RefundCase.case_id == case_id).one()
        assert case.status == "REJECTED"
        assert case.fraud_score >= 85
