"""男装图片视觉分类 Provider（定稿 §4.3 / Phase 5）。

- mock：不伪装识别能力——返回 unknown + needs_review=True 的占位结果，等待
  真实模型接入（Ollama qwen3-vl / qwen2.5vl）；
- ollama_vl：本地 Ollama 视觉模型，输出 main_category / sub_category /
  confidence / attributes，标签必须落在固定分类树内，非法值归 unknown；
  置信度低于阈值或标签未知 → needs_review=True，永不自动覆盖商品主分类。
"""
import base64
import json
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

VALID_MAIN = {"top", "bottom"}
VALID_SUB = {
    "tshirt", "shirt", "hoodie", "jacket", "padded",
    "jeans", "casual_pants", "suit_pants", "cargo_pants", "joggers", "shorts",
}

_PROMPT = (
    "你是男装商品分类助手。看图分类并只输出 JSON："
    '{"main_category": "top|bottom|unknown", '
    '"sub_category": "tshirt|shirt|hoodie|jacket|padded|jeans|casual_pants|suit_pants|cargo_pants|joggers|shorts|unknown", '
    '"attributes": {"color": "颜色", "pattern": "纯色/印花/条纹", "length": "长裤/九分/七分/短裤/上衣"}, '
    '"confidence": 0到1的小数}。'
    "规则：上装主图 main_category=top；裤子主图=bottom；无法判断用 unknown。"
    "一张图同时出现上衣和裤子时，以占画面更大的服装为准并在 attributes 中备注另一件。"
)


class VisionProvider(ABC):
    name = "base"

    @abstractmethod
    def classify(self, image_path: str) -> dict:
        raise NotImplementedError


class MockVisionProvider(VisionProvider):
    """演示占位：明确 needs_review，等待真实模型/图片接入。"""

    name = "mock"

    def classify(self, image_path: str) -> dict:
        return {
            "main_category": "unknown",
            "sub_category": "unknown",
            "confidence": 0.0,
            "attributes": {},
            "needs_review": True,
            "provider": "mock",
            "demo": True,
        }


class OllamaVisionProvider(VisionProvider):
    name = "ollama_vl"

    def __init__(self, base_url: str, model: str, threshold: float, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.threshold = threshold
        self.timeout = timeout

    def classify(self, image_path: str) -> dict:
        path = Path(image_path)
        if not path.exists():
            raise RuntimeError(f"图片不存在: {image_path}")
        image_b64 = base64.b64encode(path.read_bytes()).decode()
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": _PROMPT, "images": [image_b64]}],
                    "stream": False,
                    "format": "json",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            payload = json.loads(content)
        except Exception as exc:  # noqa: BLE001  模型/网络失败由上层标 needs_review
            raise RuntimeError(f"Ollama 视觉模型调用失败: {exc}") from exc

        main_category = payload.get("main_category", "unknown")
        sub_category = payload.get("sub_category", "unknown")
        if main_category not in VALID_MAIN:
            main_category = "unknown"
        if sub_category not in VALID_SUB:
            sub_category = "unknown"
        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return {
            "main_category": main_category,
            "sub_category": sub_category,
            "confidence": round(confidence, 2),
            "attributes": payload.get("attributes") or {},
            "needs_review": confidence < self.threshold or main_category == "unknown",
            "provider": self.name,
            "demo": False,
        }
