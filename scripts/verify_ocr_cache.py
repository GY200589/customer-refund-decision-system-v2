# -*- coding: utf-8 -*-
"""验证 OCR 结果缓存复用（upload 实时预览 -> EvidenceAgent 异步流程不再重复推理）。

场景模拟：
  1. FakeRedis 模拟缓存层
  2. 第一次 extract（upload 实时预览）-> 真实 PaddleOCR 推理，结果写入缓存
  3. 第二次 extract（EvidenceAgent 异步流程）-> 命中缓存，毫秒级返回，结果一致
  4. Redis 不可用（传 None）-> 降级直通，功能不受影响

用法（项目根目录）:
    backend/.venv/Scripts/python.exe scripts/verify_ocr_cache.py
"""
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))


class FakeRedis:
    """最小化 Redis 模拟：get / setex / delete，够 CachedOcrProvider 用。"""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


def main():
    from app.infrastructure.providers.ocr import CachedOcrProvider, PaddleOcrProvider

    tmp = Path(__file__).parent / "_ocr_tmp"
    img = tmp / "receipt.png"
    if not img.exists():
        print("缺少 receipt.png，先运行 verify_ocr.py 生成")
        return 1

    fake_redis = FakeRedis()
    inner = PaddleOcrProvider(lang="ch")
    cached = CachedOcrProvider(inner, redis_client=fake_redis, ttl=3600)

    print("== 场景 1：upload 实时预览（首次，真实推理）==")
    t0 = time.perf_counter()
    r1 = cached.extract("receipt.png", str(img), None, 0)
    t1 = time.perf_counter() - t0
    print(f"耗时 {t1:.2f}s | 置信度 {r1.overall_confidence:.4f} | 字段 {r1.fields}")

    print("\n== 场景 2：EvidenceAgent 异步流程（命中缓存）==")
    t0 = time.perf_counter()
    r2 = cached.extract("receipt.png", str(img), "hash-x", 12990)  # file_hash/amount 与 upload 时不同
    t2 = time.perf_counter() - t0
    print(f"耗时 {t2 * 1000:.1f}ms | 置信度 {r2.overall_confidence:.4f} | 字段 {r2.fields}")

    assert r1.text == r2.text, "两次识别文本不一致"
    assert abs(r1.overall_confidence - r2.overall_confidence) < 1e-9, "置信度不一致"
    assert r1.fields == r2.fields, "字段不一致"
    assert t2 < 0.05, f"缓存命中却耗时 {t2 * 1000:.1f}ms（应 <50ms）"
    speedup = t1 / t2 if t2 > 0 else float("inf")
    print(f"[PASS] 结果完全一致，加速 {speedup:.0f}x")

    print("\n== 场景 3：缓存失效后重新推理 ==")
    fake_redis.delete(f"ocr:cache:{img}")
    t0 = time.perf_counter()
    r3 = cached.extract("receipt.png", str(img), None, 0)
    t3 = time.perf_counter() - t0
    print(f"耗时 {t3:.2f}s（重新真实推理）")
    assert r3.text == r1.text, "重新推理结果不一致"
    print("[PASS] 缓存删除后正确回源")

    print("\n== 场景 4：Redis 不可用时降级直通 ==")
    no_cache = CachedOcrProvider(inner, redis_client=None)
    r4 = no_cache.extract("receipt.png", str(img), None, 0)
    assert r4.text == r1.text
    print("[PASS] 无 Redis 时直通，功能正常")

    print("\n全部场景通过 ✓ upload 识别一次，EvidenceAgent 免二次推理")
    return 0


if __name__ == "__main__":
    sys.exit(main())
