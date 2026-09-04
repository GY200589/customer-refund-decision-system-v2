"""健康检查：探测数据库与 Redis 连通性，供 Docker 健康检查与管理员监控使用。"""
import time

from fastapi import APIRouter, Request
from sqlalchemy import text

from ...db import engine

router = APIRouter()


def _check_database() -> dict:
    start = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": type(exc).__name__}


def _check_redis(request: Request) -> dict:
    start = time.perf_counter()
    try:
        request.app.state.redis.ping()
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": type(exc).__name__}


@router.get("/health")
def health(request: Request):
    checks = {
        "database": _check_database(),
        "redis": _check_redis(request),
    }
    ok = all(c["status"] == "ok" for c in checks.values())
    return {
        "status": "ok" if ok else "degraded",
        "version": "1.0.0",
        "checks": checks,
    }
