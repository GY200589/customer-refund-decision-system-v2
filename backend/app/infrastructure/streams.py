import json
from datetime import datetime, timezone

import redis

from ..config import settings


def publish_case(client: redis.Redis, case_id: str, trace_id: str) -> str:
    """把案件投递到 Redis Stream，返回消息 ID。"""
    entry = {
        "case_id": case_id,
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    return client.xadd(settings.refund_stream, entry)


def ensure_group(client: redis.Redis) -> None:
    try:
        client.xgroup_create(
            settings.refund_stream, settings.refund_group, id="0", mkstream=True
        )
    except redis.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def move_to_dlq(client: redis.Redis, message_id: str, payload: dict) -> None:
    client.xadd(settings.refund_dlq, {**payload, "error": "exceeded retries"})
    client.xack(settings.refund_stream, settings.refund_group, message_id)


def publish_event(client: redis.Redis, case_id: str, event: dict) -> None:
    client.publish(f"case:{case_id}:events", json.dumps(event, ensure_ascii=False, default=str))
