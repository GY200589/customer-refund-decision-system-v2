# sandbox 模块：安全沙箱适配层
#
# 移植自 工单5「Agent评测、成本优化与本地沙箱安全协作系统」
# 提供 Docker 容器隔离 + 进程内 OfficeCLI 双模式文件操作
#
# 使用方式：
#   from app.sandbox import ContainerOfficeCLI
#   cli = ContainerOfficeCLI("/path/to/work_dir")
#   content = cli.read_excel("file.xlsx")

from .adapter import SandboxAdapter
from .container_office_cli import ContainerOfficeCLI
from .exceptions import SandboxError, SandboxTimeoutError, PathEscapeError, OfficeCLIError
from .path_sanitizer import sanitize_path
from .sandbox_manager import SandboxLifecycleManager

__all__ = [
    "SandboxAdapter",
    "ContainerOfficeCLI",
    "SandboxLifecycleManager",
    "sanitize_path",
    "SandboxError",
    "SandboxTimeoutError",
    "PathEscapeError",
    "OfficeCLIError",
]