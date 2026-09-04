"""OfficeCLI 封装

使用 python-docx 和 openpyxl 作为 OfficeCLI 的 MVP 实现。
所有操作在沙箱内完成，不涉及宿主机直接文件操作。

强制规则：
- 所有外部命令使用参数数组，禁止 shell=True
- 用户内容只作参数，不拼接命令
- 路径必须经过 sanitize 检查
"""

import logging
import os
from typing import Any, Dict, List, Optional, Union

from .exceptions import CommandInjectionError, FileOperationError, OfficeCLIError
from .path_sanitizer import sanitize_path, validate_input_path, validate_output_path

from src.agent import register_tool  # 注册工具到全局注册表

logger = logging.getLogger(__name__)

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {".docx", ".xlsx", ".xls"}


class OfficeCLI:
    """OfficeCLI 封装层。

    提供 Word/Excel 文件的读取、解析、修改和写回功能。
    所有文件操作路径必须经过安全检查。
    """

    def __init__(self, sandbox_work_dir: str = "/sandbox"):
        self._work_dir = sandbox_work_dir

    # ── Word 操作 ──────────────────────────────────────────

    @register_tool("read_word")
    def read_word(self, file_path: str) -> str:
        """读取 Word 文档内容。

        Args:
            file_path: 沙箱内的文件路径（相对沙箱工作目录）。

        Returns:
            文档文本内容。

        Raises:
            OfficeCLIError: 读取失败或格式错误。
        """
        safe_path = self._resolve_sandbox_path(file_path, ".docx")
        try:
            from docx import Document

            doc = Document(safe_path)
            paragraphs = [p.text for p in doc.paragraphs]
            tables = []
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text for cell in row.cells]
                    tables.append(" | ".join(cells))
            content = "\n".join(paragraphs)
            if tables:
                content += "\n\n--- Tables ---\n" + "\n".join(tables)
            return content
        except Exception as e:
            raise OfficeCLIError(f"读取 Word 文件失败 {safe_path!r}: {e}")

    @register_tool("write_word")
    def write_word(self, file_path: str, content: str) -> str:
        """写入 Word 文档。

        Args:
            file_path: 沙箱内的写回路径。
            content: 文本内容。

        Returns:
            写回后的完整路径。

        Raises:
            OfficeCLIError: 写入失败。
        """
        safe_path = self._resolve_sandbox_path(file_path, ".docx", is_output=True)
        try:
            from docx import Document

            doc = Document()
            for line in content.split("\n"):
                doc.add_paragraph(line)
            doc.save(safe_path)
            logger.info("Word 文档已写入: %s", safe_path)
            return safe_path
        except Exception as e:
            raise OfficeCLIError(f"写入 Word 文件失败 {safe_path!r}: {e}")

    def modify_word(self, file_path: str, new_content: str) -> str:
        """修改 Word 文档（读取后覆盖写入）。

        Args:
            file_path: 沙箱内的文件路径。
            new_content: 新内容。

        Returns:
            写回后的完整路径。
        """
        # 读取验证存在性，然后写回
        self.read_word(file_path)
        safe_path = self._resolve_sandbox_path(file_path, ".docx", is_output=True)
        try:
            from docx import Document

            doc = Document()
            for line in new_content.split("\n"):
                doc.add_paragraph(line)
            doc.save(safe_path)
            logger.info("Word 文档已修改: %s", safe_path)
            return safe_path
        except Exception as e:
            raise OfficeCLIError(f"修改 Word 文件失败 {safe_path!r}: {e}")

    # ── Excel 操作 ──────────────────────────────────────────

    @register_tool("read_excel")
    def read_excel(self, file_path: str, sheet_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """读取 Excel 文件内容。

        Args:
            file_path: 沙箱内的文件路径。
            sheet_name: 工作表名称，默认读取第一个。

        Returns:
            行数据列表，每行为 {列名: 值} 字典。

        Raises:
            OfficeCLIError: 读取失败或格式错误。
        """
        safe_path = self._resolve_sandbox_path(file_path, ".xlsx")
        try:
            import openpyxl

            wb = openpyxl.load_workbook(safe_path, read_only=True, data_only=True)
            ws = wb[sheet_name] if sheet_name else wb.active

            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return []

            headers = [str(h) if h is not None else "" for h in rows[0]]
            result = []
            for row in rows[1:]:
                row_dict = {}
                for i, cell in enumerate(row):
                    col_name = headers[i] if i < len(headers) else f"col_{i}"
                    row_dict[col_name] = cell if cell is not None else ""
                result.append(row_dict)

            wb.close()
            return result
        except Exception as e:
            raise OfficeCLIError(f"读取 Excel 文件失败 {safe_path!r}: {e}")

    @register_tool("write_excel")
    def write_excel(
        self, file_path: str, data: List[Dict[str, Any]], sheet_name: str = "Sheet1"
    ) -> str:
        """写入 Excel 文件。

        Args:
            file_path: 沙箱内的写回路径。
            data: 行数据列表。
            sheet_name: 工作表名称。

        Returns:
            写回后的完整路径。
        """
        safe_path = self._resolve_sandbox_path(file_path, ".xlsx", is_output=True)
        wb = None
        try:
            import openpyxl
            from openpyxl.utils import get_column_letter

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = sheet_name

            if data:
                headers = list(data[0].keys())
                ws.append(headers)
                for row in data:
                    ws.append([row.get(h, "") for h in headers])

            wb.save(safe_path)
            logger.info("Excel 文件已写入: %s", safe_path)
            return safe_path
        except Exception as e:
            raise OfficeCLIError(f"写入 Excel 文件失败 {safe_path!r}: {e}")
        finally:
            if wb is not None:
                try:
                    wb.close()
                except Exception:
                    pass

    def modify_excel(
        self, file_path: str, data: List[Dict[str, Any]], sheet_name: Optional[str] = None
    ) -> str:
        """修改 Excel 文件。

        Args:
            file_path: 沙箱内的文件路径。
            data: 新数据。
            sheet_name: 工作表名称。

        Returns:
            写回后的完整路径。
        """
        # 读取验证存在性
        self.read_excel(file_path, sheet_name)
        return self.write_excel(file_path, data, sheet_name or "Sheet1")

    # ── 内部方法 ────────────────────────────────────────────

    def _resolve_sandbox_path(
        self, file_path: str, expected_ext: str, is_output: bool = False
    ) -> str:
        """解析沙箱内文件路径。

        不做路径穿越检查（沙箱内信任），但检查扩展名。

        Args:
            file_path: 沙箱内相对路径。
            expected_ext: 期望的文件扩展名。
            is_output: 是否为输出路径。

        Returns:
            解析后的沙箱内绝对路径。
        """
        # 检查扩展名
        ext = os.path.splitext(file_path)[1].lower()
        if ext != expected_ext and ext not in ALLOWED_EXTENSIONS:
            raise OfficeCLIError(
                f"不支持的文件格式: {ext!r}，期望: {expected_ext!r}"
            )

        # 禁止绝对路径（沙箱内也应使用相对路径）
        if os.path.isabs(file_path):
            raise OfficeCLIError(f"沙箱内禁止使用绝对路径: {file_path!r}")

        # 禁止 ../ 穿越
        normalized = os.path.normpath(file_path)
        if normalized.startswith("..") or ".." in normalized.split(os.sep):
            raise OfficeCLIError(f"沙箱内禁止路径穿越: {file_path!r}")

        # 拼接到沙箱工作目录
        full_path = os.path.join(self._work_dir, normalized)
        return full_path