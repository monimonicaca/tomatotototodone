# -*- coding: utf-8 -*-
"""Canvas 绘图小工具：圆角矩形、按像素测量/截断文本。

被主卡、待办面板、统计图共用——消除各视图重复实现。
"""
from __future__ import annotations

import tkinter.font as tkfont


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    """用平滑 polygon 模拟圆角矩形（tkinter 没有原生 round rect）。"""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def text_width(canvas, text, font_spec) -> int:
    """测量文本像素宽；无字体环境时退化估算。"""
    text = str(text or "")
    try:
        return tkfont.Font(font=font_spec).measure(text)
    except Exception:
        return len(text) * 10


def fit_text(canvas, text, font_spec, max_px) -> str:
    """超宽文本截断并加省略号。"""
    text = str(text or "")
    if text_width(canvas, text, font_spec) <= max_px:
        return text
    out = text
    while out and text_width(canvas, out + "…", font_spec) > max_px:
        out = out[:-1]
    return out + "…"
