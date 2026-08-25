#!/usr/bin/env python3
"""手诊拍照示例图 — 掌面朝前、手指自然微屈、甲床可见"""
from PIL import Image, ImageDraw, ImageFont
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.paths import DOCS_IMAGES_DIR  # noqa: E402

W, H = 1024, 1024
OUT = os.path.join(DOCS_IMAGES_DIR, "hands.jpg")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

img = Image.new('RGB', (W, H), '#FFFDF7')
draw = ImageDraw.Draw(img)

# CJK 字体候选（按平台依次尝试；全部不可用时退化为 PIL 默认字体）
_FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",                          # macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",                  # macOS（旧版）
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",   # Linux 部署机
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",      # Linux Noto
]


def _load_fonts():
    for path in _FONT_CANDIDATES:
        try:
            return (ImageFont.truetype(path, 22),
                    ImageFont.truetype(path, 17),
                    ImageFont.truetype(path, 14))
        except (OSError, IOError):
            continue
    f = ImageFont.load_default()
    return f, f, f


f_bold, f_norm, f_small = _load_fonts()

# ── 标题栏 ──
draw.rectangle([0, 0, W, 56], fill='#8B1A1A')
draw.text((W//2, 28), "手诊拍照示例", fill='white', font=f_bold, anchor='mm')

# ── 画一只手（左手）──
def draw_hand(draw, cx, cy, mirror=False, label_side='left'):
    """画一只手：掌面朝前，手指自然微屈露出指甲"""
    sc = 1.0
    if mirror:
        sc = -1.0  # 水平翻转用于画对侧手

    # 手掌（椭圆）
    palm_top = cy - 200
    palm_bot = cy + 180
    palm_w = 100
    draw.ellipse([cx-palm_w, palm_top, cx+palm_w, palm_bot],
                 outline='#333', width=3, fill='#FFF0E6')

    # 手腕
    wrist_y = palm_bot
    draw.rectangle([cx-60, wrist_y, cx+60, wrist_y+80],
                   outline='#333', width=2, fill='#FFF0E6')

    # 手指（5根，自然微屈）
    finger_base_y = palm_top + 40
    finger_names = ['拇指','食指','中指','无名指','小指']
    finger_x_offsets = [-80, -40, 0, 40, 70]
    finger_lengths = [120, 180, 200, 180, 150]
    finger_widths = [28, 22, 22, 20, 18]

    for i in range(5):
        fx = cx + finger_x_offsets[i] * sc
        fy = finger_base_y + (140 - finger_lengths[i]*0.3)  # 微屈缩短
        fl = finger_lengths[i]
        fw = finger_widths[i]

        # 手指段 1（近端）
        seg1_h = fl * 0.4
        draw.rounded_rectangle(
            [fx-fw//2, fy, fx+fw//2, fy+seg1_h],
            radius=8, outline='#333', width=2, fill='#FFF0E6')

        # 手指段 2（中段，微屈角度）
        seg2_h = fl * 0.35
        fy2 = fy + seg1_h
        bend = 8 * sc  # 微弯曲折
        draw.rounded_rectangle(
            [fx-fw//2+bend//2, fy2, fx+fw//2+bend//2, fy2+seg2_h],
            radius=7, outline='#333', width=2, fill='#FFF0E6')

        # 指端（末段 + 指甲）
        fy3 = fy2 + seg2_h
        nail_h = fl * 0.25
        draw.rounded_rectangle(
            [fx-fw//2+bend, fy3, fx+fw//2+bend, fy3+nail_h],
            radius=6, outline='#333', width=2, fill='#FFF0E6')

        # 指甲（在指端上方可见）
        nail_w = fw - 8
        nail_margin = 4
        draw.rounded_rectangle(
            [fx-nail_w//2+bend, fy3+nail_margin, fx+nail_w//2+bend, fy3+nail_h-nail_margin],
            radius=4, outline='#E8A0A0', width=2, fill='#FFD4D4')

        # 甲半月（月牙白）
        draw.arc(
            [fx-nail_w//2+bend+3, fy3+nail_margin-2, fx+nail_w//2+bend-3, fy3+nail_margin+14],
            180, 360, fill='#FFFFFF', width=3)

        # 指腹褶纹
        if finger_names[i] != '拇指':
            for j in range(2):
                rx = fx - fw//2 + 3 + j*8
                ry = fy3 + nail_h - 10
                draw.arc([rx, ry, rx+fw-14, ry+6], 0, 180, fill='#CCBBAA', width=1)

    # 掌纹（生命线、智慧线、感情线示意）
    # 生命线
    draw.arc([cx-55, cy-80, cx-20, cy+60], 160, 320, fill='#D4A574', width=2)
    # 智慧线
    draw.arc([cx-30, cy-50, cx+50, cy+10], 170, 330, fill='#D4A574', width=2)
    # 感情线
    draw.arc([cx-40, cy-10, cx+70, cy+60], 180, 310, fill='#D4A574', width=2)

    # ── 标注 ──
    off = 1 if label_side == 'right' else -1
    anchor = 'la' if label_side == 'right' else 'ra'
    lx = cx + off * 140

    # 甲床标注（指向食指指甲）
    ax = cx + finger_x_offsets[1] * sc + 30*sc
    ay = finger_base_y + 130
    draw.line([(ax, ay), (lx, ay-20)], fill='#E74C3C', width=2)
    draw.text((lx, ay-25), "甲床颜色/形态\n(淡白·红润·暗紫)", fill='#E74C3C', font=f_small, anchor=anchor)

    # 手掌颜色标注
    draw.line([(cx, cy+40), (lx+off*30, cy+80)], fill='#2980B9', width=2)
    draw.text((lx, cy+85), "手掌颜色\n(淡白·红·暗红)", fill='#2980B9', font=f_small, anchor=anchor)

    # 温度标注
    draw.line([(cx-60, cy-140), (lx, cy-160)], fill='#D4770A', width=2)
    draw.text((lx, cy-165), "手掌温度\n(温·凉·厥冷)", fill='#D4770A', font=f_small, anchor=anchor)

# ── 画两只手 ──
draw_hand(draw, W//3, H//2-30, mirror=False, label_side='left')
draw_hand(draw, W*2//3, H//2+20, mirror=True, label_side='right')

# ── 底部提示 ──
tips = [
    "● 双手并排，掌面朝镜头，手指自然微屈",
    "● 甲床（指甲颜色/形态）从指端正面可见",
    "● 双手一起拍，便于左右对比色泽差异",
]
for i, t in enumerate(tips):
    draw.text((W//2, H-140+i*28), t, fill='#666', font=f_norm, anchor='ma')

draw.text((W-16, H-16), "示意图 · 仅供参考", fill='#AAA', font=f_small, anchor='rb')

img.save(OUT, quality=95)
print(f"✅ {OUT}")
