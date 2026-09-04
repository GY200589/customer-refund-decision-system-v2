import logging
import time

from langgraph.checkpoint.memory import MemorySaver

from ..config import settings

logger = logging.getLogger(__name__)

# Redis 冷启动（redis-stack 加载 RedisJSON/RediSearch 模块与数据集）期间，
# redis-cli ping 已返回 PONG（健康检查通过），但 FT.CREATE / JSON 命令仍会抛
# BusyLoadingError。此时 RedisSaver.setup() 建索引会失败，需重试几次。
_REDIS_RETRY_ATTEMPTS = 10
_REDIS_RETRY_BACKOFF_SECONDS = 2.0


def build_checkpointer(use_redis: bool = True):
    """优先使用 Redis 持久化 checkpoint；仅 test 环境允许回退内存。

    注意：langgraph-checkpoint-redis 的 `from_conn_string` 返回的是同步上下文管理器，
    且 `__init__` 不会创建 RediSearch 索引。需直接 `RedisSaver(redis_url=...)` 后调用
    `setup()` 来初始化索引（依赖 redis-stack 的 RedisJSON/RediSearch 模块）。

    生产环境若 Redis 不可用，直接抛错交由容器重启重试，绝不静默回退内存——
    否则 API 与 worker 的 checkpoint 存储不一致（worker 写 Redis、API 用内存），
    人工审批 resume 会因找不到 checkpoint 而从 intake 节点重新执行，报 KeyError。
    """
    if not use_redis or settings.app_env == "test":
        return MemorySaver()

    redis_saver_cls = None
    for module in ("langgraph.checkpoint.redis", "langgraph_checkpoint_redis"):
        try:
            mod = __import__(module, fromlist=["RedisSaver"])
            redis_saver_cls = mod.RedisSaver
            break
        except Exception:  # noqa: BLE001
            continue

    if redis_saver_cls is None:
        if settings.app_env == "test":
            return MemorySaver()
        raise RuntimeError("未安装 langgraph-checkpoint-redis，且非 test 环境，拒绝回退内存")

    last_exc = None
    for attempt in range(1, _REDIS_RETRY_ATTEMPTS + 1):
        try:
            saver = redis_saver_cls(redis_url=settings.redis_url)
            saver.setup()
            logger.info("Redis checkpointer ready (attempt=%d)", attempt)
            return saver
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Redis checkpointer init failed (attempt=%d/%d): %s",
                attempt,
                _REDIS_RETRY_ATTEMPTS,
                exc,
            )
            time.sleep(_REDIS_RETRY_BACKOFF_SECONDS)

    if settings.app_env == "test":
        logger.warning("Redis checkpointer unavailable, falling back to MemorySaver (test env)")
        return MemorySaver()

    raise RuntimeError(
        f"Redis checkpointer unavailable after {_REDIS_RETRY_ATTEMPTS} attempts: {last_exc}"
    )
