"""客服能力自动评测 runner（定稿 §4.9）。

在服务层直接调用意图识别 / 知识检索 / 动作路由（与线上 /customer/assistant
同一条代码路径），不经过 HTTP，保证评测口径与真实行为一致。
报告 JSON 落在 eval/reports/，供 Admin「智能客服评测」页面展示。
"""
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from ..db import SessionLocal
from ..models import User
from ..services import rag as rag_svc
from ..services.assistant import route_action
from ..services.intent import INTENT_KEYWORDS, recognize
from .assistant_dataset import load_assistant_dataset

REPORTS_DIR = Path(__file__).parent / "reports"


def _aggregate(per_intent_raw: dict[str, dict]) -> dict:
    tp = sum(s["tp"] for s in per_intent_raw.values())
    fp = sum(s["fp"] for s in per_intent_raw.values())
    fn = sum(s["fn"] for s in per_intent_raw.values())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def run_eval() -> dict:
    samples = load_assistant_dataset()
    predicted: list[dict] = []
    errors: list[dict] = []
    latencies: list[float] = []

    with SessionLocal() as db:
        # 动作路由按 customer1 语境评测（订单/退款数据即种子预置的演示数据）
        customer = db.query(User).filter(User.username == "customer1").first()

        for sample in samples:
            start = time.perf_counter()
            rec = recognize(sample["query"])
            retrieved = rag_svc.retrieve_knowledge(db, sample["query"])
            action = route_action(rec["intents"][0] if rec["intents"] else "other")
            latencies.append((time.perf_counter() - start) * 1000)
            pred = {
                "intents": rec["intents"],
                "entities": rec["entities"],
                "confidence": rec["confidence"],
                "retrieved_doc_keys": [h["doc_key"] for h in retrieved],
                "action": action,
            }
            predicted.append(pred)

            # 错误样本：意图集合不一致 / 实体缺失 / 检索未命中 / 动作不符，任一即记录
            failed = False
            if "expected_intents" in sample and set(pred["intents"]) != set(sample["expected_intents"]):
                failed = True
            if "expected_entities" in sample and not all(
                pred["entities"].get(k) == v for k, v in sample["expected_entities"].items()
            ):
                failed = True
            if "expected_sources" in sample and not (
                set(sample["expected_sources"]) & set(pred["retrieved_doc_keys"])
            ):
                failed = True
            if "expected_action" in sample and pred["action"] != sample["expected_action"]:
                failed = True
            if failed:
                errors.append({
                    "id": sample["id"],
                    "query": sample["query"],
                    "input_source": sample.get("input_source", "text"),
                    "expected_intents": sample.get("expected_intents"),
                    "predicted_intents": pred["intents"],
                    "expected_entities": sample.get("expected_entities"),
                    "predicted_entities": pred["entities"],
                    "expected_sources": sample.get("expected_sources"),
                    "retrieved_doc_keys": pred["retrieved_doc_keys"],
                    "expected_action": sample.get("expected_action"),
                    "predicted_action": pred["action"],
                })

    # 意图指标（仅有 expected_intents 的样本参与）
    intent_samples = [(s, p) for s, p in zip(samples, predicted) if "expected_intents" in s]
    per_intent_raw: dict[str, dict] = {}
    for intent in set(INTENT_KEYWORDS.keys()) | {"other"}:
        per_intent_raw[intent] = {"tp": 0, "fp": 0, "fn": 0}
    for sample, pred in intent_samples:
        expected, got = set(sample["expected_intents"]), set(pred["intents"])
        for i in expected & got:
            per_intent_raw[i]["tp"] += 1
        for i in got - expected:
            per_intent_raw[i]["fp"] += 1
        for i in expected - got:
            per_intent_raw[i]["fn"] += 1

    micro = _aggregate(per_intent_raw)
    per_intent: dict[str, dict] = {}
    f1_list = []
    for intent, s in per_intent_raw.items():
        precision = s["tp"] / (s["tp"] + s["fp"]) if (s["tp"] + s["fp"]) else 0.0
        recall = s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_intent[intent] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": s["tp"] + s["fn"],
        }
        if s["tp"] + s["fn"]:  # 只对出现过的意图求 macro 平均
            f1_list.append(f1)
    macro_f1 = round(statistics.mean(f1_list), 3) if f1_list else 0.0

    exact_hits = sum(
        1
        for sample, pred in intent_samples
        if set(sample["expected_intents"]) == set(pred["intents"])
    )

    # 实体 / 检索 / 动作指标
    entity_samples = [(s, p) for s, p in zip(samples, predicted) if s.get("expected_entities")]
    entity_hits = sum(
        1
        for sample, pred in entity_samples
        if all(pred["entities"].get(k) == v for k, v in sample["expected_entities"].items())
    )
    rag_samples = [(s, p) for s, p in zip(samples, predicted) if s.get("expected_sources")]
    retrieval_hits = sum(
        1
        for sample, pred in rag_samples
        if set(sample["expected_sources"]) & set(pred["retrieved_doc_keys"])
    )
    citation_covered = sum(1 for _, pred in rag_samples if pred["retrieved_doc_keys"])
    unsupported = sum(1 for _, pred in rag_samples if not pred["retrieved_doc_keys"])
    action_samples = [(s, p) for s, p in zip(samples, predicted) if s.get("expected_action")]
    action_hits = sum(1 for sample, pred in action_samples if pred["action"] == sample["expected_action"])

    # 语音 vs 文字：意图 Micro-F1 对比
    def _micro_for(source: str) -> dict:
        rows = [(s, p) for s, p in intent_samples if s.get("input_source", "text") == source]
        raw = {i: {"tp": 0, "fp": 0, "fn": 0} for i in per_intent_raw}
        for sample, pred in rows:
            expected, got = set(sample["expected_intents"]), set(pred["intents"])
            for i in expected & got:
                raw[i]["tp"] += 1
            for i in got - expected:
                raw[i]["fp"] += 1
            for i in expected - got:
                raw[i]["fn"] += 1
        return {"n": len(rows), **_aggregate(raw)}

    report_id = f"assistant_eval_{int(datetime.now(timezone.utc).timestamp())}"
    report = {
        "report_id": report_id,
        "kind": "assistant",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total": len(samples),
        "metrics": {
            "intent_micro_f1": micro["f1"],
            "intent_macro_f1": macro_f1,
            "multi_intent_exact_rate": round(exact_hits / len(intent_samples), 3) if intent_samples else None,
            "entity_accuracy": round(entity_hits / len(entity_samples), 3) if entity_samples else None,
            "rag_retrieval_hit_rate": round(retrieval_hits / len(rag_samples), 3) if rag_samples else None,
            "citation_coverage": round(citation_covered / len(rag_samples), 3) if rag_samples else None,
            "unsupported_answer_rate": round(unsupported / len(rag_samples), 3) if rag_samples else None,
            "action_accuracy": round(action_hits / len(action_samples), 3) if action_samples else None,
            "avg_latency_ms": round(statistics.mean(latencies), 1),
            "voice_vs_text": {
                "text": _micro_for("text"),
                "voice": _micro_for("voice"),
            },
        },
        "per_intent": per_intent,
        "sample_counts": {
            "intent": len(intent_samples),
            "entity": len(entity_samples),
            "rag": len(rag_samples),
            "action": len(action_samples),
        },
        "errors": errors,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{report_id}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def list_reports() -> list[dict]:
    if not REPORTS_DIR.exists():
        return []
    items = []
    for path in sorted(REPORTS_DIR.glob("assistant_eval_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append({
            "report_id": data.get("report_id", path.stem),
            "created_at": data.get("created_at"),
            "total": data.get("total"),
            "metrics": data.get("metrics"),
        })
    return items


def load_report(report_id: str) -> dict | None:
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    print(json.dumps(run_eval()["metrics"], ensure_ascii=False, indent=2))
