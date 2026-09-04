# Phase 00 — 仓库与环境审计

- 日期：2026-08-18
- 阶段目标：只读检查宿主环境与仓库初始状态，确定可行的验证方式，不写业务代码。

## 1. 环境检查结果

| 组件 | 状态 | 版本 / 说明 |
|---|---|---|
| 操作系统 | 可用 | Windows 11 Home China (build 10.0.26200) |
| Shell | 可用 | bash（Unix 语法，Windows 宿主） |
| Python | 可用 | `python` = 3.11.15；`python3` = 3.12.10 |
| Node.js | 可用 | v24.16.0 |
| npm | 可用 | 11.13.0 |
| Docker | 可用 | 28.3.2（build 578ccf6） |
| Docker Compose | 可用 | v2.39.1-desktop.1 |
| Git | 可用 | 2.54.0.windows.1 |
| redis-cli | 不在 PATH | 通过 Docker 容器内使用 |
| psql | 不在 PATH | 通过 Docker 容器内使用 |

## 2. 仓库初始状态

- 目标目录：`D:\桌面\多Agent 协同项目 - 客诉舆情退赔决策系统deepseek`
- 初始内容：空目录（无既有代码、无未提交修改、无用户文件）。

## 3. 依赖与模型可用性

| 依赖 | 结论 |
|---|---|
| PostgreSQL | 宿主未安装，改用 `docker compose` 提供 `postgres:16` |
| Redis | 宿主未安装，改用 `docker compose` 提供 `redis:7` |
| PaddleOCR | 未安装；MVP 采用确定性 Mock OCR 提供者，保留 `PaddleOcrProvider` 真实实现接口（可选安装） |
| Ollama / 本地 LLM | 未安装；MVP 采用确定性 Mock LLM 提供者，保留 `OllamaProvider` 真实实现接口 |

## 4. 验证方式决策

- 后端单元测试：`pytest`（在 Docker `backend`/`worker` 镜像内运行，不依赖真实大模型，使用 FakeProvider）。
- 全套服务联调：`docker compose up -d`，通过健康检查确认各服务可用。
- 前端构建：`npm run build`（Vite 产物）。
- 压力测试：Locust 对 `POST /api/v1/cases` 等快速接口施压，如实记录本机 Docker 单机数据，不表述为生产容量承诺。

## 5. 风险与结论

- Windows 宿主无原生 `redis-cli`/`psql`，但不阻塞，全部走 Docker。
- 真实 PaddleOCR / Ollama 模型体积大、下载慢，本轮不联网下载，以 Mock 提供者 + 可切换接口交付。
- 本机单核 Docker 压测结果仅代表演示环境，不作为生产容量承诺。

**结论：环境满足“构建 + docker 完整验证”的要求，进入第 1 阶段（项目骨架）。**
