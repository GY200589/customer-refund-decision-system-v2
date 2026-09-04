"""Telemetry 模块 — 可观测入口

提供三层 Span 封装（LLM / 工具 / 沙箱），异步上报 Langfuse，
失败时降级到本地缓冲。

移植自 工单5「Agent评测、成本优化与本地沙箱安全协作系统」
"""
import os
import json
import time
import uuid
import queue
import logging
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Optional, Any

logger = logging.getLogger(__name__)

# ── 数据模型 ──


@dataclass
class SpanContext:
    """单次调用上下文"""
    span_id: str
    trace_id: str    # 共享 trace_id
    parent_id: Optional[str] = None
    span_type: str = "tool"  # llm | tool | sandbox
    name: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    input: Any = None
    output: Any = None
    metadata: dict = field(default_factory=dict)
    error: Optional[str] = None
    tags: list = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000


@dataclass
class TraceContext:
    """完整 Trace"""
    trace_id: str
    name: str = "agent_analysis"
    spans: list = field(default_factory=list)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    error: Optional[str] = None

    def add_span(self, span: SpanContext):
        self.spans.append(span)

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000


# ── 抽象上报器 ──


class TracerBackend(ABC):
    """追踪后端抽象"""
    @abstractmethod
    def report_trace(self, trace: TraceContext) -> bool:
        ...

    @abstractmethod
    def flush(self) -> bool:
        ...


class NullBackend(TracerBackend):
    """空实现（无操作）"""
    def report_trace(self, trace: TraceContext) -> bool:
        return True

    def flush(self) -> bool:
        return True


