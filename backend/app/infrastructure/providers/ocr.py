import io
import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class OcrResult:
    text: str
    fields: dict
    overall_confidence: float


def _format_cent(amount_cent: int) -> str:
    return f"{amount_cent // 100}.{amount_cent % 100:02d}"


class OcrProvider(ABC):
    @abstractmethod
    def extract(self, file_name: str, file_path: str | None, file_hash: str | None, amount_cent: int) -> OcrResult:
        raise NotImplementedError


class CachedOcrProvider(OcrProvider):
    """OCR 结果缓存装饰器：同一文件（file_path）短期内只识别一次。

    解决 upload 实时预览与 EvidenceAgent 异步流程对同一凭证重复跑 OCR 的问题：
    - upload 接口首次识别后写入 Redis（TTL，默认 1 小时）
    - 建案后 EvidenceAgent 命中缓存直接返回，省去数秒的模型推理
    - Redis 不可用时静默降级为直通（不影响功能正确性）

    说明：缓存 key 不含 amount_cent（真实 PaddleOCR 不依赖该参数，
    仅 Mock 用它生成文本），因此同一文件不同金额下返回的 text 一致。
    """

    def __init__(self, inner: OcrProvider, redis_client=None, ttl: int = 3600, enabled: bool = True):
        self._inner = inner
        self._redis = redis_client
        self._ttl = ttl
        self._enabled = enabled

    @property
    def cache_enabled(self) -> bool:
        return self._enabled and self._redis is not None

    @staticmethod
    def _key(file_path: str | None, file_name: str) -> str:
        return f"ocr:cache:{file_path or file_name}"

    def extract(self, file_name: str, file_path: str | None, file_hash: str | None, amount_cent: int) -> OcrResult:
        result = self._get_cached(file_path, file_name)
        if result is not None:
            logger.info("OCR 缓存命中: %s", file_name)
            return result

        result = self._inner.extract(file_name, file_path, file_hash, amount_cent)
        self._put_cached(file_path, file_name, result)
        return result

    # ---- 缓存读写（任何异常均静默降级）----

    def _get_cached(self, file_path, file_name) -> OcrResult | None:
        if not self.cache_enabled:
            return None
        try:
            raw = self._redis.get(self._key(file_path, file_name))
            if not raw:
                return None
            data = json.loads(raw)
            return OcrResult(
                text=data.get("text", ""),
                fields=data.get("fields") or {},
                overall_confidence=float(data.get("overall_confidence", 0.0)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR 缓存读取失败（降级直通）: %s", exc)
            return None

    def _put_cached(self, file_path, file_name, result: OcrResult) -> None:
        if not self.cache_enabled or not result:
            return
        try:
            payload = json.dumps(
                {
                    "text": result.text,
                    "fields": result.fields,
                    "overall_confidence": result.overall_confidence,
                },
                ensure_ascii=False,
            )
            self._redis.setex(self._key(file_path, file_name), self._ttl, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR 缓存写入失败（忽略）: %s", exc)


class MockOcrProvider(OcrProvider):
    """确定性 Mock：文件名包含模糊/损坏等关键字时返回低置信度，否则高置信度。"""

    LOW_HINTS = ("blur", "模糊", "unclear", "bad", "损坏", "low")

    def extract(self, file_name: str, file_path: str | None, file_hash: str | None, amount_cent: int) -> OcrResult:
        lowered = (file_name or "").lower()
        is_low = any(h in lowered for h in self.LOW_HINTS)
        confidence = 0.55 if is_low else 0.95
        # 测试/演示可用 amount-99.00 文件名模拟凭证中真实识别到的金额；
        # 普通文件仍回显申请金额，保持既有 Mock 用例的确定性。
        import re

        amount_match = re.search(r"amount[-_ ]?(\d+(?:\.\d{1,2})?)", lowered)
        extracted_cent = round(float(amount_match.group(1)) * 100) if amount_match else amount_cent
        order_match = re.search(r"(SO[A-Z0-9]{8,})", file_name or "", re.IGNORECASE)
        text = f"退款申请凭证 {file_name}：金额 {_format_cent(extracted_cent)} 元，商品退款"
        fields = {"amount_cent": extracted_cent, "merchant": "示例商户"}
        if order_match:
            fields["order_id"] = order_match.group(1).upper()
        return OcrResult(
            text=text,
            fields=fields,
            overall_confidence=confidence,
        )


class PaddleOcrProvider(OcrProvider):
    """真实 PaddleOCR 实现。

    - 同时兼容 paddleocr 2.x（.ocr(path, cls=True)）与 3.x（.predict() + rec_texts/rec_scores）API
    - 支持图片文件与 PDF（PDF 先转图片再 OCR；优先 PyMuPDF，其次 pdf2image）
    - 使用 mean(confidences) 作为整体置信度（比 min 更合理）
    - paddleocr 未安装时回退到 MockOcrProvider
    """

    def __init__(self, lang: str = "ch", use_angle_cls: bool = False):
        try:
            import paddleocr  # 延迟导入
            from paddleocr import PaddleOCR

            version = getattr(paddleocr, "__version__", "2.0.0")
            self._is_v3 = int(version.split(".")[0]) >= 3

            if self._is_v3:
                # 3.x：use_angle_cls 已更名为 use_textline_orientation；
                # 关闭 MKLDNN 规避 paddlepaddle 3.3 oneDNN PIR 属性转换 bug
                kwargs = {"lang": lang, "enable_mkldnn": False}
                if use_angle_cls:
                    kwargs["use_textline_orientation"] = True
                self._ocr = PaddleOCR(**kwargs)
            else:
                self._ocr = PaddleOCR(lang=lang, use_angle_cls=use_angle_cls)
        except ImportError:
            logger.warning("paddleocr 未安装，回退到 MockOcrProvider")
            self._mock = MockOcrProvider()
            self._ocr = None
            self._is_v3 = False

    def extract(self, file_name: str, file_path: str | None, file_hash: str | None, amount_cent: int) -> OcrResult:
        if self._ocr is None:
            return self._mock.extract(file_name, file_path, file_hash, amount_cent)

        # 确定文件路径：优先 file_path，其次 file_name
        path = file_path or file_name
        if not os.path.isfile(path):
            logger.warning("文件不存在: %s", path)
            return OcrResult(text="", fields={}, overall_confidence=0.0)

        ext = Path(path).suffix.lower()
        if ext == ".pdf":
            return self._ocr_pdf(path)

        lines, confidences = self._run_ocr(path)
        return self._build_result(lines, confidences)

    # ---- 底层调用：屏蔽 2.x / 3.x API 差异 ----

    def _run_ocr(self, image) -> tuple[list[str], list[float]]:
        """对图片（路径 / PIL Image / np.ndarray）执行 OCR，返回 (文本行, 置信度列表)。"""
        import numpy as np

        if isinstance(image, str):
            source = image  # 文件路径
        else:
            # PIL Image -> BGR ndarray
            import cv2

            if hasattr(image, "convert"):
                image = image.convert("RGB")
            arr = np.asarray(image)
            source = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        try:
            if self._is_v3:
                results = self._ocr.predict(source)
                lines, confidences = [], []
                for res in results or []:
                    texts = list(res.get("rec_texts", []) or [])
                    scores = [float(s) for s in (res.get("rec_scores", []) or [])]
                    lines.extend(texts)
                    confidences.extend(scores)
                return lines, confidences

            result = self._ocr.ocr(source, cls=True)
            lines, confidences = [], []
            for page in result or []:
                for item in page or []:
                    text = item[1][0]
                    conf = float(item[1][1])
                    lines.append(text)
                    confidences.append(conf)
            return lines, confidences
        except TypeError:
            # 某些 2.x 版本不接受 ndarray 的 cls 参数等边缘情况，降级为临时文件
            if isinstance(image, str):
                raise
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                image.save(tmp, format="PNG")
                tmp_path = tmp.name
            try:
                result = self._ocr.ocr(tmp_path, cls=True)
                lines, confidences = [], []
                for page in result or []:
                    for item in page or []:
                        lines.append(item[1][0])
                        confidences.append(float(item[1][1]))
                return lines, confidences
            finally:
                os.unlink(tmp_path)

    def _build_result(self, lines: list[str], confidences: list[float]) -> OcrResult:
        if not lines:
            return OcrResult(text="", fields={}, overall_confidence=0.0)
        overall = sum(confidences) / len(confidences)
        full_text = "\n".join(lines)
        fields = self._extract_fields(full_text)
        return OcrResult(text=full_text, fields=fields, overall_confidence=overall)

    def _ocr_pdf(self, path: str) -> OcrResult:
        """将 PDF 每页转为图片后 OCR。优先 PyMuPDF（免装 poppler），其次 pdf2image。"""
        images = self._pdf_to_images(path)
        if not images:
            return OcrResult(text="", fields={}, overall_confidence=0.0)

        all_lines: list[str] = []
        all_confidences: list[float] = []
        for img in images:
            lines, confs = self._run_ocr(img)
            all_lines.extend(lines)
            all_confidences.extend(confs)

        return self._build_result(all_lines, all_confidences)

    @staticmethod
    def _pdf_to_images(path: str) -> list:
        try:
            try:
                import pymupdf  # PyMuPDF >= 1.24 推荐写法
            except ImportError:
                import fitz as pymupdf  # 兼容旧版（会有弃用警告）

            doc = pymupdf.open(path)
            images = []
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                images.append(io.BytesIO(pix.tobytes("png")))
            doc.close()

            # BytesIO -> PIL Image
            from PIL import Image

            return [Image.open(buf) for buf in images]
        except ImportError:
            pass

        try:
            from pdf2image import convert_from_path

            return convert_from_path(path, dpi=200)
        except Exception as exc:  # noqa: BLE001
            logger.error("PDF 转换失败: %s", exc)
            return []

    def _extract_fields(self, text: str) -> dict:
        """从 OCR 文本中提取结构化字段（金额、日期、订单号等）。"""
        import re

        fields = {}

        # 提取金额：匹配 "X.XX元" 或 "金额 X.XX" 或 "￥X.XX"
        amount_patterns = [
            r"金额[：:\s]*([\d,]+\.\d{2})",
            r"[￥¥]([\d,]+\.\d{2})",
            r"([\d,]+\.\d{2})\s*元",
        ]
        for pat in amount_patterns:
            m = re.search(pat, text)
            if m:
                try:
                    fields["amount"] = float(m.group(1).replace(",", ""))
                except ValueError:
                    pass
                break

        # 提取日期：匹配 YYYY-MM-DD 或 YYYY年MM月DD日
        date_patterns = [
            r"(\d{4}-\d{1,2}-\d{1,2})",
            r"(\d{4}年\d{1,2}月\d{1,2}日)",
        ]
        for pat in date_patterns:
            m = re.search(pat, text)
            if m:
                fields["date"] = m.group(0)
                break

        # 提取订单号
        order_patterns = [
            r"订单[号：:\s]*([A-Za-z0-9\-]+)",
            r"(ORD[-]?\d+)",
        ]
        for pat in order_patterns:
            m = re.search(pat, text)
            if m:
                fields["order_id"] = m.group(1)
                break

        return fields
