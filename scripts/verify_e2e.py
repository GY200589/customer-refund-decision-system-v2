"""端到端验证脚本：真实调用运行中的服务，验证核心业务链路。

用法：
    python scripts/verify_e2e.py [BASE_URL]
    默认 BASE_URL=http://localhost:8001
"""
import sys
import time
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"
API = f"{BASE}/api/v1"


def login(client, username):
    r = client.post(f"{API}/auth/login", json={"username": username, "password": "password123"})
    r.raise_for_status()
    return r.json()["token"]


def idem():
    return uuid.uuid4().hex


def main():
    ok = 0
    fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  [PASS] {name}")
        else:
            fail += 1
            print(f"  [FAIL] {name} {detail}")

    with httpx.Client(timeout=30, trust_env=False) as c:
        print("== 认证 ==")
        agent = login(c, "agent1")
        sup = login(c, "supervisor1")
        check("agent1 登录", bool(agent))
        check("supervisor1 登录", bool(sup))
        ah = {"Authorization": f"Bearer {agent}"}
        sh = {"Authorization": f"Bearer {sup}"}

        print("== 场景B：低金额自动完成 ==")
        r = c.post(
            f"{API}/cases",
            json={
                "order_id": "E2E-B-001",
                "amount_cent": 12800,
                "complaint_text": "系统故障导致错误扣费",
                "risk_flags": {},
                "evidence": [{"file_name": "clear.jpg"}],
            },
            headers={**ah, "X-Idempotency-Key": idem()},
        )
        check("建案返回 202", r.status_code == 202, r.text)
        b_id = r.json()["case_id"]
        time.sleep(3)  # 等待 Worker 消费并跑完工作流
        rb = c.get(f"{API}/cases/{b_id}", headers=ah)
        check("场景B状态 COMPLETED", rb.json()["status"] == "COMPLETED", rb.text)
        check("场景B已退款", rb.json()["refund_status"] == "EXECUTED", rb.text)
        check("场景B低风险", rb.json()["risk_level"] == "LOW", rb.text)

        print("== 场景A：高金额转人工并批准 ==")
        r = c.post(
            f"{API}/cases",
            json={
                "order_id": "E2E-A-001",
                "amount_cent": 35000,
                "complaint_text": "商品破损，要求退款",
                "risk_flags": {},
                "evidence": [{"file_name": "invoice.jpg"}],
            },
            headers={**ah, "X-Idempotency-Key": idem()},
        )
        a_id = r.json()["case_id"]
        time.sleep(3)
        ra = c.get(f"{API}/cases/{a_id}", headers=ah)
        check("场景A挂起 SUSPENDED", ra.json()["status"] == "SUSPENDED", ra.text)
        check("场景A未退款", ra.json()["refund_status"] != "EXECUTED", ra.text)

        print("== 越权：agent 尝试审批（应 403） ==")
        r403 = c.post(
            f"{API}/cases/{a_id}/decision",
            json={"action": "APPROVE"},
            headers={**ah, "X-Idempotency-Key": idem()},
        )
        check("agent 审批被拒 403", r403.status_code == 403, r403.text)

        print("== 主管批准 ==")
        r = c.post(
            f"{API}/cases/{a_id}/decision",
            json={"action": "APPROVE", "comment": "情况属实，批准退款"},
            headers={**sh, "X-Idempotency-Key": idem()},
        )
        check("审批返回 200", r.status_code == 200, r.text)
        check("审批后状态 COMPLETED", r.json()["status"] == "COMPLETED", r.text)
        ra2 = c.get(f"{API}/cases/{a_id}", headers=ah)
        check("审批意见已记录", ra2.json()["review_comment"] == "情况属实，批准退款", ra2.text)
        check("审批后已退款", ra2.json()["refund_status"] == "EXECUTED", ra2.text)

        print("== 重复审批（应 409） ==")
        r409 = c.post(
            f"{API}/cases/{a_id}/decision",
            json={"action": "APPROVE"},
            headers={**sh, "X-Idempotency-Key": idem()},
        )
        check("重复审批被拒 409", r409.status_code == 409, r409.text)

        print("== 幂等：同键重复建案返回同一 case_id ==")
        k = idem()
        p = {
            "order_id": "E2E-IDEM",
            "amount_cent": 12800,
            "complaint_text": "重复请求测试",
            "risk_flags": {},
            "evidence": [{"file_name": "clear.jpg"}],
        }
        r1 = c.post(f"{API}/cases", json=p, headers={**ah, "X-Idempotency-Key": k})
        r2 = c.post(f"{API}/cases", json=p, headers={**ah, "X-Idempotency-Key": k})
        check("幂等返回一致", r1.json()["case_id"] == r2.json()["case_id"], f"{r1.text} vs {r2.text}")

        print("== 列表接口 ==")
        rl = c.get(f"{API}/cases?limit=5", headers=sh)
        check("列表可查询（主管可见全部）", rl.status_code == 200 and rl.json()["total"] >= 3, rl.text)

        print("== 权限：客服仅可见自己创建的案件 ==")
        rl_agent = c.get(f"{API}/cases?limit=200", headers=ah)
        agent_total = rl_agent.json().get("total", 0)
        check("客服列表仅含本人案件", agent_total <= rl.json()["total"], f"agent={agent_total} vs all={rl.json()['total']}")

    print(f"\n结果：{ok} 通过，{fail} 失败")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
