import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# All production routes live in the 沙箱 package.  Keep the import explicit so
# the API, worker-facing upload flow, dashboard stats, and trace endpoints are
# built from the same source tree.
from .api.沙箱 import admin, auth, batch, cases, customer, health, review_tasks, stats
from .container import Deps
from .db import init_db
from .infrastructure.redis_client import build_redis
from .models import _request_ip_ctx
from .seed import seed_defaults
from .workflow.checkpoint import build_checkpointer
from .workflow.graph import build_graph

access_logger = logging.getLogger("access")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_defaults()
    redis = build_redis()
    checkpointer = build_checkpointer(use_redis=True)
    deps = Deps(redis, checkpointer)
    graph = build_graph(deps)
    app.state.redis = redis
    app.state.deps = deps
    app.state.graph = graph
    yield


app = FastAPI(title="客诉舆情退赔决策系统", version="1.0.0", lifespan=lifespan)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(cases.router, prefix="/api/v1/cases", tags=["cases"])
app.include_router(customer.router, prefix="/api/v1/customer", tags=["customer"])
app.include_router(review_tasks.router, prefix="/api/v1/review-tasks", tags=["review"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(batch.router, prefix="/api/v1/batch", tags=["batch"])
app.include_router(stats.router, prefix="/api/v1/stats", tags=["stats"])


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    """结构化访问日志：记录 method/path/status/耗时/request_id，不落请求体。

    请求体可能包含身份证/手机号/支付凭证等敏感信息，故不记录；日志仅含无敏感字段。
    """
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    start = time.perf_counter()
    # 注入来源 IP 到上下文，供 AuditLog.ip_address 自动记录（审计留痕）
    token = _request_ip_ctx.set(request.client.host if request.client else None)
    try:
        response = await call_next(request)
    finally:
        _request_ip_ctx.reset(token)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    access_logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
            ensure_ascii=False,
        )
    )
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.status_code), "message": exc.detail}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL", "message": "服务器内部错误"}},
    )
