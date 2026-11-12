# -*- coding: utf-8 -*-
"""生成应用图标（assets/icon.png / icon.ico / icon.icns 源图）。

用法：python3 scripts/make_icon.py
依赖：Pillow（pip install pillow）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "assets")
os.makedirs(OUT, exist_ok=True)

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("需要 Pillow：pip install pillow")
    sys.exit(1)

SIZE = 1024
BRAND = (14, 175, 126)        # 翠绿主体色
BRAND_DARK = (8, 120, 86)


def draw_icon():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    # 平滑垂直渐变圆角方底
    top, bottom = (16, 196, 140), (6, 108, 78)
    grad = Image.new("RGBA", (1, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        grad.putpixel((0, y), (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
            255))
    grad = grad.resize((SIZE, SIZE))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, SIZE, SIZE], radius=220, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # 四角星 ✦（品牌符号）
    cx, cy = SIZE / 2, SIZE / 2
    arm = SIZE * 0.30
    waist = SIZE * 0.075
    pts = [
        (cx, cy - arm),
        (cx + waist, cy - waist),
        (cx + arm, cy),
        (cx + waist, cy + waist),
        (cx, cy + arm),
        (cx - waist, cy + waist),
        (cx - arm, cy),
        (cx - waist, cy - waist),
    ]
    d.polygon(pts, fill=(255, 255, 255, 255))
    return img


def main():
    img = draw_icon()
    png = os.path.join(OUT, "icon.png")
    img.save(png)
    print("✓", png)
    # Windows ICO（多尺寸）
    ico = os.path.join(OUT, "icon.ico")
    img.resize((256, 256), Image.LANCZOS).save(
        ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128),
                    (256, 256)])
    print("✓", ico)
    # macOS ICNS（icns 需 png2icns 或 sips/iconutil，此处产出 1024 png 供
    # build_macos.sh 用 iconutil 转换；无 iconutil 时直接用 png）
    icns_src = os.path.join(OUT, "icon_1024.png")
    img.save(icns_src)
    print("✓", icns_src, "（macOS 用 iconutil 转 .icns）")


if __name__ == "__main__":
    main()