class FileBackend(TracerBackend):
    """文件落盘（用于离线调试/审计）"""
    def __init__(self, log_dir: str = "logs/traces"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def report_trace(self, trace: TraceContext) -> bool:
        try:
            path = os.path.join(self.log_dir, f"{trace.trace_id}.json")
            # 每个案件一个 JSON Trace，既便于离线排查，也方便前端按 trace_id 查询。
            data = {
                "trace_id": trace.trace_id,
                "name": trace.name,
                "start_time": trace.start_time,
                "end_time": trace.end_time,
                "duration_ms": trace.duration_ms,
                "error": trace.error,
                "spans": [
                    {
                        "span_id": s.span_id,
                        "parent_id": s.parent_id,
                        "span_type": s.span_type,
                        "name": s.name,
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "duration_ms": s.duration_ms,
                        "error": s.error,
                        "input": str(s.input)[:500],
                        "output": str(s.output)[:500],
                    }
                    for s in trace.spans
                ],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.warning("FileBackend 写入失败: %s", e)
            return False

    def flush(self) -> bool:
        return True


class LangfuseBackend(TracerBackend):
    """Langfuse 异步上报（后台线程 + 指数退避重试 + 失败落盘缓冲）

    两条红线落地：
    - 上报不阻塞主流程：report_trace 仅将 payload 入队立即返回，后台线程消费；
    - 通道自动重连：上传失败按指数退避重试，重试耗尽后写入本地缓冲文件待重放。
    """

    API_URL = "https://api.langfuse.com/api/public/traces"
    MAX_RETRIES = 3
    BASE_BACKOFF_S = 1.0
    FLUSH_TIMEOUT_S = 10.0

    def __init__(self, public_key: str = "", secret_key: str = "", host: Optional[str] = None,
                 max_retries: int = MAX_RETRIES,
                 buffer_path: str = "logs/traces/failed_buffer.jsonl"):
        self.public_key = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        self.secret_key = secret_key or os.environ.get("LANGFUSE_SECRET_KEY", "")
        self.host = host or os.environ.get("LANGFUSE_HOST", self.API_URL)
        self.max_retries = max_retries
        self.buffer_path = buffer_path
        self._enabled = bool(self.public_key and self.secret_key)
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._closed = False
        if not self._enabled:
            logger.info("Langfuse 未配置 Key，使用 FileBackend 降级")
            return
        os.makedirs(os.path.dirname(self.buffer_path) or ".", exist_ok=True)
        self._worker = threading.Thread(
            target=self._upload_loop, name="langfuse-uploader", daemon=True
        )
        self._worker.start()

    def report_trace(self, trace: TraceContext) -> bool:
        if not self._enabled:
            return False
        # 序列化后入队，避免后台线程读取时 trace 对象被后续修改
        self._queue.put(self._build_payload(trace))
        return True

    def _upload_loop(self) -> None:
        while not self._closed:
            try:
                payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._upload_with_retry(payload)
            finally:
                self._queue.task_done()

    def _upload_with_retry(self, payload: dict) -> None:
        import httpx
        headers = {
            "Authorization": f"Bearer {self.public_key}:{self.secret_key}",
            "Content-Type": "application/json",
        }
        backoff = self.BASE_BACKOFF_S
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = httpx.post(self.host, json=payload, headers=headers, timeout=5.0)
                if resp.is_success:
                    return
                logger.warning(
                    "Langfuse 上报失败 (HTTP %s)，第 %d/%d 次重试",
                    resp.status_code, attempt, self.max_retries,
                )
            except Exception as e:
                logger.warning(
                    "Langfuse 上报异常: %s，第 %d/%d 次重试", e, attempt, self.max_retries
                )
            if attempt < self.max_retries:
                time.sleep(backoff)
                backoff *= 2
        # 重试耗尽：落本地缓冲，不丢 Trace
        self._buffer_failed(payload)

    def _buffer_failed(self, payload: dict) -> None:
        try:
            with open(self.buffer_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            logger.warning("Trace 上报重试耗尽，已落本地缓冲: %s", self.buffer_path)
        except Exception as e:
            logger.warning("本地缓冲写入失败: %s", e)

    def _build_payload(self, trace: TraceContext) -> dict:
        return {
            "id": trace.trace_id,
            "name": trace.name,
            "timestamp": trace.start_time,
            "metadata": trace.metadata,
            "observations": [
                {
                    "id": s.span_id,
                    "traceId": trace.trace_id,
                    "parentObservationId": s.parent_id,
                    "type": "GENERATION" if s.span_type == "llm" else "SPAN",
                    "name": s.name,
                    "startTime": s.start_time,
                    "endTime": s.end_time or time.time(),
                    "input": s.input,
                    "output": s.output,
                    "metadata": s.metadata,
                    "level": "ERROR" if s.error else "DEFAULT",
                    "statusMessage": s.error,
                }
                for s in trace.spans
            ],
        }

    def flush(self) -> bool:
        """等待队列清空（有超时上限），返回是否已清空。"""
        if not self._enabled:
            return True
        deadline = time.time() + self.FLUSH_TIMEOUT_S
        while not self._queue.empty() and time.time() < deadline:
            time.sleep(0.05)
        return self._queue.empty()

    def shutdown(self) -> None:
        """停止后台上传线程（daemon，进程退出时也会自动回收）。"""
        self._closed = True
        if self._worker is not None:
            self._worker.join(timeout=3.0)


# ── 全局 Tracer ──


class Tracer:
    """全局追踪器 — 组装 Trace 并上报"""

    def __init__(self, backend: Optional[TracerBackend] = None):
        self.backend = backend or _resolve_backend()
        self._local = threading.local()

    def new_trace(self, name: str = "agent_analysis", **kwargs) -> TraceContext:
        trace_id = kwargs.pop("trace_id", uuid.uuid4().hex[:16])
        trace = TraceContext(trace_id=trace_id, name=name, **kwargs)
        self._local.current_trace = trace
        return trace

    @property
    def current_trace(self) -> Optional[TraceContext]:
        return getattr(self._local, "current_trace", None)

    def start_span(self, name: str, span_type: str = "tool",
                   input: Any = None, **kwargs) -> SpanContext:
        trace = self.current_trace
        if trace is None:
            trace = self.new_trace()
        span = SpanContext(
            span_id=uuid.uuid4().hex[:12],
            trace_id=trace.trace_id,
            span_type=span_type,
            name=name,
            input=input,
            **kwargs,
        )
        trace.add_span(span)
        self._local.current_span = span
        return span

    def end_span(self, span: SpanContext, output: Any = None,
                 error: Optional[str] = None):
        span.end_time = time.time()
        span.output = output
        span.error = error
        if self._local.current_span is span:
            self._local.current_span = None

    @contextmanager
    def span(self, name: str, span_type: str = "tool",
             input: Any = None, **kwargs):
        _span = self.start_span(name, span_type, input, **kwargs)
        try:
            yield _span
        except Exception as e:
            self.end_span(_span, error=str(e))
            raise
        else:
            self.end_span(_span)

    def finish_trace(self, error: Optional[str] = None):
        trace = self.current_trace
        if trace is None:
            return
        trace.end_time = time.time()
        trace.error = error
        self.backend.report_trace(trace)
        self._local.current_trace = None

    def flush(self):
        self.backend.flush()


# ── 工厂函数 ──


def _resolve_backend() -> TracerBackend:
    """根据环境变量自动选择后端"""
    mode = os.environ.get("TRACER_BACKEND", "auto")
    if mode == "null":
        return NullBackend()
    if mode == "file":
        return FileBackend()
    if mode == "langfuse":
        return LangfuseBackend()
    # auto: 有 Langfuse Key 就用，否则文件
    if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
        return LangfuseBackend()
    return FileBackend()


# ── 案例级 Trace 注册表 ──
# worker 线程池并发处理多个 case，threading.local 无法跨 graph 节点可靠传递，
# 故按 trace_id 显式注册/注销，graph 节点埋点通过 get_active_trace(trace_id) 取回。

_active_lock = threading.Lock()
_active_traces: "dict[str, TraceContext]" = {}


def begin_case_trace(trace_id: str, name: str = "refund_case_analysis",
                     metadata: Optional[dict] = None) -> TraceContext:
    """开启一条案件级 Trace（供 graph 节点埋点写入 span）。"""
    trace = TraceContext(trace_id=trace_id, name=name, metadata=metadata or {})
    with _active_lock:
        _active_traces[trace_id] = trace
    return trace


def get_active_trace(trace_id: str) -> Optional[TraceContext]:
    with _active_lock:
        return _active_traces.get(trace_id)


def end_case_trace(trace_id: str, error: Optional[str] = None) -> bool:
    """结束并上报案件级 Trace（FileBackend 落盘 / LangfuseBackend 异步入队）。"""
    with _active_lock:
        trace = _active_traces.pop(trace_id, None)
    if trace is None:
        return False
    trace.end_time = time.time()
    trace.error = error
    return tracer.backend.report_trace(trace)


# ── 全局单例 ──

tracer = Tracer()


__all__ = [
    "Tracer", "TraceContext", "SpanContext",
    "TracerBackend", "NullBackend", "FileBackend", "LangfuseBackend",
    "tracer",
    "begin_case_trace", "get_active_trace", "end_case_trace",
]
