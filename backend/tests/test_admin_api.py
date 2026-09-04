from fastapi.testclient import TestClient

from app.main import app


def _token(client, username, password="password123"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_endpoints_forbidden_for_non_admin(db_setup):
    with TestClient(app) as client:
        agent = _auth(_token(client, "agent1"))
        assert client.get("/api/v1/admin/thresholds", headers=agent).status_code == 403
        assert client.get("/api/v1/admin/users", headers=agent).status_code == 403
        assert client.get("/api/v1/admin/audit-logs", headers=agent).status_code == 403


def test_thresholds_roundtrip(db_setup):
    with TestClient(app) as client:
        admin = _auth(_token(client, "admin1"))
        r = client.get("/api/v1/admin/thresholds", headers=admin)
        assert r.status_code == 200
        body = r.json()
        assert "amount_human_review_threshold_cent" in body

        r2 = client.put(
            "/api/v1/admin/thresholds",
            json={"amount_human_review_threshold_cent": 50000},
            headers=admin,
        )
        assert r2.status_code == 200
        assert r2.json()["amount_human_review_threshold_cent"] == 50000

        # 空 body 应 422
        assert client.put("/api/v1/admin/thresholds", json={}, headers=admin).status_code == 422
        # 非法取值应 422（欺诈分拒绝阈值 > 100）
        assert (
            client.put("/api/v1/admin/thresholds", json={"fraud_reject_threshold": 150}, headers=admin).status_code
            == 422
        )


def test_users_crud(db_setup):
    with TestClient(app) as client:
        admin = _auth(_token(client, "admin1"))

        # 创建
        r = client.post(
            "/api/v1/admin/users",
            json={"username": "agent2", "password": "password123", "role": "agent", "display_name": "客服小李"},
            headers=admin,
        )
        assert r.status_code == 201, r.text
        uid = r.json()["id"]

        # 重复创建 -> 409
        r2 = client.post(
            "/api/v1/admin/users",
            json={"username": "agent2", "password": "password123", "role": "agent"},
            headers=admin,
        )
        assert r2.status_code == 409

        # 列表包含新用户
        users = client.get("/api/v1/admin/users", headers=admin).json()
        assert any(u["username"] == "agent2" for u in users)

        # 更新角色与禁用
        r3 = client.patch(
            f"/api/v1/admin/users/{uid}",
            json={"role": "supervisor", "is_active": False},
            headers=admin,
        )
        assert r3.status_code == 200
        assert r3.json()["role"] == "supervisor"
        assert r3.json()["is_active"] is False


def test_admin_cannot_lock_self(db_setup):
    with TestClient(app) as client:
        admin_token = _token(client, "admin1")
        admin = _auth(admin_token)
        login = client.post(
            "/api/v1/auth/login", json={"username": "admin1", "password": "password123"}
        )
        admin_id = login.json()["user"]["id"]

        # 不能禁用自己
        assert client.patch(f"/api/v1/admin/users/{admin_id}", json={"is_active": False}, headers=admin).status_code == 409
        # 不能降级自己
        assert client.patch(f"/api/v1/admin/users/{admin_id}", json={"role": "agent"}, headers=admin).status_code == 409


def test_audit_logs_visible(db_setup):
    with TestClient(app) as client:
        admin = _auth(_token(client, "admin1"))
        r = client.get("/api/v1/admin/audit-logs", headers=admin)
        assert r.status_code == 200
        body = r.json()
        assert "total" in body and "items" in body


def test_health_reports_components(db_setup):
    with TestClient(app) as client:
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert "checks" in body
        assert "database" in body["checks"]
        assert "redis" in body["checks"]
