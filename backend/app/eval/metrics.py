"""评测指标计算

计算指标：
- 平均分 / 中位数 / 最小 / 最大 / 标准差
- 通过率（score >= 60）
- 等级分布（S/A/B/C/D）
- 各维度平均分
"""
import statistics
from typing import Any, Dict, List


def compute_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算评测指标"""
    if not results:
        return {}

    scores = [r.get("score", 0) for r in results]
    durations = [r.get("duration_ms", 0) for r in results]
    errors = [r for r in results if r.get("error")]

    # 维度分收集
    dim_scores = {}
    for r in results:
        dims = r.get("dimension_scores", {})
        for k, v in dims.items():
            dim_scores.setdefault(k, []).append(v)

    metrics: Dict[str, Any] = {
        "average_score": statistics.mean(scores) if scores else 0,
        "median_score": statistics.median(scores) if len(scores) > 1 else scores[0] if scores else 0,
        "min_score": min(scores) if scores else 0,
        "max_score": max(scores) if scores else 0,
        "std_dev_score": statistics.stdev(scores) if len(scores) > 1 else 0,
        "pass_rate": sum(1 for s in scores if s >= 60) / len(scores) if scores else 0,
        "average_duration_ms": statistics.mean(durations) if durations else 0,
        "total_duration_ms": sum(durations),
        "error_count": len(errors),
        "error_rate": len(errors) / len(results) if results else 0,
    }

    # 维度平均分
    if dim_scores:
        metrics["dimension_averages"] = {k: statistics.mean(v) for k, v in dim_scores.items()}

    # 等级分布
    grades = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    for s in scores:
        if s >= 90:
            grades["S"] += 1
        elif s >= 80:
            grades["A"] += 1
        elif s >= 70:
            grades["B"] += 1
        elif s >= 60:
            grades["C"] += 1
        else:
            grades["D"] += 1
    metrics["grade_distribution"] = grades

    return metrics