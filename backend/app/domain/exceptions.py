class ConcurrencyConflict(Exception):
    """并发冲突（乐观锁失败 / 状态已变更），映射为 HTTP 409。"""
