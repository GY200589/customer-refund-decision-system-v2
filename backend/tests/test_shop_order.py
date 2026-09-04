"""模拟购物订单测试：服务端算价 / 归属隔离 / 状态（定稿 §4.4 / C8）。"""
from fastapi.testclient import TestClient

from app.main import app


def _token(client, username, password="password123"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _first_product(client, token, sub_category=None):
    url = "/api/v1/customer/products?page_size=50"
    if sub_category:
        url += f"&sub_category={sub_category}"
    items = client.get(url, headers=_auth(token)).json()["items"]
    return items[0]


def test_create_order_server_side_pricing(db_setup):
    """下单金额必须等于服务端 price_cent × quantity，与前端无关。"""
    with TestClient(app) as client:
        token = _token(client, "customer1")
        p = _first_product(client, token, sub_category="jeans")
        r = client.post(
            "/api/v1/customer/orders",
            json={"items": [{"product_id": p["id"], "size": p["sizes"][0], "quantity": 2}]},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.text
        order = r.json()
        assert order["total_cent"] == p["price_cent"] * 2
        assert order["order_no"].startswith("SO") and len(order["order_no"]) >= 6
        assert order["status"] == "COMPLETED"


def test_order_invalid_size_rejected(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        p = _first_product(client, token)
        r = client.post(
            "/api/v1/customer/orders",
            json={"items": [{"product_id": p["id"], "size": "不存在码", "quantity": 1}]},
            headers=_auth(token),
        )
        assert r.status_code == 422


def test_order_list_only_mine(db_setup):
    """agent 登录后预置订单不可见；customer1 可见种子订单。"""
    with TestClient(app) as client:
        cust_token = _token(client, "customer1")
        orders = client.get("/api/v1/customer/orders", headers=_auth(cust_token)).json()
        assert len(orders) >= 3, "预置演示订单开箱可用"
        for o in orders:
            assert o["order_no"].startswith("SO")

        agent_token = _token(client, "agent1")
        r = client.get("/api/v1/customer/orders", headers=_auth(agent_token))
        assert r.status_code == 403


def test_order_detail_includes_refundable(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        orders = client.get("/api/v1/customer/orders", headers=_auth(token)).json()
        detail = client.get(f"/api/v1/customer/orders/{orders[0]['order_no']}", headers=_auth(token)).json()
        assert "refundable_cent" in detail and detail["refundable_cent"] == detail["total_cent"]
        assert detail["has_active_refund"] is False
        assert detail["payment"]["status"] == "PAID" and detail["payment"]["is_demo"] is True
        assert detail["recipient"]["address"].endswith("（演示地址）")
        assert detail["logistics"]["steps"] and detail["logistics"]["is_demo"] is True
        assert detail["pricing"]["paid_cent"] == detail["total_cent"]
        assert all("line_total_cent" in item and "image_url" in item for item in detail["items"])


def test_other_users_order_is_404(db_setup):
    """他人订单按 404 处理，不泄露存在性。"""
    with TestClient(app) as client:
        # 用 admin 创建一个 customer，再验证它看不到 customer1 的订单
        admin_token = _token(client, "admin1")
        client.post(
            "/api/v1/admin/users",
            json={"username": "customer2", "password": "password123", "role": "customer", "display_name": "顾客老王"},
            headers=_auth(admin_token),
        )
        cust2_token = _token(client, "customer2")
        orders2 = client.get("/api/v1/customer/orders", headers=_auth(cust2_token)).json()
        assert orders2 == []

        cust1_token = _token(client, "customer1")
        orders1 = client.get("/api/v1/customer/orders", headers=_auth(cust1_token)).json()
        r = client.get(f"/api/v1/customer/orders/{orders1[0]['order_no']}", headers=_auth(cust2_token))
        assert r.status_code == 404
