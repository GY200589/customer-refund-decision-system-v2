def run(state, deps):
    """SentimentAgent：情绪与舆情风险分级。模型异常时安全降级。"""
    case_id = state["case_id"]
    try:
        result = deps.sentiment.analyze(state.get("complaint_text", ""), state.get("risk_flags") or {})
    except Exception as exc:  # noqa: BLE001
        deps.record_agent_run(case_id, "SentimentAgent", "FAILED", error=str(exc))
        return {"errors": [f"SentimentAgent: {exc}"], "sentiment_score": 0, "risk_level": "LOW"}

    deps.record_agent_run(
        case_id, "SentimentAgent", "SUCCESS",
        output_summary=f"sentiment={result.sentiment_score} level={result.risk_level}",
    )
    deps.publish_event(
        case_id,
        {"agent": "SentimentAgent", "status": "done", "sentiment_score": result.sentiment_score, "risk_level": result.risk_level},
    )
    return {"sentiment_score": result.sentiment_score, "risk_level": result.risk_level}
