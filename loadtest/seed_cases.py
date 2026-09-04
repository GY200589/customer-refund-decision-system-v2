"""预生成挂起案件，供压测场景 C（审批）使用。

用法：
    cd loadtest
    python seed_cases.py [数量] [BASE_URL]

默认生成 200 个金额 350 元（35000 分，>= 300 元阈值）的挂起案件，其 case_id 写入
suspended_ids.json（与 locustfile.py 的 SUSPENDED_IDS_FILE 对应）。
"""
import json
import sys
import time
import uuid

import httpx

BASE = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8001"
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 200
API = f"{BASE}/api/v1"


def main():
    with httpx.Client(timeout=30, trust_env=False) as c:
        r = c.post(f"{API}/auth/login", json={"username": "agent1", "password": "password123"})
        r.raise_for_status()
        token = r.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        ids = []
        for i in range(COUNT):
            resp = c.post(
                f"{API}/cases",
                json={
                    "order_id": f"seed-{i}-{uuid.uuid4().hex[:6]}",
                    "amount_cent": 35000,
                    "complaint_text": "压测预置：商品破损要求退款",
                    "risk_flags": {},
                    "evidence": [{"file_name": "invoice.jpg"}],
                },
                headers={**headers, "X-Idempotency-Key": uuid.uuid4().hex},
            )
            if resp.status_code != 202:
                print(f"  [WARN] 第 {i} 个建案失败 {resp.status_code}: {resp.text[:120]}")
                continue
            ids.append(resp.json()["case_id"])

        # 等待 Worker 消费并转为 SUSPENDED
        print(f"已创建 {len(ids)} 个高金额案件，等待 Worker 挂起 ...")
        ready = []
        deadline = time.time() + 60
        while time.time() < deadline and len(ready) < len(ids):
            for cid in list(ids):
                if cid in ready:
                    continue
                g = c.get(f"{API}/cases/{cid}", headers=headers)
                if g.status_code == 200 and g.json().get("status") == "SUSPENDED":
                    ready.append(cid)
            if len(ready) < len(ids):
                time.sleep(1)

        with open("suspended_ids.json", "w", encoding="utf-8") as f:
            json.dump(ready, f)
        print(f"挂起完成：{len(ready)}/{len(ids)}，已写入 suspended_ids.json")


if __name__ == "__main__":
    main()
