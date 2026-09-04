"""LLMJudge — 使用大模型 API 进行 LLM-as-a-judge 评分

三维度评分（面向客诉退赔决策领域）：
- 决策正确性 (0-40分): 预期决策是否与实际决策一致
- 金额边界安全 (0-30分): 是否正确处理金额阈值边界
- 理由质量 (0-30分): 决策理由是否清晰、完整、合规

API Key 通过环境变量 DEEPSEEK_API_KEY 配置，无 key 时降级到 MockJudge。
"""
import json
import os
import re
from typing import Any, Dict, Optional

from .base import BaseJudge


class LLMJudge(BaseJudge):
    """LLM Judge — 使用大模型 API 评分"""

    def __init__(self, api_key: str = "", model: str = "deepseek-chat", base_url: str = ""):
        super().__init__()
        self.name = "llm"
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model

        try:
            import httpx
            self.client = httpx.AsyncClient(timeout=60.0)
            self.available = bool(self.api_key)
        except ImportError:
            self.client = None
            self.available = False

        if not self.available:
            print("⚠️  LLM Judge 不可用: 缺少 API Key 或 httpx 库")

    def _build_judge_prompt(self, case: Dict[str, Any], actual_decision: str, actual_reason: str) -> str:
        """构建 Judge 评分 prompt"""
        prompt = f"""你是一个专业的客诉退赔决策系统评测员。请对以下决策结果进行评分（0-100分）。

## 测试用例
- 名称: {case.get('name', 'unknown')}
- 描述: {case.get('description', 'N/A')}
- 金额: {case.get('amount_cent', 0)} 分
- 投诉文本: {case.get('complaint_text', 'N/A')}
- 风险信号: {case.get('risk_flags', {})}
- 证据齐全: {case.get('evidence_present', False)}
- OCR 置信度: {case.get('ocr_confidence', 0.0)}

## 预期决策
{case.get('expected_decision', 'N/A')}

## 实际决策
{actual_decision}

## 决策理由
{actual_reason or 'N/A'}

## 评分标准（三维度，总分 100）
1. **决策正确性 (0-40分)**: 实际决策是否与预期一致？场景判断是否合理？
2. **金额边界安全 (0-30分)**: 金额阈值（30000分=人工审核线）是否被正确处理？大额转人工、小额自动批准的逻辑是否正确？
3. **理由质量 (0-30分)**: 决策理由是否清晰、完整、有依据？是否涵盖了关键风险因素？

请以 JSON 格式返回评分结果：
```json
{{
    "decision_accuracy": 0-40,
    "amount_boundary": 0-30,
    "reason_quality": 0-30,
    "total": 0-100,
    "feedback": "简短的评分理由"
}}
```"""
        return prompt

    async def evaluate(self, case: Dict[str, Any], actual_decision: str, actual_reason: str = "") -> float:
        """使用 LLM 评测"""
        if not self.available:
            from .mock_judge import MockJudge
            mock = MockJudge()
            return mock.evaluate(case, actual_decision, actual_reason)

        try:
            prompt = self._build_judge_prompt(case, actual_decision, actual_reason)

            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "你是一个专业的客诉退赔决策系统评测员，以 JSON 格式返回评分结果。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 500,
            }

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                json=data,
                headers=headers,
            )

            if response.status_code != 200:
                print(f"⚠️  LLM API 返回 {response.status_code}: {response.text[:200]}")
                return 50.0

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # 提取 JSON
            json_match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
            if json_match:
                scores = json.loads(json_match.group(1))
            else:
                scores = json.loads(content)

            return float(scores.get("total", 50.0))

        except Exception as e:
            print(f"⚠️  LLM Judge 评分失败: {e}")
            return 50.0

    async def close(self):
        """关闭客户端"""
        if self.client:
            await self.client.aclose()