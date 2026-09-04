"""沙箱生命周期管理器

管理沙箱的创建、执行和销毁全生命周期。
保证：正常、异常、超时三种路径都销毁实例。
"""

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional, TypeVar

from .adapter import SandboxAdapter
from .exceptions import SandboxError, SandboxTimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SandboxLifecycleManager:
    """沙箱生命周期管理器。

    封装 try/finally 模式，确保沙箱在任何情况下都被销毁。
    """

    def __init__(self, adapter_factory: Callable[[], SandboxAdapter]):
        self._factory = adapter_factory
        self._adapter: Optional[SandboxAdapter] = None

    @property
    def adapter(self) -> Optional[SandboxAdapter]:
        return self._adapter

    async def run_in_sandbox(
        self,
        task_func: Callable[[SandboxAdapter], T],
        config: Optional[Dict[str, Any]] = None,
        timeout: int = 60,
    ) -> T:
        """在沙箱中执行任务，确保结束后销毁沙箱。

        Args:
            task_func: 需要沙箱的任务函数，接收 SandboxAdapter 参数。
            config: 沙箱创建配置。
            timeout: 任务超时秒数。

        Returns:
            任务函数返回值。

        Raises:
            SandboxTimeoutError: 任务超时。
            SandboxError: 沙箱相关错误。
        """
        config = config or {}
        self._adapter = self._factory()
        start_time = time.time()

        try:
            # 创建沙箱
            logger.info("创建沙箱: id=%s", self._adapter.sandbox_id)
            self._adapter.create(config)
            logger.info("沙箱创建成功: id=%s", self._adapter.sandbox_id)

            # 执行任务（带超时）
            try:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, task_func, self._adapter),
                    timeout=timeout,
                )
                elapsed = time.time() - start_time
                logger.info("沙箱任务完成: id=%s elapsed=%.2fs", self._adapter.sandbox_id, elapsed)
                return result

            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                logger.error(
                    "沙箱任务超时: id=%s timeout=%ds elapsed=%.2fs",
                    self._adapter.sandbox_id, timeout, elapsed,
                )
                raise SandboxTimeoutError(
                    f"沙箱任务超时 (timeout={timeout}s)"
                )

        except SandboxError:
            raise
        except Exception as e:
            logger.error("沙箱任务异常: id=%s error=%s", self._adapter.sandbox_id, e)
            raise SandboxError(f"沙箱任务异常: {e}") from e
        finally:
            # 三路径销毁：正常/异常/超时
            self._destroy_sandbox()

    def run_in_sandbox_sync(
        self,
        task_func: Callable[[SandboxAdapter], T],
        config: Optional[Dict[str, Any]] = None,
        timeout: int = 60,
    ) -> T:
        """同步版本的沙箱任务执行。

        Args:
            task_func: 需要沙箱的任务函数。
            config: 沙箱创建配置。
            timeout: 任务超时秒数。

        Returns:
            任务函数返回值。
        """
        config = config or {}
        self._adapter = self._factory()

        try:
            logger.info("创建沙箱(同步): id=%s", self._adapter.sandbox_id)
            self._adapter.create(config)
            logger.info("沙箱创建成功(同步): id=%s", self._adapter.sandbox_id)

            # 同步执行，手动实现超时
            from concurrent.futures import ThreadPoolExecutor, TimeoutError

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(task_func, self._adapter)
                try:
                    result = future.result(timeout=timeout)
                    logger.info("沙箱任务完成(同步): id=%s", self._adapter.sandbox_id)
                    return result
                except TimeoutError:
                    logger.error(
                        "沙箱任务超时(同步): id=%s timeout=%ds",
                        self._adapter.sandbox_id, timeout,
                    )
                    raise SandboxTimeoutError(
                        f"沙箱任务超时 (timeout={timeout}s)"
                    )

        except SandboxError:
            raise
        except Exception as e:
            logger.error("沙箱任务异常(同步): id=%s error=%s", self._adapter.sandbox_id, e)
            raise SandboxError(f"沙箱任务异常: {e}") from e
        finally:
            self._destroy_sandbox()

    def _destroy_sandbox(self) -> None:
        """销毁沙箱（幂等）。"""
        if self._adapter is not None:
            try:
                self._adapter.destroy()
                logger.info("沙箱已销毁: id=%s", self._adapter.sandbox_id)
            except Exception as e:
                logger.error("沙箱销毁失败: id=%s error=%s", self._adapter.sandbox_id, e)
            finally:
                self._adapter = None