import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import Base

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_schema() -> None:
    """轻量增量迁移：create_all 只创建新表，不会给已有表加列。

    用户端扩展（定稿 §5.2 / C2）在 refund_cases 上新增了 source 等列，
    这里对旧库显式补齐；新库上 create_all 已建列，以下语句均为幂等 no-op。
    """
    stmts = [
        "ALTER TABLE refund_cases ADD COLUMN IF NOT EXISTS source VARCHAR(32) DEFAULT 'agent_console'",
        "ALTER TABLE refund_cases ADD COLUMN IF NOT EXISTS product_id INTEGER",
        "ALTER TABLE refund_cases ADD COLUMN IF NOT EXISTS product_name VARCHAR(128)",
        "ALTER TABLE refund_cases ADD COLUMN IF NOT EXISTS product_sub_category VARCHAR(32)",
        "ALTER TABLE refund_cases ADD COLUMN IF NOT EXISTS order_item_id INTEGER",
        "CREATE INDEX IF NOT EXISTS ix_refund_cases_source ON refund_cases (source)",
        "CREATE INDEX IF NOT EXISTS ix_refund_cases_order_item ON refund_cases (order_item_id)",
    ]
    with engine.connect() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))
        conn.commit()


def init_db() -> None:
    # 多 uvicorn worker 并发启动时，create_all 的 check-then-create 存在竞态：
    # 各 worker 同时判定「表/枚举类型不存在」并一起 CREATE，偶发 UniqueViolation
    # （pg_type_typname_nsp_index / pg_class_relname_nsp_index）。重试即可自愈。
    last_exc = None
    for attempt in range(1, 6):
        try:
            Base.metadata.create_all(bind=engine)
            _migrate_schema()
            return
        except IntegrityError as exc:
            last_exc = exc
            time.sleep(1)
    raise last_exc
