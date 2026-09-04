import time
import uuid as _uuid

from langgraph.graph import END, START, StateGraph

from .. import agents
from ..telemetry import SpanContext, get_active_trace
from .state import WorkflowState

# span 类型：merged_risk 为一次 LLM 调用（欺诈+舆情双评分），其余为工具/规则节点
_LLM_NODES = {"merged_risk"}


def _traced(node_key: str, fn):
    """节点埋点包装：向案件级 Trace 写入一个 span（无 Trace 时零开销直通）。

    span 记录节点名、耗时、入参摘要（订单/金额）与出参摘要（决策/风险/错误），
    供 Langfuse 观测与前端 Trace 瀑布图展示。
    """

    def wrapped(state):
        trace = get_active_trace(state.get("trace_id") or "")
        span = None
        if trace is not None:
            span = SpanContext(
                span_id=_uuid.uuid4().hex[:12],
                trace_id=trace.trace_id,
                span_type="llm" if node_key in _LLM_NODES else "tool",
                name=node_key,
                start_time=time.time(),
                input={
                    "order_id": state.get("order_id"),
                    "amount_cent": state.get("amount_cent"),
                },
            )
            trace.add_span(span)
        try:
            result = fn(state)
            if span is not None:
                span.end_time = time.time()
                span.output = {
                    k: result.get(k)
                    for k in ("decision", "risk_level", "risk_flags")
                    if isinstance(result, dict) and result.get(k) is not None
                }
                if isinstance(result, dict) and result.get("errors"):
                    span.output = {**(span.output or {}), "errors": result["errors"]}
            return result
        except Exception as exc:  # noqa: BLE001
            if span is not None:
                span.end_time = time.time()
                span.error = str(exc)
            raise

    return wrapped


def build_graph(deps):
    g = StateGraph(WorkflowState)

    g.add_node("intake", _traced("intake", lambda s: agents.intake.run(s, deps)))
    g.add_node("order_verify", _traced("order_verify", lambda s: agents.order_verify.run(s, deps)))
    g.add_node("product_consistency", _traced("product_consistency", lambda s: agents.product_consistency.run(s, deps)))
    g.add_node("critic", _traced("critic", lambda s: agents.critic.run(s, deps)))
    g.add_node("evidence", _traced("evidence", lambda s: agents.evidence.run(s, deps)))
    g.add_node("fraud", _traced("fraud", lambda s: agents.fraud.run(s, deps)))
    g.add_node("sentiment", _traced("sentiment", lambda s: agents.sentiment.run(s, deps)))
    g.add_node("merged_risk", _traced("merged_risk", lambda s: agents.merged_risk.run(s, deps)))
    g.add_node("decision", _traced("decision", lambda s: agents.decision.run(s, deps)))
    g.add_node("human_review", _traced("human_review", lambda s: agents.human_review.run(s, deps)))
    g.add_node("execute_refund", _traced("execute_refund", lambda s: agents.execute.run(s, deps)))
    g.add_node("reject", _traced("reject", lambda s: agents.reject.run(s, deps)))

    g.add_edge(START, "intake")
    g.add_edge("intake", "order_verify")
    g.add_edge("order_verify", "product_consistency")
    g.add_edge("product_consistency", "critic")
    # CriticAgent 路由：检测到注入 → reject，通过 → evidence
    def route_critic(state):
        errors = state.get("errors", [])
        if any("CriticAgent" in str(e) for e in errors):
            return "reject"
        return "evidence"

    g.add_conditional_edges(
        "critic",
        route_critic,
        {"reject": "reject", "evidence": "evidence"},
    )
    g.add_edge("evidence", "merged_risk")
    g.add_edge("merged_risk", "decision")

    def route_decision(state):
        # 决策节点只产出结论；这里统一把结论映射为后续业务动作。
        d = state.get("decision")
        if d == "APPROVE":
            return "execute_refund"
        if d == "REJECT":
            return "reject"
        return "human_review"

    def route_after_review(state):
        # 人工审批后沿用同一条出口：批准执行退款，其余结果进入拒绝流程。
        return "execute_refund" if state.get("decision") == "APPROVE" else "reject"

    g.add_conditional_edges(
        "decision",
        route_decision,
        {"execute_refund": "execute_refund", "reject": "reject", "human_review": "human_review"},
    )
    g.add_conditional_edges(
        "human_review",
        route_after_review,
        {"execute_refund": "execute_refund", "reject": "reject"},
    )
    g.add_edge("execute_refund", END)
    g.add_edge("reject", END)

    return g.compile(checkpointer=deps.checkpointer)
