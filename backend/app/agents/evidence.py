"""OCR evidence extraction and consistency checks."""

import logging

logger = logging.getLogger(__name__)


def _amount_cent(fields: dict) -> int | None:
    if fields.get("amount_cent") is not None:
        try:
            return int(fields["amount_cent"])
        except (TypeError, ValueError):
            return None
    if fields.get("amount") is not None:
        try:
            return round(float(fields["amount"]) * 100)
        except (TypeError, ValueError):
            return None
    return None


def run(state, deps):
    """提取多份凭证，并核对 OCR 金额、订单号与本次申请是否一致。"""
    case_id = state["case_id"]
    evidence = state.get("evidence") or []
    amount = state["amount_cent"]
    order_id = str(state.get("order_id") or "").upper()

    if not evidence:
        deps.record_agent_run(case_id, "EvidenceAgent", "SUCCESS", output_summary="无凭证")
        deps.publish_event(case_id, {"agent": "EvidenceAgent", "status": "done", "evidence_present": False})
        return {"evidence_present": False, "ocr_text": "", "ocr_confidence": None}

    all_ocr_texts = []
    all_confidences = []
    detected_amounts: list[int] = []
    detected_orders: list[str] = []
    errors = []

    for ev in evidence:
        file_name = ev.get("file_name", "")
        file_path = ev.get("file_path")
        file_hash = ev.get("file_hash")
        try:
            ocr = deps.ocr.extract(file_name, file_path, file_hash, amount)
            deps.update_evidence(case_id, file_name, ocr.text, ocr.overall_confidence)
            if ocr.text:
                all_ocr_texts.append(ocr.text)
            if ocr.overall_confidence is not None:
                all_confidences.append(ocr.overall_confidence)
            extracted_amount = _amount_cent(ocr.fields or {})
            if extracted_amount is not None:
                detected_amounts.append(extracted_amount)
            extracted_order = (ocr.fields or {}).get("order_id")
            if extracted_order:
                detected_orders.append(str(extracted_order).upper())
        except Exception as exc:  # noqa: BLE001  OCR 超时/不可用 -> 安全降级
            deps.update_evidence(case_id, file_name, "", None)
            errors.append(f"{file_name}: {exc}")
            logger.warning("EvidenceAgent OCR 失败 %s: %s", file_name, exc)

    flags = dict(state.get("risk_flags") or {})
    amount_tolerance = max(100, int(amount * 0.05))
    amount_match = (
        all(abs(value - amount) <= amount_tolerance for value in detected_amounts)
        if detected_amounts
        else None
    )
    order_match = all(value == order_id for value in detected_orders) if detected_orders else None
    flags.update(
        {
            "ocr_detected_amounts_cent": detected_amounts,
            "ocr_amount_match": amount_match,
            "ocr_amount_mismatch": amount_match is False,
            "ocr_detected_order_ids": detected_orders,
            "ocr_order_match": order_match,
            "ocr_order_mismatch": order_match is False,
        }
    )
    deps.persist_case(case_id, risk_flags=flags)

    if errors:
        deps.record_agent_run(
            case_id,
            "EvidenceAgent",
            "FAILED",
            output_summary=f"部分失败: {len(errors)}/{len(evidence)}",
            error="; ".join(errors),
        )
        deps.publish_event(case_id, {"agent": "EvidenceAgent", "status": "failed", "errors": errors})

    if not all_ocr_texts:
        deps.record_agent_run(case_id, "EvidenceAgent", "FAILED", output_summary="所有凭证 OCR 均失败")
        deps.publish_event(case_id, {"agent": "EvidenceAgent", "status": "done", "evidence_present": False})
        return {
            "evidence_present": True,
            "ocr_text": "",
            "ocr_confidence": None,
            "risk_flags": flags,
            "errors": errors,
        }

    overall_conf = min(all_confidences) if all_confidences else None
    combined_text = "\n---\n".join(all_ocr_texts)
    consistency = f"amount_match={amount_match}, order_match={order_match}"
    deps.record_agent_run(
        case_id,
        "EvidenceAgent",
        "SUCCESS",
        output_summary=f"confidence={overall_conf}, files={len(all_ocr_texts)}/{len(evidence)}, {consistency}",
    )
    deps.publish_event(
        case_id,
        {
            "agent": "EvidenceAgent",
            "status": "done",
            "ocr_confidence": overall_conf,
            "amount_match": amount_match,
            "order_match": order_match,
            "file_count": len(all_ocr_texts),
        },
    )
    return {
        "evidence_present": True,
        "ocr_text": combined_text,
        "ocr_confidence": overall_conf,
        "ocr_amounts_cent": detected_amounts,
        "ocr_amount_match": amount_match,
        "ocr_order_match": order_match,
        "risk_flags": flags,
    }
