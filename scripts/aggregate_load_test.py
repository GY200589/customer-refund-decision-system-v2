"""汇总 Locust 各阶段 CSV，生成 reports/负载测试报告.md + .json。

用法：python scripts/aggregate_load_test.py reports
读取 reports/loadtest_{N}users_stats.csv（每阶段一个），提取：
    - 总吞吐（Requests/s，即 QPS）
    - P95（95% 列，取 Aggregate 行）
    - 错误率（Failure Count / Request Count）
"""
import csv
import glob
import json
import os
import re
import sys


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_stats_csv(path: str) -> dict:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    # 找 Aggregate 行（Locust 汇总行的 Name == "Aggregated"，Type 列留空）
    agg = next((r for r in rows if r.get("Name") == "Aggregated"), None)
    if agg is None:
        return {}
    req = int(_num(agg.get("Request Count", 0)))
    fail = int(_num(agg.get("Failure Count", 0)))
    rps = _num(agg.get("Requests/s", 0))
    p95 = _num(agg.get("95%", 0))  # 空阶段为 N/A -> 0
    median = _num(agg.get("Median Response Time", 0))
    avg = _num(agg.get("Average Response Time", 0))
    err_rate = (fail / req * 100) if req else 0.0
    return {
        "requests": req,
        "failures": fail,
        "rps": round(rps, 1),
        "p95_ms": round(p95, 1),
        "median_ms": round(median, 1),
        "avg_ms": round(avg, 1),
        "error_rate_pct": round(err_rate, 3),
    }


def main(report_dir: str):
    pattern = os.path.join(report_dir, "loadtest_*users_stats.csv")
    files = sorted(
        glob.glob(pattern),
        key=lambda p: int(re.search(r"loadtest_(\d+)users", p).group(1)),
    )
    if not files:
        print(f"未找到 {pattern}，请先运行 scripts/run_load_test.sh")
        sys.exit(1)

    stages = []
    for path in files:
        users = int(re.search(r"loadtest_(\d+)users", path).group(1))
        data = parse_stats_csv(path)
        data["users"] = users
        stages.append(data)
        print(f"  {users} users: QPS={data['rps']}  P95={data['p95_ms']}ms  "
              f"err={data['error_rate_pct']}%  ({data['requests']} reqs)")

    # 验收判定：QPS>=200 且 P95<300ms 且 错误率<0.1%
    verdicts = []
    for s in stages:
        ok_qps = s["rps"] >= 200
        ok_p95 = s["p95_ms"] < 300
        ok_err = s["error_rate_pct"] < 0.1
        verdicts.append({"users": s["users"], "qps_ok": ok_qps, "p95_ok": ok_p95, "err_ok": ok_err})

    # 写 JSON
    json_path = os.path.join(report_dir, "负载测试报告.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"stages": stages, "verdicts": verdicts}, f, ensure_ascii=False, indent=2)

    # 写 Markdown
    md_path = os.path.join(report_dir, "负载测试报告.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 负载测试报告\n\n")
        f.write("> 工具：Locust；目标：客诉舆情退赔决策系统（真实端点 `/api/v1/*`）。\n\n")
        f.write("## 测试环境\n\n")
        f.write("- 后端：FastAPI（uvicorn 多 worker ×4）+ PostgreSQL + Redis(redis-stack)\n")
        f.write("- 容器资源限制：backend 4 CPU / 2G，postgres 8 CPU / 2G，worker 4 CPU / 1G，redis 2 CPU / 1G\n")
        f.write("- 场景：A 建案 / B 查询 / C 审批 / D 大盘（见 loadtest/locustfile.py）\n\n")
        f.write("## 分阶结果\n\n")
        f.write("| 并发用户 | QPS (req/s) | P95 (ms) | 中位数 (ms) | 平均 (ms) | 错误率 | 总请求 |\n")
        f.write("|---------|------------|----------|-------------|-----------|--------|--------|\n")
        for s in stages:
            f.write(
                f"| {s['users']} | {s['rps']} | {s['p95_ms']} | {s['median_ms']} | "
                f"{s['avg_ms']} | {s['error_rate_pct']}% | {s['requests']} |\n"
            )
        f.write("\n## 验收判定（QPS≥200 且 P95<300ms 且 错误率<0.1%）\n\n")
        f.write("| 并发用户 | QPS 达标 | P95 达标 | 错误率达标 |\n")
        f.write("|---------|---------|---------|-----------|\n")
        for v in verdicts:
            mark = lambda b: "✅" if b else "❌"  # noqa: E731
            f.write(f"| {v['users']} | {mark(v['qps_ok'])} | {mark(v['p95_ok'])} | {mark(v['err_ok'])} |\n")
        f.write("\n> 说明：QPS 为 Aggregate 行的 Requests/s；P95 取 Aggregate 行 95% 分位。\n")

    print(f"\n已生成 {md_path} 与 {json_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports")
