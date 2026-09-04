"""客诉舆情退赔决策系统 压测脚本（Locust）。

四个业务场景（对应任务三定稿规格的真实端点，前缀 /api/v1）：

    A 建案写路径   POST /api/v1/cases            （幂等键 + Redis Stream 生产）
    B 查询读路径   GET  /api/v1/cases  + 详情     （DB 查询 + 多表聚合）
    C 审批写路径   POST /api/v1/cases/{id}/decision（主管审批挂起案件）
    D 大盘/健康    GET  /api/v1/health + /review-tasks

运行（分阶压测由 scripts/run_load_test.sh 编排）：
    cd loadtest
    locust -f locustfile.py --host http://localhost:8001 \
        --users 50 --spawn-rate 10 --run-time 60s --headless --only-summary

前置：场景 C 需要一批已挂起（SUSPENDED）案件，由 loadtest/seed_cases.py 预生成，
其 ID 列表写入 SUSPENDED_IDS_FILE 指向的 JSON 文件；未提供则该任务自动跳过。
"""
import json
import os
import queue
import threading
import time
import uuid

from locust import HttpUser, between, task

API = "/api/v1"
SUSPENDED_IDS_FILE = os.environ.get("SUSPENDED_IDS_FILE", "suspended_ids.json")
TOKENS_FILE = os.environ.get("TOKENS_FILE", "tokens.json")

# 共享审批队列：预置的挂起案件，每个仅被审批一次，避免重复审批 409 污染错误率
_approve_queue = queue.Queue()
_approve_lock = threading.Lock()
_approve_loaded = False

# Token 池（由 gen_tokens.py 预生成），按轮转分发，避免登录风暴拉高 P95
_token_lock = threading.Lock()
_agent_tokens = []
_sup_tokens = []
_agent_idx = 0
_sup_idx = 0
_tokens_loaded = False


def _headers(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _load_assets():
    """惰性加载挂起案件队列 + Token 池（各仅一次）。"""
    global _approve_loaded, _tokens_loaded, _agent_tokens, _sup_tokens
    with _approve_lock:
        if not _approve_loaded:
            _approve_loaded = True
            try:
                with open(SUSPENDED_IDS_FILE, "r", encoding="utf-8") as f:
                    for cid in json.load(f):
                        _approve_queue.put(cid)
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass
        if not _tokens_loaded:
            _tokens_loaded = True
            try:
                with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    _agent_tokens = data.get("agent", [])
                    _sup_tokens = data.get("supervisor", [])
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass


def _next_token(pool):
    """从池中轮转取 token（无 token 则返回 None，触发回退到空授权）。"""
    if not pool:
        return None
    global _agent_idx, _sup_idx
    with _token_lock:
        if pool is _agent_tokens:
            tok = _agent_tokens[_agent_idx % len(_agent_tokens)]
            _agent_idx += 1
        else:
            tok = _sup_tokens[_sup_idx % len(_sup_tokens)]
            _sup_idx += 1
        return tok


def _idem():
    return uuid.uuid4().hex


class RefundUser(HttpUser):
    """客服视角：建案 + 查询 + 大盘。"""

    weight = 9  # 客服为主（场景 A/B/D），主管占比低（场景 C）
    wait_time = between(0.1, 0.5)
    token = None
    last_case_id = None

    def on_start(self):
        _load_assets()
        self.token = _next_token(_agent_tokens)

    @property
    def auth(self):
        return _headers(self.token)

    # —— 场景 A：建案（写路径） ——
    @task(6)
    def create_case(self):
        # 约 70% 低金额（自动完成）+ 30% 高金额（转人工挂起）
        amount = 12800 if uuid.uuid4().int % 10 < 7 else 35000
        r = self.client.post(
            f"{API}/cases",
            json={
                "order_id": f"load-{time.time_ns()}-{uuid.uuid4().hex[:6]}",
                "amount_cent": amount,
                "complaint_text": "压测：系统故障导致错误扣费",
                "risk_flags": {},
                "evidence": [{"file_name": "clear.jpg"}],
            },
            headers={**self.auth, "X-Idempotency-Key": _idem()},
        )
        if r.status_code == 202:
            self.last_case_id = r.json().get("case_id")

    # —— 场景 B：查询（读路径） ——
    @task(4)
    def list_cases(self):
        self.client.get(f"{API}/cases?limit=20", headers=self.auth)

    @task(2)
    def get_case_detail(self):
        cid = getattr(self, "last_case_id", None)
        if cid:
            # name 固定，避免每个 case_id 各占一行统计
            self.client.get(f"{API}/cases/{cid}", headers=self.auth, name=f"{API}/cases/{{id}}")

    # —— 场景 D：大盘 / 健康 ——
    @task(2)
    def health(self):
        self.client.get(f"{API}/health")


class SupervisorUser(HttpUser):
    """主管视角：审批挂起案件 + 大盘。"""

    weight = 1  # 主管占比低，审批受预置队列约束
    wait_time = between(0.2, 0.8)
    token = None

    def on_start(self):
        _load_assets()
        self.token = _next_token(_sup_tokens)

    @property
    def auth(self):
        return _headers(self.token)

    # —— 场景 C：审批（写路径，需预置挂起案件） ——
    @task(5)
    def approve_case(self):
        _load_assets()
        try:
            cid = _approve_queue.get_nowait()
        except queue.Empty:
            return  # 队列耗尽 -> 本轮不审批
        with self.client.post(
            f"{API}/cases/{cid}/decision",
            json={"action": "APPROVE", "comment": "压测审批"},
            headers={**self.auth, "X-Idempotency-Key": _idem()},
            name=f"{API}/cases/{{id}}/decision",
            catch_response=True,
        ) as r:
            if r.status_code == 409:
                # 案件已被审批（跨阶段复用同一预置队列的幂等冲突），不算业务失败
                r.success()

    # —— 场景 D：主管大盘 ——
    @task(2)
    def review_tasks(self):
        self.client.get(f"{API}/review-tasks", headers=self.auth)
