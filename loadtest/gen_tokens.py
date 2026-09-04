"""预生成 JWT Token 池，避免压测时每个 Locust 用户都走一次 bcrypt 登录。

登录的 bcrypt 校验（约 250ms）在数百用户并发 spawn 时会形成登录风暴，严重拉高
P95 并掩盖真实业务端点性能。JWT 无状态，预生成后按轮转分发即可。

用法：
    cd loadtest
    python gen_tokens.py [agent数] [supervisor数] [BASE_URL]

生成 tokens.json：{"agent": [...], "supervisor": [...]}，供 locustfile.py 读取。
"""
import json
import sys

import httpx

BASE = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:8001"
N_AGENT = int(sys.argv[1]) if len(sys.argv) > 1 else 50
N_SUP = int(sys.argv[2]) if len(sys.argv) > 2 else 10
API = f"{BASE}/api/v1"


def _login(c, username):
    r = c.post(f"{API}/auth/login", json={"username": username, "password": "password123"})
    r.raise_for_status()
    return r.json()["token"]


def main():
    with httpx.Client(timeout=30, trust_env=False) as c:
        agents = [_login(c, "agent1") for _ in range(N_AGENT)]
        sups = [_login(c, "supervisor1") for _ in range(N_SUP)]
    with open("tokens.json", "w", encoding="utf-8") as f:
        json.dump({"agent": agents, "supervisor": sups}, f)
    print(f"已生成 {len(agents)} agent + {len(sups)} supervisor tokens -> tokens.json")


if __name__ == "__main__":
    main()
