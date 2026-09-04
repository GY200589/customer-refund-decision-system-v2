# -*- coding: utf-8 -*-
"""验证真实 PaddleOCR 效果：生成收据图片/PDF -> 调用 PaddleOcrProvider -> 断言识别结果。

用法（在项目根目录）:
    backend/.venv/Scripts/python.exe scripts/verify_ocr.py
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))


def find_font():
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            return str(p)
    return None


def make_receipt_image(path: str):
    """生成一张模拟退款凭证图片（中文 + 金额 + 订单号 + 日期）。"""
    from PIL import Image, ImageDraw, ImageFont

    font_path = find_font()
    font = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
    title_font = ImageFont.truetype(font_path, 36) if font_path else font

    img = Image.new("RGB", (640, 420), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, 631, 411], outline="black", width=2)
    d.text((200, 30), "退款申请凭证", fill="black", font=title_font)
    lines = [
        "商户名称：示例电商旗舰店",
        "订单号：ORD-2024-0088",
        "退款金额：129.90元",
        "支付方式：微信支付",
        "申请日期：2026-08-31",
        "退款原因：商品质量问题",
    ]
    y = 100
    for line in lines:
        d.text((60, y), line, fill="black", font=font)
        y += 46
    img.save(path)
    return path


def make_receipt_pdf(image_path: str, pdf_path: str) -> str:
    from PIL import Image

    Image.open(image_path).convert("RGB").save(pdf_path, "PDF")
    return pdf_path


def main():
    from app.infrastructure.providers.ocr import PaddleOcrProvider

    tmp = Path(__file__).resolve().parent / "_ocr_tmp"
    tmp.mkdir(exist_ok=True)
    img_path = make_receipt_image(str(tmp / "receipt.png"))
    pdf_path = make_receipt_pdf(img_path, str(tmp / "receipt.pdf"))

    provider = PaddleOcrProvider(lang="ch")
    print(f"paddleocr 版本分支: is_v3={getattr(provider, '_is_v3', 'N/A(mock回退)')}")

    failures = []

    for label, path in (("图片", img_path), ("PDF", pdf_path)):
        result = provider.extract(Path(path).name, path, None, 0)
        print(f"\n=== {label} 识别结果 ===")
        print(f"整体置信度: {result.overall_confidence:.4f}")
        print(f"结构化字段: {result.fields}")
        print(f"识别文本:\n{result.text}")

        if not result.text:
            failures.append(f"{label}: 未识别到任何文本")
            continue
        if result.overall_confidence < 0.5:
            failures.append(f"{label}: 置信度过低 {result.overall_confidence:.2f}")
        if "订单" not in result.text or "ORD" not in result.text.replace(" ", ""):
            failures.append(f"{label}: 未识别出订单号，文本={result.text[:80]!r}")
        if "129" not in result.text.replace(" ", ""):
            failures.append(f"{label}: 未识别出金额 129.90，文本={result.text[:80]!r}")
        if result.fields.get("order_id") != "ORD-2024-0088":
            failures.append(f"{label}: order_id 字段抽取不符: {result.fields.get('order_id')!r}")
        if abs(result.fields.get("amount", 0) - 129.90) > 0.01:
            failures.append(f"{label}: amount 字段抽取不符: {result.fields.get('amount')!r}")

    print("\n" + "=" * 50)
    if failures:
        print("验证失败:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("全部断言通过：真实 PaddleOCR 识别文本/置信度/字段抽取均正常 ✓")


if __name__ == "__main__":
    main()
