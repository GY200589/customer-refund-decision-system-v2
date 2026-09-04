"""用户端退款链路测试（定稿 §4.5）：可退金额校验、幂等、来源标识、画像累计。"""
import hashlib
import uuid

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, RefundCase, ShopOrder, User
from app.services.refund_guard import customer_refund_profile


def _token(client, username, password="password123"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _new_order(client, token):
    items = client.get("/api/v1/customer/products?page_size=50", headers=_auth(token)).json()["items"]
    p = next(x for x in items if x["sub_category"] == "joggers")
    r = client.post(
        "/api/v1/customer/orders",
        json={"items": [{"product_id": p["id"], "size": p["sizes"][0], "quantity": 1}]},
        headers=_auth(token),
    )
    assert r.status_code == 201
    return r.json()


def test_customer_refund_profile_uses_orders_as_denominator(db_setup):
    """演示产生很多退款记录时，画像仍按购买订单计算，而不是按退款案件计算。"""
    suffix = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        user = User(
            username=f"profile-{suffix}",
            password_hash="test-only",
            role="customer",
            display_name="画像测试用户",
        )
        db.add(user)
        db.flush()
        for index in range(10):
            order_no = f"PROFILE-{suffix}-{index}"
            db.add(ShopOrder(order_no=order_no, customer_id=user.id, total_cent=10000))
            if index < 4:
                db.add(RefundCase(
                    order_id=order_no,
                    user_id=user.id,
                    amount_cent=1500,
                    status="COMPLETED",
                    refund_status="EXECUTED",
                    source="customer_portal",
                ))
        db.commit()

        profile = customer_refund_profile(db, user.id)
        assert profile["total_orders"] == 10
        assert profile["refunded_orders"] == 4
        assert profile["refund_rate"] == 0.4


def test_refund_requires_idempotency_key(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        r = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={"reason_code": "size"},
            headers=_auth(token),
        )
        assert r.status_code == 400


def test_refund_full_amount_and_source(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        r = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={"reason_code": "size", "description": "尺码买大了"},
            headers={**_auth(token), "X-Idempotency-Key": "rf-full-1"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["amount_cent"] == order["total_cent"]
        assert body["friendly_status"] == "正在核对资料"

        with SessionLocal() as db:
            case = db.query(RefundCase).filter(RefundCase.case_id == body["case_id"]).first()
            assert case.source == "customer_portal"
            assert case.user_id != 1  # 申请人=顾客本人（C3）
            assert case.product_sub_category == "joggers"
            user = db.query(User).filter(User.username == "customer1").first()
        assert user.total_cases >= 1  # 画像累计生效（C4）


def test_size_refund_without_evidence_can_complete_for_demo(db_setup):
    """标准尺码售后无需凭证，避免用户端每笔演示退款都进入人工队列。"""
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        created = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={
                "item_id": order["items"][0]["id"],
                "reason_code": "size",
                "issue_severity": "moderate",
                "description": "尺码不合适",
            },
            headers={**_auth(token), "X-Idempotency-Key": "rf-size-no-proof"},
        )
        assert created.status_code == 201, created.text
        with SessionLocal() as db:
            case = db.query(RefundCase).filter(RefundCase.case_id == created.json()["case_id"]).one()
            assert case.risk_flags["reason_code"] == "size"
            assert case.risk_flags["evidence_required"] is False


def test_minor_quality_issue_defaults_to_partial_refund(db_setup):
    """轻微质量问题缺省采用建议金额，不再无差别全额退款。"""
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        item = order["items"][0]
        quote = client.get(
            f"/api/v1/customer/orders/{order['order_no']}/refund-quote",
            params={"item_id": item["id"], "reason_code": "quality", "issue_severity": "minor"},
            headers=_auth(token),
        )
        assert quote.status_code == 200, quote.text
        quote_body = quote.json()
        assert quote_body["recommended_rate"] == 15
        assert quote_body["recommended_amount_cent"] < item["unit_price_cent"]

        created = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={
                "item_id": item["id"],
                "reason_code": "quality",
                "issue_severity": "minor",
                "description": "裤脚有一点小线头",
            },
            headers={**_auth(token), "X-Idempotency-Key": "rf-minor-partial"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["amount_cent"] == quote_body["recommended_amount_cent"]
        assert created.json()["partial_refund"] is True


def test_full_claim_for_minor_defect_is_marked_for_manual_review(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        item = order["items"][0]
        created = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={
                "item_id": item["id"],
                "amount_cent": item["unit_price_cent"],
                "reason_code": "quality",
                "issue_severity": "minor",
                "description": "只有一点小瑕疵但申请全额",
            },
            headers={**_auth(token), "X-Idempotency-Key": "rf-minor-full-review"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["needs_manual_review"] is True
        with SessionLocal() as db:
            case = db.query(RefundCase).filter(RefundCase.case_id == created.json()["case_id"]).one()
            assert case.risk_flags["amount_exceeds_recommendation"] is True
            assert case.risk_flags["recommended_amount_cent"] < case.amount_cent
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.case_id == case.case_id, AuditLog.action == "refund:guard_evaluated")
                .one()
            )
            assert audit.after_value["amount_exceeds_recommendation"] is True


def test_customer_upload_returns_hash_and_ocr_amount_warning(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        content = b"\x89PNG\r\n\x1a\n" + b"mock-image-content"
        response = client.post(
            "/api/v1/customer/uploads?amount_cent=5000",
            files={"file": ("amount-9.99.png", content, "image/png")},
            headers=_auth(token),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["file_hash"] == hashlib.sha256(content).hexdigest()
        assert body["ocr_fields"]["amount_cent"] == 999
        assert body["ocr_amount_match"] is False


def test_customer_cannot_reference_unowned_evidence_path(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        response = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={
                "item_id": order["items"][0]["id"],
                "reason_code": "quality",
                "evidence": [{"file_name": "fake.png", "file_path": "C:/Windows/fake.png", "file_hash": "forged"}],
            },
            headers={**_auth(token), "X-Idempotency-Key": "rf-unowned-evidence"},
        )
        assert response.status_code == 422
        assert "不属于当前账号" in response.json()["error"]["message"]


def test_reused_evidence_is_added_to_anti_abuse_profile(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        content = b"\x89PNG\r\n\x1a\n" + b"reused-proof-content"
        uploaded = client.post(
            "/api/v1/customer/uploads?amount_cent=5000",
            files={"file": ("proof.png", content, "image/png")},
            headers=_auth(token),
        ).json()
        proof = {
            "file_name": uploaded["file_name"],
            "file_path": uploaded["file_path"],
            "file_hash": "client-value-is-not-trusted",
        }
        first_order = _new_order(client, token)
        first = client.post(
            f"/api/v1/customer/orders/{first_order['order_no']}/refund",
            json={
                "item_id": first_order["items"][0]["id"],
                "reason_code": "size",
                "evidence": [proof],
            },
            headers={**_auth(token), "X-Idempotency-Key": "rf-evidence-first"},
        )
        assert first.status_code == 201, first.text

        second_order = _new_order(client, token)
        second = client.post(
            f"/api/v1/customer/orders/{second_order['order_no']}/refund",
            json={
                "item_id": second_order["items"][0]["id"],
                "reason_code": "size",
                "evidence": [proof],
            },
            headers={**_auth(token), "X-Idempotency-Key": "rf-evidence-second"},
        )
        assert second.status_code == 201, second.text
        with SessionLocal() as db:
            case = db.query(RefundCase).filter(RefundCase.case_id == second.json()["case_id"]).one()
            assert case.risk_flags["duplicate_evidence"] is True
            assert case.risk_flags["duplicate_evidence_count"] >= 1


def test_refund_idempotent_double_click(db_setup):
    """重复点击提交只创建一个案件（复用 IdempotencyRecord）。"""
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        headers = {**_auth(token), "X-Idempotency-Key": "rf-idem-1"}
        payload = {"reason_code": "size", "description": "尺码不合适"}
        r1 = client.post(f"/api/v1/customer/orders/{order['order_no']}/refund", json=payload, headers=headers)
        r2 = client.post(f"/api/v1/customer/orders/{order['order_no']}/refund", json=payload, headers=headers)
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["case_id"] == r2.json()["case_id"]


def test_refund_amount_exceeds_refundable(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        r = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={"reason_code": "other", "amount_cent": order["total_cent"] + 100000},
            headers={**_auth(token), "X-Idempotency-Key": "rf-over-1"},
        )
        assert r.status_code == 422


def test_refund_partial_by_item(db_setup):
    """部分退款：按明细金额校验可退额度，案件携带商品与 order_item_id。"""
    with TestClient(app) as client:
        token = _token(client, "customer1")
        # 预置订单 SO2026090100003 有两个商品（卫衣 L + 工装短裤 32）
        detail = client.get("/api/v1/customer/orders/SO2026090100003", headers=_auth(token)).json()
        assert len(detail["items"]) == 2
        hoodie = next(i for i in detail["items"] if i["sub_category"] == "hoodie")

        r = client.post(
            "/api/v1/customer/orders/SO2026090100003/refund",
            json={"item_id": hoodie["id"], "reason_code": "size", "description": "卫衣买小了"},
            headers={**_auth(token), "X-Idempotency-Key": "rf-part-1"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["amount_cent"] == hoodie["unit_price_cent"]

        # 明细可退额度扣减
        detail2 = client.get("/api/v1/customer/orders/SO2026090100003", headers=_auth(token)).json()
        hoodie2 = next(i for i in detail2["items"] if i["id"] == hoodie["id"])
        assert hoodie2["refundable_cent"] == 0


def test_refund_duplicate_pending_item_rejected(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        r1 = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={"item_id": None, "reason_code": "size"},
            headers={**_auth(token), "X-Idempotency-Key": "rf-dup-1"},
        )
        assert r1.status_code == 201
        # 整单已有处理中的退款 → 再次申请 409（不同幂等键）
        r2 = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={"reason_code": "other"},
            headers={**_auth(token), "X-Idempotency-Key": "rf-dup-2"},
        )
        assert r2.status_code == 409


def test_same_product_new_order_can_refund_after_previous_completed(db_setup):
    """同款商品的售后额度按订单明细隔离，前一单退款完成不影响再次购买。"""
    with TestClient(app) as client:
        token = _token(client, "customer1")
        first_order = _new_order(client, token)
        first_item = first_order["items"][0]
        first_refund = client.post(
            f"/api/v1/customer/orders/{first_order['order_no']}/refund",
            json={"item_id": first_item["id"], "reason_code": "size", "description": "第一次购买尺码不合适"},
            headers={**_auth(token), "X-Idempotency-Key": "rf-same-product-first"},
        )
        assert first_refund.status_code == 201, first_refund.text

        with SessionLocal() as db:
            case = db.query(RefundCase).filter(RefundCase.case_id == first_refund.json()["case_id"]).first()
            case.status = "COMPLETED"
            case.refund_status = "EXECUTED"
            db.commit()

        second_order = _new_order(client, token)
        second_detail = client.get(
            f"/api/v1/customer/orders/{second_order['order_no']}", headers=_auth(token)
        ).json()
        second_item = second_detail["items"][0]
        assert second_item["product_id"] == first_item["product_id"]
        assert second_item["id"] != first_item["id"]
        assert second_item["refundable_cent"] == second_item["unit_price_cent"]
        assert second_item["has_active_refund"] is False

        second_refund = client.post(
            f"/api/v1/customer/orders/{second_order['order_no']}/refund",
            json={"item_id": second_item["id"], "reason_code": "quality", "description": "第二次购买有质量问题"},
            headers={**_auth(token), "X-Idempotency-Key": "rf-same-product-second"},
        )
        assert second_refund.status_code == 201, second_refund.text


def test_customer_refund_detail_is_scoped_and_user_friendly(db_setup):
    """退款详情仅本人可见，并且不返回内部风控与 Agent 运行数据。"""
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        created = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={"item_id": order["items"][0]["id"], "reason_code": "logistics", "description": "包裹一直没有更新"},
            headers={**_auth(token), "X-Idempotency-Key": "rf-detail-1"},
        )
        assert created.status_code == 201, created.text
        case_id = created.json()["case_id"]

        detail = client.get(f"/api/v1/customer/refunds/{case_id}", headers=_auth(token))
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert payload["order_no"] == order["order_no"]
        assert payload["reason"] == "物流问题"
        assert payload["timeline"] and payload["friendly_explanation"]
        assert "fraud_score" not in payload and "agent_runs" not in payload

        admin_token = _token(client, "admin1")
        client.post(
            "/api/v1/admin/users",
            json={"username": "customer-refund-detail", "password": "password123", "role": "customer"},
            headers=_auth(admin_token),
        )
        other_token = _token(client, "customer-refund-detail")
        assert client.get(f"/api/v1/customer/refunds/{case_id}", headers=_auth(other_token)).status_code == 404


def test_refund_others_order_404(db_setup):
    with TestClient(app) as client:
        admin_token = _token(client, "admin1")
        client.post(
            "/api/v1/admin/users",
            json={"username": "customer3", "password": "password123", "role": "customer", "display_name": "顾客老三"},
            headers=_auth(admin_token),
        )
        c3 = _token(client, "customer3")
        r = client.post(
            "/api/v1/customer/orders/SO2026090100002/refund",
            json={"reason_code": "size"},
            headers={**_auth(c3), "X-Idempotency-Key": "rf-other-1"},
        )
        assert r.status_code == 404


def test_agent_sees_customer_portal_case(db_setup):
    """用户端案件对客服可见（含无归属客服的新建案件），列表与详情带来源标识。"""
    with TestClient(app) as client:
        cust_token = _token(client, "customer1")
        r = client.post(
            f"/api/v1/customer/orders/SO2026090100002/refund",
            json={"reason_code": "size", "description": "腰围小了"},
            headers={**_auth(cust_token), "X-Idempotency-Key": "rf-agent-see"},
        )
        case_id = r.json()["case_id"]

        agent_token = _token(client, "agent1")
        listing = client.get("/api/v1/cases", headers=_auth(agent_token)).json()
        assert any(c["case_id"] == case_id for c in listing["items"])
        row = next(c for c in listing["items"] if c["case_id"] == case_id)
        assert row["source"] == "customer_portal" and row["source_label"] == "用户端"

        detail = client.get(f"/api/v1/cases/{case_id}", headers=_auth(agent_token))
        assert detail.status_code == 200
        assert detail.json()["source"] == "customer_portal"


def test_my_refunds_friendly_only(db_setup):
    """用户端退款列表只含本人 portal 案件 + 通俗状态，不暴露风险分。"""
    with TestClient(app) as client:
        token = _token(client, "customer1")
        rows = client.get("/api/v1/customer/refunds", headers=_auth(token)).json()
        assert rows, "至少有一笔本人退款申请"
        for row in rows:
            assert "friendly_status" in row and row["friendly_status"]
            assert "fraud_score" not in row and "risk_level" not in row


def test_refund_audit_logged(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        order = _new_order(client, token)
        r = client.post(
            f"/api/v1/customer/orders/{order['order_no']}/refund",
            json={"reason_code": "other"},
            headers={**_auth(token), "X-Idempotency-Key": "rf-audit-1"},
        )
        case_id = r.json()["case_id"]
        with SessionLocal() as db:
            log = (
                db.query(AuditLog)
                .filter(AuditLog.case_id == case_id, AuditLog.action == "case:created")
                .first()
            )
            assert log is not None
            assert log.after_value.get("source") == "customer_portal"
            assert db.query(ShopOrder).filter(ShopOrder.order_no == order["order_no"]).first() is not None


def test_shop_order_aware_order_verify(db_setup):
    """订单感知校验：SO 订单返回真实金额；未知订单回退 legacy Mock 规则。"""
    from app.infrastructure.providers.order_verify import (
        MockOrderVerificationProvider,
        ShopOrderAwareOrderVerificationProvider,
    )

    provider = ShopOrderAwareOrderVerificationProvider(fallback=MockOrderVerificationProvider())
    result = provider.verify("SO2026090100002")
    assert result.is_valid
    assert result.verified_amount_cent == 17900  # 休闲直筒长裤种子价

    # 未知订单回退 legacy：长度达标视为有效、固定 10000 分（既有测试口径不变）
    legacy = provider.verify("ORD2024001")
    assert legacy.is_valid and legacy.verified_amount_cent == 10000
    bad = provider.verify("123")
    assert not bad.is_valid
