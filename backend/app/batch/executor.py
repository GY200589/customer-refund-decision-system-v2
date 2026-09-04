"""批量审批执行器

逐条调用 resume_workflow 唤醒挂起图，三层防重保障：
1. 幂等键（SHA256: actor_id:case_id:action）
2. Redis 分布式锁（SETNX, 10s TTL）
3. 状态前置校验（期待 SUSPENDED）

部分失败处理：某单已被他人处理/状态已变则跳过并记入汇总，不整体回滚。
"""
import hashlib
import logging
from typing import List

from app.batch.models import ApprovalRow, BatchApprovalResult
from app.container import Deps

logger = logging.getLogger(__name__)


def _idempotency_key(actor_id: str, case_id: str, action: str) -> str:
    """生成幂等键"""
    raw = f"{actor_id}:{case_id}:{action}"
    return "batch:" + hashlib.sha256(raw.encode()).hexdigest()


def execute_batch_approval(
    rows: List[ApprovalRow],
    deps: Deps,
    graph,
    operator: str,
    operator_id: int,
) -> BatchApprovalResult:
    """逐条执行批量审批

    Args:
        rows: 审批记录列表
        deps: 依赖容器
        operator: 操作人标识

    Returns:
        BatchApprovalResult: 汇总结果
    """
    result = BatchApprovalResult(
        total=len(rows),
        approved=0,
        rejected=0,
        failed=0,
        failures=[],
    )

    for row in rows:
        try:
            action_map = {"同意": "APPROVE", "拒绝": "REJECT"}
            action = action_map.get(row.action)
            if not action:
                result.failed += 1
                result.failures.append({"case_id": row.case_id, "error": f"无效动作: {row.action}"})
                continue

            # 1. 幂等键检查
            idem_key = _idempotency_key(operator, row.case_id, action)
            idem_result = _check_idempotency(deps, idem_key)
            if idem_result == "already_done":
                logger.info("跳过已处理单: %s", row.case_id)
                result.failed += 1
                result.failures.append({"case_id": row.case_id, "error": "已处理（幂等命中）"})
                continue

            # 2. 分布式锁
            lock_key = f"refund:approval:{row.case_id}"
            lock_token = _acquire_lock(deps, lock_key)
            if not lock_token:
                result.failed += 1
                result.failures.append({"case_id": row.case_id, "error": "该单正在被其他操作处理"})
                continue

            try:
                # 3. 状态前置校验
                current_status = deps.get_case_status(row.case_id)
                if current_status != "SUSPENDED":
                    logger.warning("状态已变更: %s 当前状态=%s", row.case_id, current_status)
                    result.failed += 1
                    result.failures.append({"case_id": row.case_id, "error": f"当前状态为 {current_status}，非挂起"})
                    continue

                # 4. 执行审批唤醒
                from langgraph.types import Command

                graph.invoke(
                    Command(resume={"action": action, "comment": row.comment, "operator": operator}),
                    config={"configurable": {"thread_id": row.case_id}},
                )
                deps.update_review_task(row.case_id, operator_id, action, row.comment)

                # 5. 记录幂等
                _record_idempotency(deps, idem_key)

                if action == "APPROVE":
                    result.approved += 1
                else:
                    result.rejected += 1
                logger.info("批量审批成功: %s → %s", row.case_id, action)

            finally:
                # 释放锁
                _release_lock(deps, lock_key, lock_token)

        except Exception as e:
            logger.error("批量审批失败: %s, error=%s", row.case_id, e)
            result.failed += 1
            result.failures.append({"case_id": row.case_id, "error": str(e)})

    logger.info(
        "批量审批完成: 总 %d, 批准 %d, 拒绝 %d, 失败 %d",
        result.total, result.approved, result.rejected, result.failed,
    )
    return result


def _check_idempotency(deps: Deps, key: str) -> str:
    """检查幂等键"""
    from app.models import IdempotencyRecord
    with deps.session() as db:
        record = db.query(IdempotencyRecord).filter(IdempotencyRecord.key == key).first()
        if record:
            return "already_done"
    return "new"


def _record_idempotency(deps: Deps, key: str) -> None:
    """记录幂等键"""
    from app.models import IdempotencyRecord
    with deps.session() as db:
        db.add(IdempotencyRecord(key=key, request_hash="batch_approval", response_body="ok", status_code=200))
        db.commit()


def _acquire_lock(deps: Deps, key: str, ttl_ms: int = 10_000):
    """获取 Redis 分布式锁"""
    from app.services.locks import acquire_lock
    return acquire_lock(deps.redis, key, ttl_ms)


def _release_lock(deps: Deps, key: str, token: str) -> None:
    """释放 Redis 分布式锁"""
    from app.services.locks import release_lock
    release_lock(deps.redis, key, token)
