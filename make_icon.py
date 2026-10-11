# -*- coding: utf-8 -*-
"""
图标生成脚本
============
绘制"师"字图标并导出为 Windows .ico。

设计说明
--------
- 配色取自校园网门户的主题色（深青绿 #17606E → #2F98A8），
  与登录页面视觉一致，一看就知道是校园网工具。
- 采用大字号无衬线粗体（微软雅黑 Bold），保证在 16×16 这样
  的极小尺寸下"师"字笔画依然不粘连、清晰可辨。
- 图标含透明通道，能自然融入浅色/深色桌面与任务栏。

用法：
    python make_icon.py            # 生成 icon.ico
"""

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- 可调参数（改这里即可微调样式）----
TOP_COLOR = (24, 96, 110)        # 渐变顶部（深青）
BOTTOM_COLOR = (47, 152, 168)    # 渐变底部（亮青）
TEXT_COLOR = (255, 255, 255, 255)
FONT_PATH = "C:/Windows/Fonts/msyhbd.ttc"   # 微软雅黑粗体
TEXT_RATIO = 0.70                # 字号占画布比例
CORNER_RATIO = 6                 # 圆角半径 = 画布/6
BASE_SIZE = 1024                 # 绘制基准分辨率（越大越清晰）

# Windows 图标所需尺寸
ICO_SIZES = [256, 128, 64, 48, 32, 24, 16]


def _make_gradient(size: int) -> Image.Image:
    """生成带圆角遮罩的竖向渐变底图。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # 逐行绘制渐变（先画到小图再放大，避免逐像素画大图过慢）
    strip = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        strip.putpixel((0, y), tuple(
            int(TOP_COLOR[i] + (BOTTOM_COLOR[i] - TOP_COLOR[i]) * t)
            for i in range(3)
        ))
    grad = strip.resize((size, size))

    # 圆角遮罩
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size, size), radius=size // CORNER_RATIO, fill=255
    )
    img.paste(grad, (0, 0), mask)
    return img


def render(size: int = BASE_SIZE) -> Image.Image:
    """渲染指定尺寸的图标。"""
    img = _make_gradient(size)
    draw = ImageDraw.Draw(img)

    font = ImageFont.truetype(FONT_PATH, int(size * TEXT_RATIO))
    # 精确居中：用 textbbox 计算实际墨迹范围，避免视觉偏移
    bbox = draw.textbbox((0, 0), "师", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - w) / 2 - bbox[0]
    y = (size - h) / 2 - bbox[1] - int(size * 0.012)   # 略微上移，视觉更居中
    draw.text((x, y), "师", font=font, fill=TEXT_COLOR)
    return img


def build_ico(png_path: str | None = None,
              ico_path: str | None = None) -> str:
    """生成 .ico 文件（内含多种尺寸，Windows 会自动选择合适的）。"""
    ico_path = ico_path or os.path.join(HERE, "icon.ico")
    png_path = png_path or os.path.join(HERE, "icon.png")

    # 用最大尺寸绘制，再缩小到各档位，保证各尺寸都是高质量缩放
    base = render(BASE_SIZE)
    base.save(png_path, "PNG")

    sizes = [(s, s) for s in ICO_SIZES]
    base.save(ico_path, "ICO", sizes=sizes)
    return ico_path


if __name__ == "__main__":
    ico = build_ico()
    print(f"已生成图标: {ico}")
    print(f"PNG 预览  : {os.path.join(HERE, 'icon.png')}")
    print(f"尺寸      : {ICO_SIZES}")