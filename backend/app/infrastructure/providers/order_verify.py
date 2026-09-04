"""订单真实性校验 Provider

Mock 实现：对 order_id 做简单格式校验。
真实场景可对接订单系统 API 查询订单是否存在、金额、归属用户。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OrderVerifyResult:
    is_valid: bool
    verified_amount_cent: int = 0
    error: str = ""


class OrderVerificationProvider(ABC):
    @abstractmethod
    def verify(self, order_id: str) -> OrderVerifyResult:
        ...


class MockOrderVerificationProvider(OrderVerificationProvider):
    """Mock 订单校验：order_id 非空且长度 >= 6 视为有效，返回固定金额 10000 分。"""

    def verify(self, order_id: str) -> OrderVerifyResult:
        if not order_id or len(order_id) < 6:
            return OrderVerifyResult(is_valid=False, error="模拟校验：订单不存在或格式错误")
        return OrderVerifyResult(
            is_valid=True,
            verified_amount_cent=10000,
            error="",
        )


class ShopOrderAwareOrderVerificationProvider(OrderVerificationProvider):
    """优先查询真实模拟订单（用户端商城 SO 订单），查不到回退 legacy Mock 规则。

    用户端退款的金额校验以此为准：verified_amount = 真实订单总额，
    避免 Mock 固定金额（10000 分）与真实商品价的差值触发价格偏差转人工（定稿 §4.5）。
    历史行为兼容：客服后台演示用任意长度订单号仍走原 Mock 规则，既有测试不受影响。
    """

    def __init__(self, fallback: OrderVerificationProvider | None = None):
        self._fallback = fallback or MockOrderVerificationProvider()

    def verify(self, order_id: str) -> OrderVerifyResult:
        from ...db import SessionLocal  # 延迟导入避免循环依赖
        from ...models import ShopOrder

        with SessionLocal() as db:
            order = db.query(ShopOrder).filter(ShopOrder.order_no == order_id).first()
        if order is not None:
            return OrderVerifyResult(is_valid=True, verified_amount_cent=order.total_cent, error="")
        return self._fallback.verify(order_id)