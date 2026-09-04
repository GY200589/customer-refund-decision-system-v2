import hashlib
import json


def compute_request_hash(body: dict) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def approval_key(actor_id: int, case_id: str, action: str, idempotency_key: str) -> str:
    """防资损幂等键公式：hash(actor_id + case_id + action + idempotency_key)。"""
    raw = f"{actor_id}:{case_id}:{action}:{idempotency_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_key(user_id: int, idempotency_key: str) -> str:
    """建案幂等键：hash(user_id + idempotency_key)，隔离不同用户的重放请求。"""
    raw = f"{user_id}:{idempotency_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
