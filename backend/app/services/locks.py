import uuid

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def acquire_lock(redis, key: str, ttl_ms: int = 10000):
    token = uuid.uuid4().hex
    ok = redis.set(key, token, nx=True, px=ttl_ms)
    return token if ok else None


def release_lock(redis, key: str, token: str) -> None:
    # Lua 脚本校验 token，避免误删其他请求的锁
    redis.eval(_RELEASE_SCRIPT, 1, key, token)
