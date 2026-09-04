import contextvars
import uuid
from datetime import datetime, timezone
from typing import Optional

# 当前请求来源 IP 的上下文（HTTP 中间件注入；worker/异步任务内为 None）
_request_ip_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_ip", default=None
)


def _current_request_ip() -> Optional[str]:
    """SQLAlchemy 列默认值：审计日志自动记录当前 HTTP 请求来源 IP。

    worker/Agent 内部写审计时无请求上下文，返回 None（来源为系统自身）。
    """
    return _request_ip_ctx.get()

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # agent/supervisor/admin
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # 用户长期退款画像（反薅羊毛）
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    refund_count: Mapped[int] = mapped_column(Integer, default=0)
    reject_count: Mapped[int] = mapped_column(Integer, default=0)
    refund_rate: Mapped[float] = mapped_column(Float, default=0.0)


class RefundCase(Base):
    __tablename__ = "refund_cases"
    # 客服列表页按 (user_id, created_at) 倒序分页查询，复合索引避免全表扫描 + 排序；
    # status 单独索引供按状态筛选（如 review-tasks 派单）。
    __table_args__ = (
        Index("ix_refund_cases_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED", index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    decision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    fraud_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sentiment_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), default=_uuid)
    complaint_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_flags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refund_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    refund_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ocr_corrected: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=False)

    # 订单真实性校验
    is_verified_order: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    order_verify_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_order_amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 商品一致性校验
    product_match: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    claimed_product: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    purchased_product: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    product_consistency_risk: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # 决策时刻用户退款率快照（反薅羊毛审计依据）
    refund_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── 用户端退款扩展 ──
    # 案件来源：agent_console=客服后台建案 / customer_portal=用户端发起 / batch=批量导入
    source: Mapped[str] = mapped_column(String(32), default="agent_console", index=True)
    # 用户端案件携带的商品信息（客服详情页展示；商品一致性校验的结构化输入）
    product_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    product_sub_category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # 部分退款记账：关联 shop_order_items.id；整单退款为 NULL
    order_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Product(Base):
    """男装商品主数据。分类以人工标签为准；vision_check 仅记录视觉模型的
    识别结果与待复核标记，低置信度永不自动覆盖主分类（定稿 §4.3）。"""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # main_category: top=上装 / bottom=下装；sub_category 见分类树（tshirt/jeans/...）
    main_category: Mapped[str] = mapped_column(String(16), nullable=False)
    sub_category: Mapped[str] = mapped_column(String(32), nullable=False)
    gender: Mapped[str] = mapped_column(String(8), default="men")
    color: Mapped[str] = mapped_column(String(32), default="黑色")
    sizes: Mapped[list] = mapped_column(JSON, default=list)  # ["S","M","L"] 或 ["29","30"]
    price_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 真实图片到位后回填
    fabric: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    fit_notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)  # 演示商品标记（无真实图片期间）
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 视觉模型识别记录：{provider, confidence, needs_review, checked_at}
    vision_check: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ShopOrder(Base):
    """模拟购物订单（不接真实支付；金额服务端按 Product.price_cent 重算）。"""

    __tablename__ = "shop_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="COMPLETED")  # 模拟支付即时完成
    total_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    remark: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class ShopOrderItem(Base):
    __tablename__ = "shop_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_orders.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    sub_category: Mapped[str] = mapped_column(String(32), nullable=False)
    size: Mapped[str] = mapped_column(String(16), nullable=False)
    color: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cent: Mapped[int] = mapped_column(Integer, nullable=False)  # 下单时价格快照


class KnowledgeDocument(Base):
    """客服知识库条目（RAG 检索来源；version 用于回答引用，如"售后规则 v1"）。"""

    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # refund_policy/size_guide/...
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(16), default="v1")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class AssistantMessage(Base):
    """智能客服会话记录：意图、实体、检索来源与回答，供复盘与自动评测。"""

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    input_source: Mapped[str] = mapped_column(String(8), default="text")  # text / voice
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    intents: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    entities: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    retrieved: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # 命中的知识/商品/订单来源
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # create_refund/query_order/...
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CaseEvidence(Base):
    __tablename__ = "case_evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("refund_cases.case_id"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ocr_corrected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ocr_corrected_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("refund_cases.case_id"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    input_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("refund_cases.case_id"), nullable=False, index=True
    )
    fraud_score: Mapped[int] = mapped_column(Integer, default=0)
    sentiment_score: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    risk_factors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    rule_version: Mapped[str] = mapped_column(String(32), default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("refund_cases.case_id"), nullable=False, index=True
    )
    assigned_to: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    before_value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default=_current_request_ip)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SystemConfig(Base):
    """运行时系统配置（如业务阈值），键值对 + JSON 编码的值。

    业务阈值默认来自环境变量（`settings`），管理员可在运行期覆盖；覆盖值写入本表，
    决策时优先读取本表，缺失时回退到环境变量默认值。
    """

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON 编码
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
