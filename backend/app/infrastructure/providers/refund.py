from abc import ABC, abstractmethod


class RefundProvider(ABC):
    @abstractmethod
    def execute(self, case_id: str, amount_cent: int, idempotency_key: str) -> str:
        """执行退款，返回退款流水号。真实实现应接入支付网关。"""
        raise NotImplementedError


class MockRefundProvider(RefundProvider):
    def execute(self, case_id: str, amount_cent: int, idempotency_key: str) -> str:
        # 无真实支付凭证，只返回可替换的 mock 流水号，不调用真实退款接口
        return f"mock-refund-{case_id}"
