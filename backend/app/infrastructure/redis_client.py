import redis

from ..config import settings


def build_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def build_raw_redis() -> redis.Redis:
    """用于需要字节串的场合（如 LangGraph RedisSaver 之外的 raw 操作）。"""
    return redis.Redis.from_url(settings.redis_url)
