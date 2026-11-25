"""锁屏暂停覆盖层：电脑锁屏时盖住当前页面的大弹窗（约 70% 显示面积）。

由 mail_monitor 的锁屏监视线程触发：pauselock 渲染（底图=当前页缓存重渲，
另存 pause_base.png 供恢复）并推送本覆盖层；解锁后 resume 把底图原样推回，
像素级还原锁屏前画面。视觉与邮件弹窗同家族：1px 黑框 + 浅抖动投影 +
Tabler 线稿挂锁（lock 字形为 2026-10-27 子集化补入，见 fonts/tabler/）。
"""
from PIL import ImageDraw

from epd_dashboard.config import EPD_HEIGHT, EPD_WIDTH
from epd_dashboard.fonts import FONT_STRONG, noto
from epd_dashboard.renderers.landscape.common import draw_tabler, dither_rect
from epd_dashboard.renderers.landscape.page4_analysis import BODY_TEXT_WEIGHT

CARD_W, CARD_H = 680, 400        # 70.8% 显示面积
SHADOW_OFFSET = 8


def render_pause_overlay(base, now):
    image = base.copy()
    draw = ImageDraw.Draw(image)
    x0 = (EPD_WIDTH - CARD_W) // 2
    x1 = x0 + CARD_W
    y0 = (EPD_HEIGHT - CARD_H) // 2
    y1 = y0 + CARD_H

    # 投影（浅抖动灰）→ 卡片白底 + 1px 黑框
    dither_rect(image, (x0 + SHADOW_OFFSET, y0 + SHADOW_OFFSET,
                        x1 + SHADOW_OFFSET, y1 + SHADOW_OFFSET), level="light")
    draw.rectangle((x0, y0, x1, y1), fill=255, outline=0, width=2)

    cx = (x0 + x1) / 2
    # 挂锁（Tabler lock 线稿，大图标锚点）
    draw_tabler(draw, cx, y0 + 96, 88, "lock")
    # 标题 / 副题 / 状态行，垂直节奏 30/24/16
    draw.text((cx, y0 + 210), "显示已暂停", font=noto(30, FONT_STRONG),
              fill=0, anchor="mm")
    draw.text((cx, y0 + 254), "电脑已锁屏，内容更新暂停", font=noto(20, BODY_TEXT_WEIGHT),
              fill=0, anchor="mm")
    draw.text((cx, y1 - 30), f"暂停于 {now.strftime('%H:%M')} · 解锁电脑后自动恢复",
              font=noto(16, 400), fill=0, anchor="mm")
    return image
