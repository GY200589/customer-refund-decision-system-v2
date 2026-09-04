"""商品一致性校验 Provider

从投诉文本中提取商品信息，与订单实际购买商品比对，判断一致性。
Mock 实现：关键词启发式判断。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProductConsistencyResult:
    claimed_product: str
    purchased_product: str
    is_match: bool
    risk: str  # HIGH / MEDIUM / LOW


class ProductConsistencyProvider(ABC):
    @abstractmethod
    def check(self, complaint_text: str, order_id: str) -> ProductConsistencyResult:
        ...


class MockProductConsistencyProvider(ProductConsistencyProvider):
    """Mock 商品一致性校验：基于关键词启发式判断。"""

    MATCH_KEYWORDS = ["退款", "退货", "商品", "购买", "收到"]
    MISMATCH_KEYWORDS = ["不是", "不对", "发错", "假冒", "假货", "仿冒"]

    def check(self, complaint_text: str, order_id: str) -> ProductConsistencyResult:
        if not complaint_text:
            return ProductConsistencyResult(
                claimed_product="（无投诉内容）",
                purchased_product="商品#默认",
                is_match=False,
                risk="HIGH",
            )

        text = complaint_text.lower()
        has_mismatch = any(kw in text for kw in self.MISMATCH_KEYWORDS)

        if has_mismatch:
            return ProductConsistencyResult(
                claimed_product="投诉中提及的商品（疑似不一致）",
                purchased_product="商品#默认",
                is_match=False,
                risk="HIGH",
            )

        has_match = any(kw in text for kw in self.MATCH_KEYWORDS)
        if has_match:
            return ProductConsistencyResult(
                claimed_product="投诉中提及的商品",
                purchased_product="商品#默认",
                is_match=True,
                risk="LOW",
            )

        return ProductConsistencyResult(
            claimed_product="投诉中提及的商品（模糊）",
            purchased_product="商品#默认",
            is_match=True,
            risk="MEDIUM",
        )