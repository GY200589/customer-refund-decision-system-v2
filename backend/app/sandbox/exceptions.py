"""沙箱异常定义"""


class SandboxError(Exception):
    """沙箱通用异常"""
    pass


class SandboxTimeoutError(SandboxError):
    """沙箱执行超时"""
    pass


class PathEscapeError(SandboxError):
    """路径逃逸检测"""
    pass


class OfficeCLIError(SandboxError):
    """OfficeCLI 操作异常"""
    pass


class CommandInjectionError(OfficeCLIError):
    """命令注入检测"""
    pass


class FileOperationError(OfficeCLIError):
    """文件操作异常"""
    pass