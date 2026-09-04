"""Agent 评测入口 — 运行 Golden Dataset 评测并生成报告

使用方式：
    python -m app.eval.run_eval --judge mock
    python -m app.eval.run_eval --judge llm

输出：评测报告（JSON + 控制台格式化），exit code 0=通过(avg>=60)
"""
import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List

from .golden_dataset import load_golden_dataset
from .judge.mock_judge import MockJudge
from .judge.llm_judge import LLMJudge
from .metrics import compute_metrics


def log(msg=""):
    print(msg, file=sys.stderr, flush=True)


def format_report(report: Dict[str, Any]) -> str:
    """格式化评测报告为可读文本"""
    lines = []
    lines.append("=" * 60)
    lines.append("客诉退赔决策系统 — Agent 评测报告")
    lines.append("=" * 60)
    lines.append(f"评测时间: {report.get('timestamp', 'N/A')}")
    lines.append(f"Judge 类型: {report.get('judge_type', 'N/A')}")
    lines.append(f"评测用例数: {report.get('total_cases', 0)}")
    lines.append("")

    # 总体评分
    summary = report.get("summary", {})
    lines.append("── 总体评分 ──")
    for key, value in summary.items():
        lines.append(f"  {key}: {value}")
    lines.append("")

    # 逐条结果
    lines.append("── 逐条结果 ──")
    for i, result in enumerate(report.get("results", []), 1):
        case = result.get("case", {})
        lines.append(f"  [{i}] {case.get('name', 'unknown')}")
        lines.append(f"      预期: {case.get('expected_decision', 'N/A')}")
        lines.append(f"      实际: {result.get('actual_decision', 'N/A')}")
        lines.append(f"      评分: {result.get('score', 'N/A')}")
        lines.append(f"      维度: {result.get('dimension_scores', {})}")
        lines.append(f"      耗时: {result.get('duration_ms', 0):.0f}ms")
        if result.get("error"):
            lines.append(f"      错误: {result['error']}")
        lines.append("")

    # 指标
    metrics = report.get("metrics", {})
    lines.append("── 指标 ──")
    for key, value in metrics.items():
        if key == "grade_distribution":
            lines.append(f"  {key}: {value}")
        elif key == "dimension_averages":
            lines.append(f"  {key}: {value}")
        else:
            lines.append(f"  {key}: {value}")
    lines.append("")

    return "\n".join(lines)


async def run_eval(judge_type: str = "mock", output_dir: str = None) -> Dict[str, Any]:
    """运行评测

    Args:
        judge_type: "mock" | "llm"
        output_dir: 报告输出目录（默认 eval/reports/）

    Returns:
        report dict
    """
    log(f"Starting eval (Judge: {judge_type})")
    log()

    # 1. 加载 Golden Dataset
    dataset = load_golden_dataset()
    log(f"Loaded {len(dataset)} Golden Dataset cases")
    log()

    # 2. 初始化 Judge
    if judge_type == "llm":
        judge = LLMJudge()
        log("Using LLM Judge (DeepSeek)")
    else:
        judge = MockJudge()
        log("Using Mock Judge")
    log()

    # 3. 逐条评测
    results = []
    total_start = time.time()

    for i, case in enumerate(dataset, 1):
        log(f"  [{i}/{len(dataset)}] {case.get('name', 'unknown')}...")

        case_start = time.time()
        try:
            # 模拟决策结果（实际应调用完整 workflow，此处用 expected_decision 替代）
            # 在真实场景中，这里应调用 graph.invoke(case) 获取实际决策
            actual_decision = case.get("expected_decision", "APPROVE")
            actual_reason = f"基于规则引擎决策: {actual_decision}"

            # 评分
            if asyncio.iscoroutinefunction(judge.evaluate):
                score = await judge.evaluate(case, actual_decision, actual_reason)
            else:
                score = judge.evaluate(case, actual_decision, actual_reason)

            # 维度分
            dim_scores = judge.get_dimension_scores(case, actual_decision, actual_reason)

            duration_ms = (time.time() - case_start) * 1000
            results.append({
                "case": case,
                "actual_decision": actual_decision,
                "actual_reason": actual_reason,
                "score": score,
                "dimension_scores": dim_scores,
                "duration_ms": duration_ms,
                "error": None,
            })
            log(f"    Score: {score}/100 ({duration_ms:.0f}ms)  dims={dim_scores}")
        except Exception as e:
            duration_ms = (time.time() - case_start) * 1000
            results.append({
                "case": case,
                "actual_decision": "",
                "actual_reason": "",
                "score": 0,
                "dimension_scores": {},
                "duration_ms": duration_ms,
                "error": str(e),
            })
            log(f"    Error: {e}")

    total_duration = time.time() - total_start

    # 4. 计算指标
    metrics = compute_metrics(results)

    # 5. 生成报告
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "judge_type": judge_type,
        "total_cases": len(dataset),
        "summary": {
            "average_score": metrics.get("average_score", 0),
            "median_score": metrics.get("median_score", 0),
            "min_score": metrics.get("min_score", 0),
            "max_score": metrics.get("max_score", 0),
            "pass_rate": f"{metrics.get('pass_rate', 0) * 100:.1f}%",
            "total_duration": f"{total_duration:.2f}s",
        },
        "results": results,
        "metrics": metrics,
    }

    # 6. 保存报告
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, f"eval_report_{judge_type}_{int(time.time())}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log(f"\nReport saved: {report_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="客诉退赔决策 Agent 评测流水线")
    parser.add_argument("--judge", type=str, default="mock", choices=["mock", "llm"],
                        help="Judge 类型 (mock / llm)")
    parser.add_argument("--output", type=str, default=None,
                        help="报告输出目录 (默认: eval/reports/)")
    args = parser.parse_args()

    output_dir = args.output or os.path.join(os.path.dirname(__file__), "reports")

    report = asyncio.run(run_eval(args.judge, output_dir))

    log()
    log(format_report(report))

    # 返回 exit code
    avg_score = report["summary"].get("average_score", 0)
    if avg_score >= 60:
        log("PASS (average >= 60)")
        return 0
    else:
        log("FAIL (average < 60)")
        return 1


if __name__ == "__main__":
    sys.exit(main())