# -*- coding: utf-8 -*-
"""迷你计时小窗：折叠态只显示标题 + 剩余时间，可一键展开回主卡。

与 TimerView 互补：主卡是完整交互，迷你窗是"只瞄一眼还剩多久"的收纳态。
迷你窗是主窗的 Toplevel 子窗，主窗关闭时会一并销毁；render(snapshot)
接收与主视图相同的快照，随计时逐拍刷新。
"""
from __future__ import annotations

import tkinter as tk

from ..engine import MODE_LABELS
from ..theme import Theme
from .canvas_helpers import fit_text, round_rect
from .window import clamp_to_screen

W, H = 216, 66                                   # 迷你窗整体尺寸
CARD = (6, 4, W - 6, H - 4, 14)                  # 卡片：x1,y1,x2,y2,圆角
TITLE_FONT = ("Segoe UI", 10, "bold")
TIME_FONT = ("Bahnschrift", 20, "bold")
TITLE_MAX_W = 118                                # 标题最大宽（让开右侧按钮区）


class MiniView:
    """迷你窗：标题 + 剩余时间 + 展开/退出。可拖动、置顶、透明角。"""

    drag_tag = "mini_card"

    def __init__(self, root, theme: Theme, *, on_expand, on_close,
                 pos=None, topmost: bool = True):
        self.theme = theme
        self.on_expand = on_expand
        self.on_close = on_close
        self._drag_state = None

        self.win = tk.Toplevel(root)
        self.win.title("番茄钟·迷你")
        self.win.overrideredirect(True)
        try:
            self.win.attributes("-topmost", topmost)
        except tk.TclError:
            pass
        bg = theme.card
        try:
            self.win.attributes("-transparentcolor", theme.transparent_key)
            bg = theme.transparent_key
        except tk.TclError:
            pass
        self.cv = tk.Canvas(self.win, width=W, height=H, bg=bg,
                            highlightthickness=0, bd=0)
        self.cv.pack()
        if pos is None:
            pos = (0, 0)
        px, py = clamp_to_screen(pos[0], pos[1], W, H)
        self.win.geometry(f"{W}x{H}+{px}+{py}")

        self._build()

    # ---------- 构建 ----------
    def _build(self):
        cv, th = self.cv, self.theme
        round_rect(cv, *CARD, fill=th.card, outline=th.card_edge, width=1,
                   tags=self.drag_tag)
        self._bind_drag(self.drag_tag)

        # 标题（当前任务名，无任务时用阶段名）
        self._title_id = cv.create_text(18, 21, text="番茄钟",
                                        font=TITLE_FONT, fill=th.muted,
                                        anchor="w")

        # 剩余时间（大号，随阶段换主题色）
        self._time_id = cv.create_text(18, 47, text="25:00",
                                       font=TIME_FONT, fill=th.ink,
                                       anchor="w")

        # 展开按钮：回到完整主卡
        self._expand_btn = tk.Button(
            self.win, text="展开", font=("Segoe UI", 10, "bold"),
            bg=th.lavender, fg=th.btn_ink, relief="flat",
            activebackground=th.pill_active, command=self.on_expand)
        self._expand_btn.place(x=W - 78, y=34, width=66, height=28)

        # 关闭按钮（退出整个应用）
        self._icon("✕", W - 16, 16, th.muted, self.on_close)

    # ---------- 渲染 ----------
    def render(self, snap):
        """与主视图同签名的快照渲染：刷新标题与剩余时间。"""
        cv, th = self.cv, self.theme
        title = snap.task_title or MODE_LABELS.get(snap.mode, "") or "番茄钟"
        cv.itemconfig(self._title_id,
                      text=fit_text(cv, title, TITLE_FONT, TITLE_MAX_W))
        cv.itemconfig(self._time_id, text=snap.digits)
        cv.itemconfig(self._time_id, fill=th.color_for_mode(snap.mode))

    # ---------- 工具 ----------
    def _icon(self, glyph, x, y, color, cb):
        item = self.cv.create_text(x, y, text=glyph,
                                   font=("Segoe UI Symbol", 12), fill=color)
        self.cv.tag_bind(item, "<Button-1>", lambda e: cb())

    # ---------- 拖拽 ----------
    def _bind_drag(self, tag):
        self.cv.tag_bind(tag, "<Button-1>", self._press)
        self.cv.tag_bind(tag, "<B1-Motion>", self._dragging)

    def _press(self, event):
        self._drag_state = (event.x_root - self.win.winfo_x(),
                            event.y_root - self.win.winfo_y())

    def _dragging(self, event):
        if not self._drag_state:
            return
        dx, dy = self._drag_state
        x, y = clamp_to_screen(event.x_root - dx, event.y_root - dy, W, H)
        self.win.geometry(f"+{x}+{y}")

    # ---------- 生命周期 ----------
    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass