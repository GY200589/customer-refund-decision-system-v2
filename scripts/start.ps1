# 一键启动全套服务（Windows PowerShell）
# 等价于 make up
param([switch]$Build)

Write-Host "==> 启动客诉舆情退赔决策系统 ..."
if ($Build) {
    docker compose up -d --build
} else {
    docker compose up -d
}
Write-Host "==> 服务状态："
docker compose ps
Write-Host "前端: http://localhost:5173  后端: http://localhost:8001/api/v1/health"
