from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    jwt_secret: str = "change-me-to-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    database_url: str = (
        "postgresql+psycopg://refund:refund_password@localhost:5432/refund_db"
    )
    redis_url: str = "redis://localhost:6379/0"

    # 数据库连接池（压测显示默认 pool_size=5/max_overflow=10 在 200 并发下雪崩；
    # 每个 uvicorn worker 的 anyio 线程池约 40 线程，故每 worker 连接池需 >40 以留余量）
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout: int = 10
    db_pool_recycle: int = 1800

    # 业务阈值（单位：分；可配置，不散落在代码中）
    amount_human_review_threshold_cent: int = 30000
    ocr_confidence_threshold: float = 0.80
    fraud_reject_threshold: int = 80
    fraud_review_threshold: int = 50

    # 用户长期退款率阈值（0~1 小数；不受金额大小影响，全局薅羊毛识别）
    refund_rate_review_threshold: float = 0.50
    refund_rate_reject_threshold: float = 0.80

    # 模型提供者：mock | paddle | ollama
    ocr_provider: str = "mock"
    llm_provider: str = "mock"
    risk_provider: str = "mock"
    sentiment_provider: str = "mock"
    refund_provider: str = "mock"

    # 合并风险提供者（优化改造）：mock | llm
    combined_risk_provider: str = "mock"

    # ── 用户端扩展（男装商城 + 智能客服）──
    # 语音识别提供者：mock（明确报不可用，不伪造转写）| dashscope（阿里云百炼）
    asr_provider: str = "mock"
    asr_model: str = "qwen3-asr-flash"
    asr_api_base: str = "https://dashscope.aliyuncs.com/api/v1"
    dashscope_api_key: str = ""  # 从环境变量 DASHSCOPE_API_KEY / .env 读取，不写入代码
    # 外部演示数据路径；Docker 通过只读 volume 注入，本地则自动查找项目目录。
    catalog_data_path: str = ""
    knowledge_base_path: str = ""

    # 知识库未命中后，由用户主动选择的大模型客服兜底。
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 20.0

    # 视觉分类提供者（男装图片识别，Phase 5）：mock | ollama_vl
    vision_provider: str = "mock"
    vision_model: str = "qwen2.5vl"
    vision_confidence_threshold: float = 0.75

    # ── 安全配置（工单6：零信任安全防护与 AI 治理）──
    critic_rule_enabled: bool = True
    critic_llm_enabled: bool = False
    critic_reject_on_high: bool = True
    critic_review_on_medium: bool = True

    dlp_enabled: bool = True
    dlp_sanitize_input: bool = True
    dlp_sanitize_output: bool = True
    dlp_mask_char: str = "*"

    tool_filter_enabled: bool = True
    tool_filter_amount_max: int = 10_000_000

    # ── 价格偏差阈值（订单真实性校验）──
    price_deviation_threshold_cent: int = 5000

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    paddleocr_lang: str = "ch"
    paddleocr_use_angle_cls: bool = False

    # 上传凭证时是否实时 OCR 预览（返回识别文本/置信度/字段，供前端回填表单）
    upload_ocr_preview: bool = True

    # OCR 结果缓存：upload 实时预览的结果写入 Redis，EvidenceAgent 异步流程直接复用
    ocr_cache_enabled: bool = True
    ocr_cache_ttl: int = 3600  # 秒

    # ── 沙箱配置 ──
    sandbox_mode: str = "off"  # on=真沙箱(Docker), off=宿主机直读
    sandbox_image: str = "sandbox-python:latest"

    # ── Langfuse 观测 ──
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # ── 评测配置 ──
    eval_enabled: bool = False

    # 工作流与队列
    refund_stream: str = "refund:stream"
    refund_group: str = "refund-group"
    refund_dlq: str = "refund:stream:dlq"

    # Worker 消费并发度：单线程串行 graph.invoke（约 2s/单）是消费吞吐瓶颈，
    # 压测时积压到 2w+ 条并抢占 postgres 连接导致 API 连接池超时。
    # 每个 case 相互独立、providers 为 mock 无状态、checkpointer 为 Redis（线程安全），
    # 故可安全并行消费。默认 4 对齐 worker 容器 4 CPU 上限。
    worker_concurrency: int = 4
    worker_batch_size: int = 8

    # SUSPENDED 超时自动升级：挂起超过该小时数未审批，worker 标记为已升级（escalated）
    suspended_escalate_hours: int = 24
    # 超时扫描频率（秒）；每轮循环约 2s（xreadgroup block），60s ≈ 每 30 轮扫一次
    suspended_escalate_scan_seconds: int = 60


settings = Settings()
