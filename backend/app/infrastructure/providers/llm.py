import json
from abc import ABC, abstractmethod

import httpx


class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, prompt: str) -> dict:
        """返回结构化 dict，失败时抛异常，由上层做降级转人工。"""
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    def complete_json(self, prompt: str) -> dict:
        # 确定性返回，便于测试
        return {"text": "mock", "score": 0.5}


class OllamaLLMProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, timeout: float = 20.0):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def complete_json(self, prompt: str) -> dict:
        try:
            resp = httpx.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return json.loads(resp.json()["response"])
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Ollama 调用失败: {exc}") from exc
