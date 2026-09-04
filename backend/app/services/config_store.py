"""运行时阈值配置：从 `system_config` 表读取，缺失回退到环境变量默认值。

阈值在决策时实时读取（无进程内缓存），因此管理员通过 API 修改后，Worker 的下一次
决策立即生效，无需重启。
"""
import json

from ..config import settings
from ..models import SystemConfig

# 可被运行时覆盖的业务阈值键 -> 环境变量默认值来源
THRESHOLD_KEYS = (
    "amount_human_review_threshold_cent",
    "ocr_confidence_threshold",
    "fraud_reject_threshold",
    "fraud_review_threshold",
    "tool_filter_amount_max",
    "critic_rule_enabled",
    "critic_llm_enabled",
    "dlp_enabled",
    "price_deviation_threshold_cent",
    "refund_rate_review_threshold",
    "refund_rate_reject_threshold",
)


def _defaults() -> dict:
    return {
        "amount_human_review_threshold_cent": settings.amount_human_review_threshold_cent,
        "ocr_confidence_threshold": settings.ocr_confidence_threshold,
        "fraud_reject_threshold": settings.fraud_reject_threshold,
        "fraud_review_threshold": settings.fraud_review_threshold,
        "tool_filter_amount_max": settings.tool_filter_amount_max,
        "critic_rule_enabled": settings.critic_rule_enabled,
        "critic_llm_enabled": settings.critic_llm_enabled,
        "dlp_enabled": settings.dlp_enabled,
        "price_deviation_threshold_cent": settings.price_deviation_threshold_cent,
        "refund_rate_review_threshold": settings.refund_rate_review_threshold,
        "refund_rate_reject_threshold": settings.refund_rate_reject_threshold,
    }


def get_thresholds(db) -> dict:
    """返回当前生效的全部阈值（DB 覆盖值优先，缺失回退默认）。"""
    result = _defaults()
    rows = db.query(SystemConfig).filter(SystemConfig.key.in_(THRESHOLD_KEYS)).all()
    for row in rows:
        try:
            result[row.key] = json.loads(row.value)
        except (TypeError, ValueError):
            continue  # 脏数据回退默认值
    return result


def set_thresholds(db, updates: dict, actor_id: int | None) -> dict:
    """持久化一组阈值覆盖值，返回写入后的完整阈值。"""
    for key, value in updates.items():
        row = db.get(SystemConfig, key)
        if row is None:
            db.add(SystemConfig(key=key, value=json.dumps(value), updated_by=actor_id))
        else:
            row.value = json.dumps(value)
            row.updated_by = actor_id
    db.commit()
    return get_thresholds(db)
