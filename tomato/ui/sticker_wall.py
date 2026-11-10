# -*- coding: utf-8 -*-
"""桌面番茄贴纸墙：每完成一个专注贴一颗"马卡龙番茄"。

设计要点：
- 纯展示：Windows 扩展样式 WS_EX_TRANSPARENT + WS_EX_NOACTIVATE，
  完全点击穿透、永不抢焦点——就是"贴在桌面上"的装饰；
- 展示数量 = 今日已完成番茄数（与统计同源，重启后自动恢复）；
- 超出屏幕可容纳数量时收起为最下方的 "+N"。
"""
from __future__ import annotations

import ctypes
import tkinter as tk

from ..theme import Theme
from .window import primary_screen

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000

WALL_W = 84
CELL = 70
TOP_PAD = 58


class StickerWall:
    def __init__(self, root, theme: Theme, transparent_key: str):
        self.theme = theme
        self.enabled = True
        self._count = 0

        self.win = tk.Toplevel(root)
        self.win.title("番茄钟·贴纸墙")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        bg = theme.card
        try:
            self.win.attributes("-transparentcolor", transparent_key)
            bg = transparent_key
        except tk.TclError:
            pass
        self.cv = tk.Canvas(self.win, bg=bg, highlightthickness=0, bd=0)
        self.cv.pack()
        self.win.withdraw()

    # ---------- 对外接口 ----------
    @property
    def count(self) -> int:
        return self._count

    def set_count(self, n: int):
        """更新今日贴纸数（<=0 或已停用时隐藏）。"""
        self._count = max(0, int(n))
        self._apply()

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        self._apply()

    def set_topmost(self, topmost: bool):
        try:
            self.win.attributes("-topmost", topmost)
        except tk.TclError:
            pass

    # ---------- 内部 ----------
    def _apply(self):
        n = self._count if self.enabled else 0
        self.cv.delete("all")
        if n <= 0:
            self.win.withdraw()
            return

        _, sh = primary_screen()
        max_fit = max(1, min(12, (sh - TOP_PAD - 120) // CELL))
        shown = min(n, max_fit)
        overflow = n - shown
        wall_h = 64 + shown * CELL + (30 if overflow > 0 else 0)

        self.cv.config(width=WALL_W, height=wall_h)
        self.win.geometry(f"{WALL_W}x{wall_h}+8+{TOP_PAD - 30}")

        for i in range(shown):
            jitter = 6 if i % 2 else -6        # 微微歪扭，手贴感
            self._draw_tomato(WALL_W // 2 + jitter,
                              32 + TOP_PAD - 30 + i * CELL + 26, 24)
        if overflow > 0:
            self.cv.create_text(WALL_W // 2, wall_h - 15,
                                text=f"+{overflow}",
                                font=("Segoe UI", 11, "bold"),
                                fill=self.theme.muted)

        self._make_click_through()
        self.win.deiconify()

    def _draw_tomato(self, cx: int, cy: int, r: int):
        """马卡龙风味番茄：粉身 + 薄荷叶 + 白色贴纸边。"""
        th = self.theme
        # 贴纸白边
        self.cv.create_oval(cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3,
                            fill="#ffffff", outline="")
        # 果身（淡粉）
        self.cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                            fill=th.pink, outline=th.pink_deep, width=2)
        # 叶子（薄荷，手绘感三角化圆）
        self.cv.create_polygon(cx, cy - r - 1, cx + 13, cy - r + 9,
                               cx - 13, cy - r + 9,
                               smooth=True, fill=th.mint,
                               outline=th.mint_deep, width=1)
        # 果柄（薰衣小段）
        self.cv.create_line(cx, cy - r - 2, cx, cy - r + 6,
                            fill=th.lavender_deep, width=3)
        # 高光
        self.cv.create_oval(cx - r * 0.5, cy - r * 0.5,
                            cx - r * 0.15, cy - r * 0.15,
                            fill="#ffffff", outline="")

    def _make_click_through(self):
        """点击穿透 + 不抢焦点。失败则退化为普通置顶窗口。"""
        try:
            user32 = ctypes.windll.user32
            hwnd = int(self.win.frame(), 16)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                style | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        except Exception:
            pass
