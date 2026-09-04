"""ContainerOfficeCLI — 在受限 Docker 容器内解析 Word/Excel

与 OfficeCLI 接口一致，但把文件解析（python-docx / openpyxl）放到受限
Docker 容器进程内执行，宿主进程不直接解析文件，满足「文件读写 100% 在
沙箱内完成」红线（R1 / P1-3）。

隔离手段（每次 ``docker run --rm`` 一次性容器）：
- ``--network none``：禁网
- ``--read-only``：根文件系统只读
- ``--user 1000:1000``：非 root
- ``--cap-drop ALL`` + ``no-new-privileges``：最小权限
- ``--cpus/--memory``：资源上限
- 仅挂载沙箱工作目录（``data/``）到 ``/sandbox``，容器无法触及宿主机其他路径

无 Docker / 无沙箱镜像时，由 harness 降级到进程内 OfficeCLI（见
harness._init_tool_map），本类只负责「容器路径」。
"""

import json
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .exceptions import OfficeCLIError

logger = logging.getLogger(__name__)

# 沙箱镜像名（可由环境变量覆盖）
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "agent-sandbox:latest")

# Docker 可用性缓存（避免每次请求都探测 docker image inspect）
_availability_cache: Optional[bool] = None


class ContainerOfficeCLI:
    """在受限 Docker 容器内做 Word/Excel 文件操作。"""

    def __init__(self, sandbox_work_dir: str = "data", image: Optional[str] = None,
                 timeout: int = 30):
        self._work_dir = os.path.abspath(sandbox_work_dir)
        self._image = image or SANDBOX_IMAGE
        self._timeout = timeout

    @classmethod
    def is_available(cls) -> bool:
        """判断 Docker CLI 与沙箱镜像是否就绪（结果缓存）。"""
        global _availability_cache
        if _availability_cache is None:
            _availability_cache = cls._check_available()
        return _availability_cache

    @staticmethod
    def _check_available() -> bool:
        if shutil.which("docker") is None:
            return False
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", SANDBOX_IMAGE],
                capture_output=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    # ── 容器执行核心 ──────────────────────────────────────

    def _run(self, op: str, rel_path: str, stdin_data: Optional[str] = None) -> dict:
        """在一次性受限容器内执行解析，返回 runner 的 JSON payload。"""
        # 注意：Docker Desktop for Windows (WSL2) 下 --workdir 会解析到宿主机路径
        # 导致错误 "the working directory 'D:/Git/sandbox' is invalid"
        # 因此不使用 --workdir，而是将数据目录挂载为 /sandbox/data 子目录
        # 容器内 runner 在 /sandbox/ 下，数据在 /sandbox/data/ 下
        docker_args = [
            "docker", "run", "--rm",
            "--interactive",  # 保持 stdin 开放，确保 write_* 操作能读取管道数据
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--user", "1000:1000",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--cpus", "1.0",
            "--memory", "512m",
            "--memory-swap", "512m",
            "--volume", f"{self._work_dir}:/sandbox/data:rw",
            self._image,
            op, f"data/{rel_path}",
        ]
        try:
            result = subprocess.run(
                docker_args, input=stdin_data, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self._timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            raise OfficeCLIError(f"沙箱操作超时: {op} {rel_path!r}")
        except FileNotFoundError:
            raise OfficeCLIError("Docker 不可用，无法执行容器沙箱操作")

        # 先解析 runner 的 JSON 输出（即便退出码非 0 也含错误信息）
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            detail = (result.stderr or result.stdout or "").strip()[:300]
            raise OfficeCLIError(f"沙箱输出解析失败 {op} {rel_path!r}: {detail}")

        if not payload.get("ok") or result.returncode != 0:
            raise OfficeCLIError(f"沙箱 {op} 失败 {rel_path!r}: {payload.get('error') or '未知错误'}")
        return payload

    # ── 与 OfficeCLI 一致的接口 ────────────────────────────

    def read_word(self, file_path: str) -> str:
        payload = self._run("read_word", file_path)
        return payload.get("result", "")

    def read_excel(self, file_path: str, sheet_name: Optional[str] = None) -> List[Dict[str, Any]]:
        # MVP：读取默认 sheet（当前流程不传 sheet_name）
        payload = self._run("read_excel", file_path)
        return payload.get("result", [])

    def write_word(self, file_path: str, content: str) -> str:
        self._run("write_word", file_path, stdin_data=content)
        return os.path.join(self._work_dir, file_path)

    def write_excel(self, file_path: str, data: List[Dict[str, Any]],
                    sheet_name: str = "Sheet1") -> str:
        self._run("write_excel", file_path, stdin_data=json.dumps(data, ensure_ascii=False))
        return os.path.join(self._work_dir, file_path)
