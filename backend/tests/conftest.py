"""pytest 全局配置：测试环境隔离。

本地测试必须与运行中的 Docker 开发栈（refund_db / redis db0）隔离，否则会出现两类问题：
1. `drop_all` 会直接破坏正在运行的 API/Worker 的表结构；
2. Worker 会消费测试投递到共享 Stream 的消息，与测试内同步状态流转产生竞争（flaky）。

因此这里在导入任何 `app.*` 模块之前，先把 `DATABASE_URL` / `REDIS_URL` 指向独立的
测试库（`refund_test_db`）与 Redis 命名空间（db 15）。开发者可用 `TEST_DATABASE_URL` /
`TEST_REDIS_URL` 覆盖默认值。
"""
import os

os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://refund:refund_password@localhost:5432/refund_test_db",
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.infrastructure.redis_client import build_redis  # noqa: E402
from app.models import Base, SystemConfig  # noqa: E402
from app.seed import seed_defaults  # noqa: E402

TEST_DB_NAME = "refund_test_db"


def _ensure_test_db() -> None:
    """若测试库不存在则创建（连到默认 postgres 库，AUTOCOMMIT 执行 CREATE DATABASE）。"""
    db_url = os.environ["DATABASE_URL"]
    admin_url = db_url.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session")
def db_setup():
    _ensure_test_db()
    Base.metadata.drop_all(bind=engine)
    init_db()
    seed_defaults()
    # 清空测试 Redis 命名空间，避免上一轮残留的 checkpoint / stream / 幂等键
    build_redis().flushdb()
    yield


@pytest.fixture(autouse=True)
def _reset_runtime_config():
    """每个测试前清空运行时配置（system_config），避免阈值等全局状态跨用例泄漏。

    纯单元测试不依赖数据库，故此处用 try/except 容错：无数据库时静默跳过，
    不影响纯单元测试的独立性。
    """
    try:
        with SessionLocal() as db:
            db.query(SystemConfig).delete()
            db.commit()
    except Exception:  # noqa: BLE001  数据库不可用时跳过
        pass
    yield
