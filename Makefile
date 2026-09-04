# 跨平台任务入口（Windows 无 make 时，等价命令见 scripts/ 下的 PS1/sh 脚本）
SHELL := /bin/bash

.PHONY: help up down logs ps test build audit reset

help:
	@echo "make up       - docker compose 启动全套服务"
	@echo "make down     - 停止并移除容器"
	@echo "make logs     - 查看服务日志"
	@echo "make ps       - 查看服务状态"
	@echo "make test     - 运行后端单元测试"
	@echo "make build    - 构建前端产物"
	@echo "make audit    - 生成安全审计报告占位"
	@echo "make reset    - 停止并清理卷（危险，会删除数据）"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

test:
	docker compose run --rm backend pytest -q

build:
	cd frontend && npm install && npm run build

reset:
	docker compose down -v
