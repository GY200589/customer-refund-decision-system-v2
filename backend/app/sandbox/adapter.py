"""SandboxAdapter 抽象基类

定义沙箱的统一接口：
- create: 创建沙箱实例
- run: 在沙箱中执行任务
- destroy: 销毁沙箱实例（必须幂等）
- read_file / write_file: 沙箱内文件读写

所有实现必须遵循：
- try/finally 生命周期，正常/异常/超时三路径销毁
- 宿主机只映射 data 目录
- 非 root、禁网、最小权限
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SandboxAdapter(ABC):
    """沙箱适配器抽象基类。"""

    def __init__(self, sandbox_id: Optional[str] = None):
        self.sandbox_id = sandbox_id or "unknown"
        self._created = False

    @abstractmethod
    def create(self, config: Optional[Dict[str, Any]] = None) -> str:
        """创建沙箱实例。

        Args:
            config: 沙箱配置（挂载目录、资源限制、超时等）。

        Returns:
            沙箱 ID。

        Raises:
            SandboxCreationError: 创建失败。
        """
        ...

    @abstractmethod
    def run(
        self,
        command: str,
        args: Optional[list] = None,
        timeout: int = 60,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """在沙箱内执行命令。

        Args:
            command: 命令名称。
            args: 参数数组（禁止 shell=True）。
            timeout: 超时秒数。
            env: 环境变量。

        Returns:
            {"stdout": str, "stderr": str, "return_code": int, "timed_out": bool}
        """
        ...

    @abstractmethod
    def read_file(self, file_path: str) -> bytes:
        """从沙箱读取文件。

        Args:
            file_path: 沙箱内文件路径。

        Returns:
            文件内容。
        """
        ...

    @abstractmethod
    def write_file(self, file_path: str, content: bytes) -> str:
        """向沙箱写入文件。

        Args:
            file_path: 沙箱内文件路径。
            content: 文件内容。

        Returns:
            沙箱内完整路径。
        """
        ...

    @abstractmethod
    def destroy(self) -> bool:
        """销毁沙箱实例。必须幂等，可重复调用。

        Returns:
            True 表示销毁成功，False 表示已销毁无需操作。
        """
        ...

    @property
    def is_created(self) -> bool:
        return self._created

    def __enter__(self):
        """Context manager 进入。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager 退出，确保销毁。"""
        self.destroy()
        return False  # 不吞异常