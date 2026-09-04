import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..container import Deps
from ..db import SessionLocal, init_db
from ..infrastructure import streams
from ..infrastructure.redis_client import build_redis
from ..models import AuditLog, CaseEvidence, RefundCase
from ..seed import seed_defaults
from ..telemetry import begin_case_trace, end_case_trace
from ..workflow.checkpoint import build_checkpointer
from ..workflow.graph import build_graph

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("worker")

TERMINAL = ("COMPLETED", "REJECTED", "FAILED")


def _load_evidence(db, case_id: str) -> list:
    rows = db.query(CaseEvidence).filter(CaseEvidence.case_id == case_id).all()
    return [
        {
            "file_name": r.file_name,
            "file_hash": r.file_hash,
            "file_path": r.file_path,
        }
        for r in rows
    ]


def _process(redis, deps, graph, payload: dict) -> None:
    case_id = payload.get("case_id")
    if not case_id:
        return
    with SessionLocal() as db:
        case = db.query(RefundCase).filter(RefundCase.case_id == case_id).first()
        if case is None:
            return
        if case.status in TERMINAL or case.status == "SUSPENDED":
            return
        state = {
            "case_id": case.case_id,
            "trace_id": case.trace_id,
            "user_id": case.user_id,
            "order_id": case.order_id,
            "amount_cent": case.amount_cent,
            "complaint_text": case.complaint_text or "",
            "risk_flags": case.risk_flags or {},
            "evidence": _load_evidence(db, case_id),
        }

    # 先把 CREATED 锁定为 RUNNING，避免同一案件被重复消费时并行执行。
    if deps.get_case_status(case_id) == "CREATED":
        deps.transition(case_id, "CREATED", "RUNNING")

    config = {"configurable": {"thread_id": case_id}}
    # 开启案件级 Trace：graph 各节点经 _traced 埋点写入 span，结束时统一上报
    # （FileBackend 落盘 / LangfuseBackend 异步入队，interrupt 挂起也会落已完成的 span）
    begin_case_trace(
        case.trace_id,
        name="refund_case_analysis",
        metadata={"case_id": case_id, "order_id": case.order_id, "amount_cent": case.amount_cent},
    )
    try:
        result = graph.invoke(state, config)
    finally:
        end_case_trace(case.trace_id)
    if "__interrupt__" in result:
        logger.info("case %s suspended for human review", case_id)
    else:
        logger.info("case %s done, decision=%s", case_id, result.get("decision"))


def _process_safe(redis, deps, graph, msg_id, payload: dict) -> bool:
    """并发线程内处理单条消息：成功返回 True，异常落 DLQ 并返回 False。

    每个 case 相互独立、mock providers 无状态、checkpointer 为 Redis（线程安全），
    故可安全地由 ThreadPoolExecutor 并发消费。ACK 由主循环统一执行。
    """
    try:
        _process(redis, deps, graph, payload)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("process %s failed: %s", msg_id, exc)
        streams.move_to_dlq(redis, msg_id, payload)
        return False


HEARTBEAT_KEY = "worker:heartbeat"
HEARTBEAT_TTL = 15  # 秒；健康检查在 15s 内读到新鲜心跳即视为存活


def _escalate_stale_suspended(db) -> int:
    """将挂起超过阈值的 SUSPENDED 案件标记升级（幂等，每案仅一次）。

    不动状态机（仍保持 SUSPENDED 等待审批），仅写入 risk_flags.escalated
    与审计记录，供前端展示「已等待 XX 小时 / 已升级」及管理层追踪。
    """
    thr_hours = settings.suspended_escalate_hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=thr_hours)
    cases = (
        db.query(RefundCase)
        .filter(RefundCase.status == "SUSPENDED", RefundCase.updated_at < cutoff)
        .all()
    )
    escalated = 0
    for case in cases:
        flags = dict(case.risk_flags or {})
        if flags.get("escalated"):
            continue
        flags["escalated"] = True
        flags["escalated_at"] = datetime.now(timezone.utc).isoformat()
        case.risk_flags = flags
        db.add(
            AuditLog(
                case_id=case.case_id,
                actor_id=None,
                action="case:escalated",
                before_value={"status": "SUSPENDED"},
                after_value={
                    "reason": f"SUSPENDED 超过 {thr_hours} 小时未审批，自动升级",
                    "escalated_hours": thr_hours,
                },
            )
        )
        escalated += 1
    if escalated:
        db.commit()
        logger.info("escalated %d stale SUSPENDED case(s) (>%dh)", escalated, thr_hours)
    return escalated


def _maybe_escalate_scan() -> None:
    """低频扫描 SUSPENDED 超时案件（独立会话，失败不影响主消费循环）。"""
    try:
        with SessionLocal() as db:
            _escalate_stale_suspended(db)
    except Exception:  # noqa: BLE001
        logger.exception("escalate scan failed")


def run_worker() -> None:
    init_db()
    seed_defaults()
    redis = build_redis()
    streams.ensure_group(redis)
    deps = Deps(redis, build_checkpointer(use_redis=True))
    graph = build_graph(deps)
    logger.info(
        "worker started, consuming %s (concurrency=%d, batch=%d)",
        settings.refund_stream,
        settings.worker_concurrency,
        settings.worker_batch_size,
    )

    with ThreadPoolExecutor(max_workers=settings.worker_concurrency, thread_name_prefix="case") as pool:
        last_escalate_scan = 0.0
        while True:
            # 低频扫描：SUSPENDED 超时自动升级（按配置间隔执行）
            if time.time() - last_escalate_scan >= settings.suspended_escalate_scan_seconds:
                last_escalate_scan = time.time()
                _maybe_escalate_scan()
            # 心跳：每次循环（含空闲阻塞）都刷新，供容器 HEALTHCHECK 探测消费进程存活。
            # 若 xreadgroup 长期阻塞或进程被挂起，心跳过期后健康检查会判定为不健康并重启容器。
            try:
                redis.set(HEARTBEAT_KEY, time.time(), ex=HEARTBEAT_TTL)
            except Exception:  # noqa: BLE001  心跳失败不应阻断主循环
                logger.warning("heartbeat write failed", exc_info=True)
            try:
                messages = redis.xreadgroup(
                    settings.refund_group,
                    "refund-worker",
                    {settings.refund_stream: ">"},
                    count=settings.worker_batch_size,
                    block=2000,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("xreadgroup failed: %s", exc)
                time.sleep(2)
                continue

            futures = {}
            for _stream, entries in messages:
                for msg_id, payload in entries:
                    futures[pool.submit(_process_safe, redis, deps, graph, msg_id, payload)] = msg_id

            # 等待本批全部完成（线程池内并发），再统一 ACK；心跳间隔 <= 批耗时，
            # 批大小默认 8、并发 4，最长约 2*单案耗时，远小于心跳 TTL 15s。
            for fut in futures:
                msg_id = futures[fut]
                try:
                    if fut.result():
                        redis.xack(settings.refund_stream, settings.refund_group, msg_id)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("ack %s failed: %s", msg_id, exc)


if __name__ == "__main__":
    run_worker()
