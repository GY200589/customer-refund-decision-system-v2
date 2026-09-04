"""语音识别 Provider（定稿 §4.8）。

- mock：不伪造真实转写——返回明确标注 demo 的预设文本，前端按"演示模式"展示（C11）；
- dashscope：阿里云百炼多模态同步接口（Qwen3-ASR-Flash），浏览器录音以
  Data URL 传入，密钥只从 DASHSCOPE_API_KEY 读取。

所有失败统一抛 ASRError，路由层转 503 并保证文字输入始终可用。
"""
from abc import ABC, abstractmethod
import base64

import httpx


class ASRError(RuntimeError):
    """语音服务不可用/调用失败，路由层据此返回 503。"""


class ASRProvider(ABC):
    name = "base"

    @abstractmethod
    def transcribe(self, audio: bytes, mime: str) -> dict:
        """返回 {text, provider, demo}；失败抛 ASRError。"""
        raise NotImplementedError


class MockASRProvider(ASRProvider):
    """演示模式：明确标记 demo=True 的预设文本，绝不伪装成真实云端转写。"""

    name = "mock"

    def transcribe(self, audio: bytes, mime: str) -> dict:
        return {
            "text": "（演示模式，未接入真实语音服务）这条裤子上身有点紧，帮我申请退款",
            "provider": "mock",
            "demo": True,
        }


_MIME_EXT = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/ogg": "ogg",
}


class DashScopeASRProvider(ASRProvider):
    """阿里云百炼 Qwen3-ASR-Flash 同步转写接口。"""

    name = "dashscope"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def transcribe(self, audio: bytes, mime: str) -> dict:
        if not self.api_key:
            raise ASRError("语音服务未配置：缺少 DASHSCOPE_API_KEY")
        # 浏览器通常发送 audio/webm;codecs=opus，扩展名判断只取 MIME 主类型。
        normalized_mime = (mime or "audio/wav").split(";", 1)[0].strip().lower()
        _MIME_EXT.get(normalized_mime, "wav")  # 同时校验常见浏览器音频类型
        audio_url = f"data:{normalized_mime};base64,{base64.b64encode(audio).decode('ascii')}"
        try:
            resp = httpx.post(
                f"{self.base_url}/services/aigc/multimodal-generation/generation",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "X-DashScope-SSE": "disable",
                },
                json={
                    "model": self.model,
                    "input": {
                        "messages": [
                            {"role": "user", "content": [{"audio": audio_url}]},
                        ]
                    },
                    "parameters": {"asr_options": {"enable_itn": True}},
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ASRError(f"语音服务调用失败: {exc}") from exc

        if resp.status_code in (401, 403):
            raise ASRError("语音服务鉴权失败，请检查 DASHSCOPE_API_KEY")
        if resp.status_code >= 400:
            raise ASRError(f"语音服务返回错误（HTTP {resp.status_code}）")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ASRError("语音服务返回了无法解析的数据") from exc

        output = payload.get("output") or {}
        nested = output.get("output") or {}
        sentence = nested.get("sentence") or {}
        text = output.get("text") or sentence.get("text") or payload.get("text") or ""
        if not text:
            choices = output.get("choices") or payload.get("choices") or []
            if choices:
                content = ((choices[0].get("message") or {}).get("content") or "")
                if isinstance(content, list):
                    text = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
                else:
                    text = str(content)
        text = str(text).strip()
        if not text:
            raise ASRError("语音服务未返回转写文本")
        return {"text": text, "provider": "dashscope", "demo": False}
