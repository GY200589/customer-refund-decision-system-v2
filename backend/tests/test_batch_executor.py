from app.batch.executor import execute_batch_approval
from app.batch.models import ApprovalRow


class _Query:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None


class _Session:
    def __init__(self, added):
        self.added = added

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def query(self, *args, **kwargs):
        return _Query()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        return None


class _Redis:
    def __init__(self, can_lock=True):
        self.can_lock = can_lock
        self.released = []

    def set(self, key, token, nx, px):
        return self.can_lock

    def eval(self, script, key_count, key, token):
        self.released.append((key, token))
        return 1


class _Deps:
    def __init__(self, can_lock=True):
        self.redis = _Redis(can_lock)
        self.added = []
        self.review_updates = []

    def session(self):
        return _Session(self.added)

    def get_case_status(self, case_id):
        return "SUSPENDED"

    def update_review_task(self, case_id, operator_id, action, comment):
        self.review_updates.append((case_id, operator_id, action, comment))


class _Graph:
    def __init__(self):
        self.calls = []

    def invoke(self, command, config):
        self.calls.append((command, config))


def test_batch_executor_resumes_each_case_and_releases_lock():
    deps = _Deps()
    graph = _Graph()

    result = execute_batch_approval(
        rows=[
            ApprovalRow(case_id="case-a", action="同意", comment="凭证有效"),
            ApprovalRow(case_id="case-b", action="拒绝", comment="材料不足"),
        ],
        deps=deps,
        graph=graph,
        operator="supervisor1",
        operator_id=2,
    )

    assert result.model_dump(exclude={"failures"}) == {
        "total": 2,
        "approved": 1,
        "rejected": 1,
        "failed": 0,
    }
    assert len(graph.calls) == 2
    assert [call[1]["configurable"]["thread_id"] for call in graph.calls] == ["case-a", "case-b"]
    assert deps.review_updates == [
        ("case-a", 2, "APPROVE", "凭证有效"),
        ("case-b", 2, "REJECT", "材料不足"),
    ]
    assert [key for key, _ in deps.redis.released] == [
        "refund:approval:case-a",
        "refund:approval:case-b",
    ]


def test_batch_executor_reports_lock_conflict_without_invoking_graph():
    deps = _Deps(can_lock=False)
    graph = _Graph()

    result = execute_batch_approval(
        rows=[ApprovalRow(case_id="case-a", action="同意")],
        deps=deps,
        graph=graph,
        operator="supervisor1",
        operator_id=2,
    )

    assert result.failed == 1
    assert result.failures[0]["case_id"] == "case-a"
    assert graph.calls == []
