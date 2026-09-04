from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import User


def _token(client, username, password="password123"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _case_payload(order_id="o-1", amount_cent=12800):
    return {
        "order_id": order_id,
        "amount_cent": amount_cent,
        "complaint_text": "系统故障导致错误扣费",
        "risk_flags": {},
        "evidence": [{"file_name": "clear.jpg"}],
    }


def test_health(db_setup):
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"


def test_login_ok_and_wrong_password(db_setup):
    with TestClient(app) as client:
        assert _token(client, "agent1")
        r = client.post("/api/v1/auth/login", json={"username": "agent1", "password": "wrong"})
        assert r.status_code == 401


def test_create_requires_auth(db_setup):
    with TestClient(app) as client:
        r = client.post("/api/v1/cases", json=_case_payload())
        assert r.status_code == 401


def test_create_idempotency(db_setup):
    with TestClient(app) as client:
        token = _token(client, "agent1")
        headers = {**_auth(token), "X-Idempotency-Key": "create-k-1"}
        r1 = client.post("/api/v1/cases", json=_case_payload(), headers=headers)
        assert r1.status_code == 202
        case_id = r1.json()["case_id"]

        r2 = client.post("/api/v1/cases", json=_case_payload(), headers=headers)
        assert r2.status_code == 202
        assert r2.json()["case_id"] == case_id

        # 相同 key 不同 body -> 422
        r3 = client.post(
            "/api/v1/cases",
            json=_case_payload(order_id="o-2"),
            headers={**_auth(token), "X-Idempotency-Key": "create-k-1"},
        )
        assert r3.status_code == 422


def test_agent_cannot_approve(db_setup):
    with TestClient(app) as client:
        token = _token(client, "agent1")
        r = client.post(
            "/api/v1/cases/some-case/decision",
            json={"action": "APPROVE"},
            headers={**_auth(token), "X-Idempotency-Key": "d-1"},
        )
        assert r.status_code == 403


def test_decision_flow_end_to_end(db_setup):
    with TestClient(app) as client:
        agent_token = _token(client, "agent1")
        # 创建案件
        r = client.post(
            "/api/v1/cases",
            json=_case_payload(order_id="o-e2e", amount_cent=35000),
            headers={**_auth(agent_token), "X-Idempotency-Key": "e2e-create"},
        )
        case_id = r.json()["case_id"]

        # 手动跑图到挂起（模拟 Worker）
        with SessionLocal() as db:
            agent_id = db.query(User.id).filter(User.username == "agent1").scalar()
        graph = app.state.graph
        deps = app.state.deps
        deps.transition(case_id, "CREATED", "RUNNING")
        result = graph.invoke(
            {
                "case_id": case_id,
                "trace_id": case_id,
                "order_id": "o-e2e",
                "amount_cent": 35000,
                "complaint_text": "系统故障导致错误扣费",
                "risk_flags": {},
                "evidence": [{"file_name": "invoice.jpg"}],
            },
            {"configurable": {"thread_id": case_id}},
        )
        assert "__interrupt__" in result

        # 主管审批
        sup_token = _token(client, "supervisor1")
        r = client.post(
            f"/api/v1/cases/{case_id}/decision",
            json={"action": "APPROVE", "comment": "情况属实"},
            headers={**_auth(sup_token), "X-Idempotency-Key": "e2e-approve"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "COMPLETED"

        # 重复审批 -> 案件已终态，409
        r2 = client.post(
            f"/api/v1/cases/{case_id}/decision",
            json={"action": "APPROVE"},
            headers={**_auth(sup_token), "X-Idempotency-Key": "e2e-approve-2"},
        )
        assert r2.status_code == 409
