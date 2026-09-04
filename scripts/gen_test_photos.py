# -*- coding: utf-8 -*-
"""批量生成 OCR 测试照片（有能识别通过的，也有识别不通过的），并逐张跑真实 PaddleOCR 验证。

生成的照片保存到 scripts/_ocr_tmp/test_photos/，文件名直接标注预期结果：
  通过-*.jpg    预期识别成功（置信度 >= 0.85 且关键字段正确）
  不通过-*.jpg 预期识别失败（置信度 < 0.8 或字段缺失/错误）

用法（项目根目录）:
    backend/.venv/Scripts/python.exe scripts/gen_test_photos.py
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent / "_ocr_tmp" / "test_photos"


def find_font():
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            return str(p)
    return None


def make_receipt(path, order_id="ORD-2024-0088", amount="129.90", date="2026-08-31",
                 merchant="示例电商旗舰店", reason="商品质量问题", size=(640, 420)):
    """生成基础收据图。"""
    font_path = find_font()
    font = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
    title_font = ImageFont.truetype(font_path, 36) if font_path else font

    w, h = size
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, w - 9, h - 9], outline="black", width=2)
    d.text((int(w * 0.31), 30), "退款申请凭证", fill="black", font=title_font)
    lines = [
        f"商户名称：{merchant}",
        f"订单号：{order_id}",
        f"退款金额：{amount}元",
        "支付方式：微信支付",
        f"申请日期：{date}",
        f"退款原因：{reason}",
    ]
    y = 100
    for line in lines:
        d.text((60, y), line, fill="black", font=font)
        y += 46
    img.save(path)
    return path


# ── 各种「拍摄效果」的退化处理 ──────────────────────────────

def photo_clean(img: Image.Image) -> Image.Image:
    """清晰拍照：轻微噪点 + 轻微 JPEG 压缩。"""
    arr = np.array(img).astype(np.int16)
    noise = np.random.default_rng(1).normal(0, 4, arr.shape).astype(np.int16)
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))


def photo_tilt(img: Image.Image) -> Image.Image:
    """手持轻微倾斜拍照：旋转 2 度 + 轻噪点。"""
    img = img.rotate(2.0, expand=True, fillcolor=(205, 205, 200))
    arr = np.array(img).astype(np.int16)
    noise = np.random.default_rng(2).normal(0, 6, arr.shape).astype(np.int16)
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))


def photo_mild_blur(img: Image.Image) -> Image.Image:
    """轻度失焦：模糊 1.6 + 噪点。"""
    img = img.filter(ImageFilter.GaussianBlur(1.6))
    arr = np.array(img).astype(np.int16)
    noise = np.random.default_rng(3).normal(0, 8, arr.shape).astype(np.int16)
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))


def photo_heavy_blur(img: Image.Image) -> Image.Image:
    """严重失焦/手抖：模糊 4.5。"""
    return img.filter(ImageFilter.GaussianBlur(4.5))


def photo_lowres(img: Image.Image) -> Image.Image:
    """低分辨率（远距离拍摄/截图缩小）：缩到 1/8 再放大。"""
    w, h = img.size
    small = img.resize((w // 8, h // 8), Image.LANCZOS)
    return small.resize((w, h), Image.NEAREST)


def photo_dark(img: Image.Image) -> Image.Image:
    """光线过暗：亮度 20% + 对比度降低 + 强噪点 + 半幅阴影遮盖文字。"""
    img = ImageEnhance.Brightness(img).enhance(0.20)
    img = ImageEnhance.Contrast(img).enhance(0.60)
    arr = np.array(img).astype(np.float32)
    # 右半幅再叠一层阴影，直接吃掉右侧文字
    h, w = arr.shape[:2]
    xx = np.arange(w)[None, :, None]
    shadow = np.where(xx > w * 0.42, 0.35, 1.0).astype(np.float32)
    arr *= shadow
    noise = np.random.default_rng(4).normal(0, 18, arr.shape).astype(np.float32)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def photo_glare(img: Image.Image) -> Image.Image:
    """反光/曝光过度：整张过曝 + 中央白斑完全冲掉文字（局部最大像素化处理）。"""
    arr = np.array(img).astype(np.float32)
    h, w = arr.shape[:2]
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    # 中心椭圆白斑，长轴覆盖订单号/金额整行
    cx, cy = w * 0.45, h * 0.50
    rx, ry = w * 0.38, h * 0.32
    falloff = np.clip(1 - ((xx - cx) / rx) ** 2 - ((yy - cy) / ry) ** 2, 0, 1)
    # 中心直接把像素强制到 252（白底 255 → 白，文字 0 → 252 灰白，几乎无对比）
    level = 120 + falloff * 135
    arr = np.maximum(arr, level[..., None])
    return Image.fromarray(arr.astype(np.uint8))


def photo_occluded(img: Image.Image) -> Image.Image:
    """关键字段被物体遮挡：模拟手指/物件盖住订单号和金额两行（椭圆色块 + 软边）。"""
    arr = np.array(img).astype(np.float32)
    h, w = arr.shape[:2]
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    mask = np.zeros((h, w), dtype=np.float32)
    for cy_frac, rx_frac, ry_frac in [(0.36, 0.34, 0.12), (0.49, 0.34, 0.10)]:
        cx, cy = w * 0.5, h * cy_frac
        rx, ry = w * rx_frac, h * ry_frac
        inside = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 < 1
        # 软边：内部 1，外部 0
        d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
        edge = np.clip(1 - (d - 0.7) / 0.4, 0, 1)
        mask = np.maximum(mask, edge)
    # 肉色 + 一点阴影
    block = np.array([220, 200, 180], dtype=np.float32)
    arr = arr * (1 - mask[..., None]) + block * mask[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def photo_perspective(img: Image.Image) -> Image.Image:
    """强透视歪斜：模拟从极端角度拍摄（梯形失真）。"""
    w, h = img.size
    # PIL QUAD 模式：data=(x0,y0,x1,y1,x2,y2,x3,y3) 是 dest 4 角对应 src 中的取样点
    # 让 dest 显示 src 的「梯形扭曲」效果
    quad = (
        int(w * 0.10), int(h * 0.10),   # dest tl ← src (0.10w, 0.10h)
        int(w * 0.95), int(h * 0.05),   # dest tr ← src (0.95w, 0.05h)
        int(w * 0.88), int(h * 0.95),   # dest br ← src (0.88w, 0.95h)
        int(w * 0.02), int(h * 0.98),   # dest bl ← src (0.02w, 0.98h)
    )
    return img.transform((w, h), Image.QUAD, quad, Image.BICUBIC,
                         fillcolor=(230, 230, 225))


def photo_rotated_90(img: Image.Image) -> Image.Image:
    """用户横着拍了图片，整张旋转 90°。"""
    return img.rotate(90, expand=True, fillcolor="white")


def photo_tiny(img: Image.Image) -> Image.Image:
    """文字极小：模拟手机远距离拍摄（分辨率太低，文字过小识别失败）。"""
    w, h = img.size
    # 缩小到 1/6，再放大回原尺寸 + 轻度噪点
    tiny = img.resize((w // 6, h // 6), Image.LANCZOS)
    out = tiny.resize((w, h), Image.LANCZOS)
    arr = np.array(out).astype(np.int16)
    noise = np.random.default_rng(6).normal(0, 12, arr.shape).astype(np.int16)
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))


# ── 生成计划：文件名 -> (内容参数, 退化函数, 预期) ─────────────

def build_cases():
    return [
        ("通过-1清晰拍摄.jpg", {}, photo_clean, True),
        ("通过-2轻微倾斜.jpg", {}, photo_tilt, True),
        ("通过-3轻度失焦.jpg", {"order_id": "ORD-2024-0369", "amount": "58.50", "date": "2026-08-28"}, photo_mild_blur, True),
        ("不通过-1严重模糊.jpg", {"order_id": "ORD-2024-1207", "amount": "299.00"}, photo_heavy_blur, False),
        ("不通过-2低分辨率.jpg", {"order_id": "ORD-2024-1580", "amount": "89.60"}, photo_lowres, False),
        ("不通过-3光线过暗.jpg", {"order_id": "ORD-2024-2841", "amount": "459.00"}, photo_dark, False),
        ("不通过-4强透视歪斜.jpg", {"order_id": "ORD-2024-4255", "amount": "188.00"}, photo_perspective, False),
        ("不通过-5手指遮挡.jpg", {"order_id": "ORD-2024-5001", "amount": "199.00"}, photo_occluded, False),
        ("不通过-6文字极小.jpg", {"order_id": "ORD-2024-6789", "amount": "256.30"}, photo_tiny, False),
    ]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    from app.infrastructure.providers.ocr import PaddleOcrProvider

    provider = PaddleOcrProvider(lang="ch")
    print("生成测试照片并逐张真实 OCR 识别...\n")

    results = []
    for fname, kwargs, degrade, expect_pass in build_cases():
        base = make_receipt(str(OUT / "_base.png"), **kwargs)
        img = Image.open(base).convert("RGB")
        img = degrade(img)
        out_path = OUT / fname
        img.save(out_path, "JPEG", quality=90)

        r = provider.extract(fname, str(out_path), None, 0)
        conf = r.overall_confidence
        fields = r.fields or {}
        order_ok = "order_id" in fields
        amount_ok = "amount" in fields

        # 通过标准：置信度 >= 0.85 且订单号/金额都抽到
        passed = conf >= 0.85 and order_ok and amount_ok
        mark = "PASS" if passed else "FAIL"
        results.append((fname, conf, passed, expect_pass))

        print(f"[{mark}] {fname}")
        print(f"      置信度 {conf:.4f} | 字段 {fields}")
        text_head = (r.text or "").replace(chr(10), " / ")[:60]
        print(f"      文本: {text_head}")
        print()

    print("=" * 60)
    print(f"{'文件名':<24} {'置信度':>8}  实际  预期")
    print("-" * 60)
    all_match = True
    for fname, conf, passed, expect_pass in results:
        expect = "通过" if expect_pass else "不通过"
        actual = "通过" if passed else "不通过"
        match = "==" if passed == expect_pass else "!!预期不符"
        if passed != expect_pass:
            all_match = False
        print(f"{fname:<24} {conf:>8.4f}  {actual}  {expect} {match}")

    if all_match:
        print("\n全部与预期一致：通过/不通过照片集已就绪 ✓")
        print(f"目录: {OUT}")
    else:
        print("\n部分照片实际结果与预期不符（标 !! 的行），可调整退化参数后重新生成。")
        sys.exit(1)


if __name__ == "__main__":
    main()
