from fastapi.testclient import TestClient

from app.main import app


def _token(client, username, password="password123"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _payload(order_id="sec-o"):
    return {
        "order_id": order_id,
        "amount_cent": 12800,
        "complaint_text": "安全测试",
        "risk_flags": {},
        "evidence": [{"file_name": "clear.jpg"}],
    }


def test_create_idempotency_isolated_by_user(db_setup):
    """相同 X-Idempotency-Key 但不同用户，应各自创建独立案件（不互相命中）。"""
    with TestClient(app) as client:
        agent = _auth(_token(client, "agent1"))
        sup = _auth(_token(client, "supervisor1"))

        r1 = client.post("/api/v1/cases", json=_payload(), headers={**agent, "X-Idempotency-Key": "shared-key"})
        r2 = client.post("/api/v1/cases", json=_payload(), headers={**sup, "X-Idempotency-Key": "shared-key"})
        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["case_id"] != r2.json()["case_id"]


def test_sse_missing_case_404(db_setup):
    with TestClient(app) as client:
        agent = _auth(_token(client, "agent1"))
        r = client.get("/api/v1/cases/does-not-exist/events", headers=agent)
        assert r.status_code == 404


def test_sse_agent_cannot_access_others_case(db_setup):
    with TestClient(app) as client:
        sup = _auth(_token(client, "supervisor1"))
        agent = _auth(_token(client, "agent1"))

        # 主管建案
        r = client.post("/api/v1/cases", json=_payload(order_id="sec-sup"), headers={**sup, "X-Idempotency-Key": "sse-1"})
        case_id = r.json()["case_id"]

        # 客服无权订阅他人案件 -> 403
        r2 = client.get(f"/api/v1/cases/{case_id}/events", headers=agent)
        assert r2.status_code == 403


def test_agent_cannot_get_others_case(db_setup):
    with TestClient(app) as client:
        sup = _auth(_token(client, "supervisor1"))
        agent = _auth(_token(client, "agent1"))

        r = client.post("/api/v1/cases", json=_payload(order_id="sec-sup-2"), headers={**sup, "X-Idempotency-Key": "get-1"})
        case_id = r.json()["case_id"]

        # 客服无权查看他人案件详情 -> 403
        assert client.get(f"/api/v1/cases/{case_id}", headers=agent).status_code == 403
        # 主管本人可查看 -> 200
        assert client.get(f"/api/v1/cases/{case_id}", headers=sup).status_code == 200


def test_agent_list_only_own_cases(db_setup):
    with TestClient(app) as client:
        agent = _auth(_token(client, "agent1"))
        sup = _auth(_token(client, "supervisor1"))

        # 客服与主管各建一案
        agent_case = client.post(
            "/api/v1/cases", json=_payload(order_id="sec-agent"),
            headers={**agent, "X-Idempotency-Key": "list-1"},
        ).json()["case_id"]
        sup_case = client.post(
            "/api/v1/cases", json=_payload(order_id="sec-sup-3"),
            headers={**sup, "X-Idempotency-Key": "list-2"},
        ).json()["case_id"]

        agent_ids = {c["case_id"] for c in client.get("/api/v1/cases?limit=200", headers=agent).json()["items"]}
        all_ids = {c["case_id"] for c in client.get("/api/v1/cases?limit=200", headers=sup).json()["items"]}

        # 客服列表仅含本人案件
        assert agent_case in agent_ids
        assert sup_case not in agent_ids
        # 主管可见全部
        assert agent_case in all_ids and sup_case in all_ids
