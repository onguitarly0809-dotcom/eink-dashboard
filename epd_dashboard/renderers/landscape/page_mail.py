"""邮件提醒弹窗层（横版插播）：在当前页面之上叠加"手机二级菜单"式提醒卡片。

背景 = 被覆盖的当前页（cli 侧按页状态从缓存纯渲染出底图，另存 mail_base.png）；
弹窗 = 居中卡片（1px 黑框 + 浅抖动投影 + 黑标题带"家族脸"），列最近 ≤3 封新邮件。

生命周期由监控进程管理：新邮件到达时 control mail 上屏（底图随存）；
overlay_seconds（默认 10 分钟）后 control mailoff 把 mail_base.png 原样推回，
像素级还原被覆盖页；期间若轮播/手动动作已切页（页状态变化）则跳过还原。
"""
from PIL import Image, ImageDraw

from epd_dashboard.config import EPD_HEIGHT, EPD_WIDTH
from epd_dashboard.fonts import FONT_STRONG, noto
from epd_dashboard.renderers.landscape.common import (
    dither_rect,
    truncate_text,
    wrap_text,
)
from epd_dashboard.renderers.landscape.page4_analysis import BODY_TEXT_WEIGHT

CARD_W = 640          # 卡片宽：两侧各留 80px 露出底层页面
BAND_H = 40           # 黑标题带高
ENTRY_H = 96          # 每封邮件槽位（发件人行 + 主题两行）
FOOTER_H = 28         # 底部"自动收起"提示行
MAX_SHOWN = 3
SHADOW_OFFSET = 6     # 投影偏移（右下）


def _draw_envelope(draw, cx, cy, size, fill=255):
    """手绘信封线稿：随项目分发的 Tabler 子集不含邮件图标，这里按同款 2px
    线稿风格自绘（矩形 + 折线封口），黑标题带内白色。"""
    half = size / 2
    x0, x1 = cx - half, cx + half
    y0, y1 = cy - half, cy + half
    draw.rectangle((x0, y0, x1, y1), outline=fill, width=2)
    mid_y = cy + size * 0.08
    draw.line((x0 + 1, y0 + 1, cx, mid_y), fill=fill, width=2)
    draw.line((x1 - 1, y0 + 1, cx, mid_y), fill=fill, width=2)


def render_mail_overlay(base, payload, now):
    """把邮件提醒卡片叠加在底图 base（当前页渲染结果）上，返回新图。

    不修改 base 本身（调用方要把 base 另存为还原基准）。
    """
    image = base.copy()
    draw = ImageDraw.Draw(image)
    payload = payload or {}
    mails = payload.get("mails") or []
    account = payload.get("account") or "邮箱"
    total_new = payload.get("total_new") or len(mails)

    # 卡片高度随邮件数自适应（1~3 封），空防御分支按单行高度。
    # 垂直居中再下移 6px：多数页面自带顶部黑标题带，与卡片黑带等高并列时
    # 光学上显得顶部拥挤，下移后上下留白更均匀
    n = max(1, min(len(mails), MAX_SHOWN))
    card_h = BAND_H + n * ENTRY_H + FOOTER_H
    x0 = (EPD_WIDTH - CARD_W) // 2
    x1 = x0 + CARD_W
    y0 = (EPD_HEIGHT - card_h) // 2 + 6
    y1 = y0 + card_h

    # 投影（浅抖动灰）→ 卡片白底 + 1px 黑框：悬浮层次感
    dither_rect(image, (x0 + SHADOW_OFFSET, y0 + SHADOW_OFFSET,
                        x1 + SHADOW_OFFSET, y1 + SHADOW_OFFSET), level="light")
    draw.rectangle((x0, y0, x1, y1), fill=255, outline=0, width=1)

    # 黑标题带：信封图标 + 标题 + 右侧账号/新件数（家族脸）
    draw.rectangle((x0, y0, x1, y0 + BAND_H), fill=0)
    _draw_envelope(draw, x0 + 21, y0 + BAND_H // 2, 20)
    draw.text((x0 + 42, y0 + BAND_H // 2), "邮件提醒",
              font=noto(20, FONT_STRONG), fill=255, anchor="lm")
    draw.text((x1 - 14, y0 + BAND_H // 2), f"{account} · 新邮件 {total_new} 封",
              font=noto(16, 500), fill=255, anchor="rm")

    margin_x0, margin_x1 = x0 + 22, x1 - 22
    if not mails:
        draw.text(((x0 + x1) / 2, y0 + BAND_H + ENTRY_H / 2), "— 无新邮件 —",
                  font=noto(16, 400), fill=0, anchor="mm")
    else:
        sender_font = noto(18, FONT_STRONG)
        time_font = noto(16, 500)
        subject_font = noto(18, BODY_TEXT_WEIGHT)
        for index, mail in enumerate(mails[:MAX_SHOWN]):
            top = y0 + BAND_H + index * ENTRY_H
            time_text = mail.get("time") or now.strftime("%H:%M")
            time_w = draw.textlength(time_text, font=time_font)
            sender = truncate_text(draw, mail.get("from") or "(未知发件人)",
                                   sender_font, (margin_x1 - time_w - 20) - margin_x0)
            draw.text((margin_x0, top + 8), sender, font=sender_font, fill=0)
            draw.text((margin_x1, top + 10), time_text, font=time_font, fill=0, anchor="rs")
            lines = wrap_text(draw, mail.get("subject") or "(无主题)", subject_font,
                              margin_x1 - margin_x0)[:2]
            if lines:
                lines[-1] = truncate_text(draw, lines[-1], subject_font,
                                          margin_x1 - margin_x0)
            for line_no, line in enumerate(lines):
                draw.text((margin_x0, top + 40 + line_no * 24), line,
                          font=subject_font, fill=0)
            if index < n - 1:
                draw.line((margin_x0 - 8, top + ENTRY_H, margin_x1 + 8, top + ENTRY_H),
                          fill=0, width=1)

    # 底部提示：自动收起时间 + 溢出计数
    footer = "10 分钟后自动收起"
    if total_new > MAX_SHOWN:
        footer = f"共 {total_new} 封 · " + footer
    draw.text(((x0 + x1) / 2, y1 - FOOTER_H / 2), footer,
              font=noto(16, 400), fill=0, anchor="mm")
    return image
