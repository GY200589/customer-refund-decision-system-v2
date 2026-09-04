"""telemetry 案例级 Trace 注册表与 graph 埋点单测"""
import json
import threading

from app.telemetry import (
    FileBackend,
    TraceContext,
    begin_case_trace,
    end_case_trace,
    get_active_trace,
    tracer,
)


def _use_file_backend(tmp_path, monkeypatch):
    backend = FileBackend(log_dir=str(tmp_path))
    monkeypatch.setattr(tracer, "backend", backend)
    return backend


def test_begin_get_end_roundtrip(tmp_path, monkeypatch):
    _use_file_backend(tmp_path, monkeypatch)

    trace = begin_case_trace("tid-1", metadata={"case_id": "c1"})
    assert isinstance(trace, TraceContext)
    assert get_active_trace("tid-1") is trace
    assert get_active_trace("tid-2") is None

    assert end_case_trace("tid-1") is True
    assert get_active_trace("tid-1") is None
    # 重复结束：已注销，返回 False
    assert end_case_trace("tid-1") is False


def test_end_writes_trace_file_with_spans(tmp_path, monkeypatch):
    _use_file_backend(tmp_path, monkeypatch)

    trace = begin_case_trace("tid-file", metadata={"case_id": "c2"})
    span = trace.spans[0] if trace.spans else None
    assert span is None  # 新 trace 无 span
    # 模拟 graph 节点埋点
    from app.telemetry import SpanContext

    trace.add_span(
        SpanContext(
            span_id="s1",
            trace_id="tid-file",
            span_type="llm",
            name="merged_risk",
            start_time=100.0,
            end_time=100.5,
            input={"order_id": "O1"},
            output={"decision": "APPROVE"},
        )
    )
    end_case_trace("tid-file")

    data = json.loads((tmp_path / "tid-file.json").read_text(encoding="utf-8"))
    assert data["trace_id"] == "tid-file"
    assert len(data["spans"]) == 1
    assert data["spans"][0]["span_type"] == "llm"
    assert data["spans"][0]["duration_ms"] == 500.0
    assert data["duration_ms"] >= 0


def test_concurrent_traces_are_isolated(tmp_path, monkeypatch):
    """worker 并发处理多案件时，各线程的 trace 互不串扰。"""
    _use_file_backend(tmp_path, monkeypatch)
    begin_case_trace("tid-a")
    begin_case_trace("tid-b")
    results = {}

    def worker(tid):
        t = get_active_trace(tid)
        assert t is not None and t.trace_id == tid
        results[tid] = end_case_trace(tid)

    threads = [threading.Thread(target=worker, args=(t,)) for t in ("tid-a", "tid-b")]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results == {"tid-a": True, "tid-b": True}


def test_graph_traced_wrapper_records_span(tmp_path, monkeypatch):
    """graph 节点 wrapper：有 trace 时写 span，无 trace 时零开销直通。"""
    _use_file_backend(tmp_path, monkeypatch)
    from app.workflow.graph import _traced

    calls = []

    def fake_node(state):
        calls.append(state["order_id"])
        return {"decision": "APPROVE", "risk_level": "LOW"}

    wrapped = _traced("merged_risk", fake_node)

    # 无 active trace：正常执行，不产生 span
    assert wrapped({"order_id": "O1", "trace_id": "none"}) == {"decision": "APPROVE", "risk_level": "LOW"}

    # 有 active trace：span 记录 name/类型/输出摘要
    trace = begin_case_trace("tid-g", metadata={})
    result = wrapped({"order_id": "O2", "amount_cent": 100, "trace_id": "tid-g"})
    assert result["decision"] == "APPROVE"
    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert span.name == "merged_risk"
    assert span.span_type == "llm"
    assert span.output == {"decision": "APPROVE", "risk_level": "LOW"}
    assert span.error is None
    end_case_trace("tid-g")
    assert calls == ["O1", "O2"]


def test_graph_traced_wrapper_records_error(tmp_path, monkeypatch):
    _use_file_backend(tmp_path, monkeypatch)
    from app.workflow.graph import _traced

    def boom(state):
        raise ValueError("node exploded")

    wrapped = _traced("evidence", boom)
    trace = begin_case_trace("tid-err")

    try:
        wrapped({"order_id": "O3", "trace_id": "tid-err"})
        raise AssertionError("should raise")
    except ValueError:
        pass

    span = trace.spans[0]
    assert span.error == "node exploded"
    assert span.end_time is not None
    end_case_trace("tid-err")
