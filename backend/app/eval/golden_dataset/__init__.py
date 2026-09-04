"""Golden Dataset — 客诉退赔领域评测用例（13 条）

统一数据源在 dataset.py（10 条业务场景 + 3 条工单6安全场景）。
此处仅 re-export，避免两处定义不同步导致安全用例不生效。
"""
from typing import Any, Dict, List

from .dataset import load_golden_dataset

__all__ = ["load_golden_dataset"]
