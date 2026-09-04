"""customer 角色与用户端权限隔离测试（定稿 §4.1 / §6）。"""
from fastapi.testclient import TestClient

from app.main import app


def _token(client, username, password="password123"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_customer_login_and_role(db_setup):
    with TestClient(app) as client:
        r = client.post("/api/v1/auth/login", json={"username": "customer1", "password": "password123"})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "customer"


def test_customer_cannot_access_console_apis(db_setup):
    """用户端身份访问后台接口必须 403（审批/案件列表/管理/统计）。"""
    with TestClient(app) as client:
        token = _token(client, "customer1")
        assert client.get("/api/v1/cases", headers=_auth(token)).status_code == 403
        assert client.post(
            "/api/v1/cases", json={"order_id": "o-9", "amount_cent": 100},
            headers={**_auth(token), "X-Idempotency-Key": "cust-forbidden"},
        ).status_code == 403
        assert client.get("/api/v1/review-tasks", headers=_auth(token)).status_code == 403
        assert client.get("/api/v1/admin/users", headers=_auth(token)).status_code == 403
        assert client.get("/api/v1/stats/overview", headers=_auth(token)).status_code == 403


def test_console_roles_cannot_access_customer_apis(db_setup):
    """后台角色访问用户端接口必须 403。"""
    with TestClient(app) as client:
        for username in ("agent1", "supervisor1", "admin1"):
            token = _token(client, username)
            assert client.get("/api/v1/customer/products", headers=_auth(token)).status_code == 403
            assert client.get("/api/v1/customer/orders", headers=_auth(token)).status_code == 403
            assert client.post(
                "/api/v1/customer/assistant", json={"text": "我要退款"},
                headers=_auth(token),
            ).status_code == 403


def test_customer_categories_and_products(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        cats = client.get("/api/v1/customer/categories", headers=_auth(token)).json()
        top = next(n for n in cats["tree"] if n["key"] == "top")
        bottom = next(n for n in cats["tree"] if n["key"] == "bottom")
        assert len(top["children"]) >= 5 and len(bottom["children"]) >= 6

        products = client.get(
            "/api/v1/customer/products?page_size=50", headers=_auth(token)
        ).json()
        assert products["total"] >= 50, "淘宝扩展后应至少有 50 个男装商品"
        subs = {p["sub_category"] for p in products["items"]}
        assert {"jeans", "casual_pants", "joggers", "shorts", "cargo_pants"} <= subs, "至少 5 种下装子类型"


def test_product_filter_by_category(db_setup):
    with TestClient(app) as client:
        token = _token(client, "customer1")
        r = client.get(
            "/api/v1/customer/products?main_category=bottom&sub_category=jeans",
            headers=_auth(token),
        ).json()
        assert r["total"] >= 2
        assert all(p["main_category"] == "bottom" and p["sub_category"] == "jeans" for p in r["items"])
