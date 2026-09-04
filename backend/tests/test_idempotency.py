from app.services.idempotency import approval_key, compute_request_hash, create_key


def test_request_hash_stable_and_sensitive():
    a = compute_request_hash({"amount": 1, "name": "x"})
    b = compute_request_hash({"name": "x", "amount": 1})
    c = compute_request_hash({"amount": 2, "name": "x"})
    assert a == b  # 字段顺序无关
    assert a != c  # 内容不同则不同


def test_approval_key_contains_context():
    k1 = approval_key(1, "case-1", "APPROVE", "idem-1")
    k2 = approval_key(1, "case-1", "APPROVE", "idem-1")
    k3 = approval_key(1, "case-1", "REJECT", "idem-1")
    k4 = approval_key(2, "case-1", "APPROVE", "idem-1")
    assert k1 == k2
    assert k1 != k3  # action 不同
    assert k1 != k4  # actor 不同


def test_create_key_scoped_by_user():
    k1 = create_key(1, "idem-1")
    k2 = create_key(1, "idem-1")
    k3 = create_key(2, "idem-1")
    assert k1 == k2
    assert k1 != k3  # 不同用户隔离
