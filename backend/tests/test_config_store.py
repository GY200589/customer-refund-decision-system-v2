from app.config import settings
from app.db import SessionLocal
from app.models import SystemConfig
from app.services import config_store


def test_defaults_when_empty(db_setup):
    with SessionLocal() as db:
        db.query(SystemConfig).delete()
        db.commit()
        th = config_store.get_thresholds(db)
    assert th["amount_human_review_threshold_cent"] == settings.amount_human_review_threshold_cent
    assert th["ocr_confidence_threshold"] == settings.ocr_confidence_threshold


def test_set_then_get_override(db_setup):
    with SessionLocal() as db:
        db.query(SystemConfig).delete()
        db.commit()
        after = config_store.set_thresholds(db, {"amount_human_review_threshold_cent": 50000}, actor_id=1)
        assert after["amount_human_review_threshold_cent"] == 50000
        # 未覆盖的键保持默认
        assert after["fraud_reject_threshold"] == settings.fraud_reject_threshold


def test_dirty_value_falls_back_to_default(db_setup):
    with SessionLocal() as db:
        db.query(SystemConfig).delete()
        db.add(SystemConfig(key="amount_human_review_threshold_cent", value="not-json"))
        db.commit()
        th = config_store.get_thresholds(db)
    assert th["amount_human_review_threshold_cent"] == settings.amount_human_review_threshold_cent
