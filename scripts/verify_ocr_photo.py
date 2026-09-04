# -*- coding: utf-8 -*-
"""模拟真实手机拍照场景的 OCR 效果验证：
干净图片 -> 加入旋转/噪点/模糊/光照不均 -> PaddleOCR 识别 -> 断言关键字段仍准确。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from PIL import Image, ImageEnhance, ImageFilter


def make_photo_like(src: str, dst: str):
    """把干净收据图处理成手机拍照效果：轻微旋转 + 轻微模糊 + 噪点 + 亮度不均。"""
    import numpy as np

    img = Image.open(src).convert("RGB")

    # 1) 轻微旋转（手持拍照常见 1~3 度）
    img = img.rotate(-2.2, expand=True, fillcolor=(210, 210, 205))

    # 2) 轻微模糊（对焦不完美）
    img = img.filter(ImageFilter.GaussianBlur(0.8))

    # 3) 高斯噪点（传感器噪声）
    arr = np.array(img).astype(np.int16)
    noise = np.random.default_rng(42).normal(0, 10, arr.shape).astype(np.int16)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # 4) 光照不均（一侧偏暗）
    w, h = img.size
    grad = np.linspace(0.72, 1.15, w)[None, :, None].astype(np.float32)
    arr2 = np.array(img).astype(np.float32) * grad
    img = Image.fromarray(np.clip(arr2, 0, 255).astype(np.uint8))

    # 5) 轻微透视缩放模拟 + 压缩感
    img = ImageEnhance.Contrast(img).enhance(0.95)
    img.save(dst, "JPEG", quality=88)  # JPEG 压缩噪声
    return dst


def main():
    base = Path(__file__).parent / "_ocr_tmp"
    base.mkdir(exist_ok=True)
    clean = base / "receipt.png"
    photo = base / "receipt_photo.jpg"

    if not clean.exists():
        print("缺少 receipt.png，先运行 verify_ocr.py 生成")
        return 1

    make_photo_like(str(clean), str(photo))
    print(f"已生成模拟拍照图: {photo}")

    from app.infrastructure.providers.ocr import PaddleOcrProvider

    prov = PaddleOcrProvider(lang="ch")
    result = prov.extract("receipt_photo.jpg", str(photo), None, 0)

    print("\n===== 模拟拍照图 OCR 结果 =====")
    print(f"置信度: {result.overall_confidence:.4f}")
    print("识别全文:")
    print(result.text)
    print(f"\n抽取字段: {result.fields}")

    # 断言：拍照干扰下关键字段仍准确
    assert float(result.fields.get("amount")) == 129.9, f"金额错误: {result.fields.get('amount')}"
    assert str(result.fields.get("order_id")) == "ORD-2024-0088", f"订单号错误: {result.fields.get('order_id')}"
    assert result.overall_confidence >= 0.90, f"置信度过低: {result.overall_confidence:.4f}"
    print("\n[PASS] 模拟拍照场景下，金额/订单号识别准确，置信度达标")
    return 0


if __name__ == "__main__":
    sys.exit(main())
