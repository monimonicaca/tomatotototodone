# -*- coding: utf-8 -*-
"""悬浮窗口外壳与屏幕定位工具：无边框、置顶、透明角、拖拽、多显示器安全。

FloatingWindow 只关心"窗口层"能力，不含业务绘制。
primary_screen / clamp_to_screen 是模块级工具，
主卡、待办面板、贴纸墙都经它们定位，共享同一套多屏安全逻辑。
"""
from __future__ import annotations

import ctypes
import tkinter as tk

from ..constants import WINDOW_H, WINDOW_W


def primary_screen() -> tuple:
    """主屏尺寸（主屏原点恒为 0,0，不受副屏影响）。"""
    try:
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        h = user32.GetSystemMetrics(1)   # SM_CYSCREEN
        if w > 0 and h > 0:
            return (w, h)
    except Exception:
        pass
    return (1280, 720)


def clamp_to_screen(x: int, y: int, w: int, h: int) -> tuple:
    """约束 w*h 窗口到可见虚拟桌面内：坐标落在已拔掉的显示器上也能拉回。"""
    try:
        user32 = ctypes.windll.user32
        left = user32.GetSystemMetrics(76)    # SM_XVIRTUALSCREEN
        top = user32.GetSystemMetrics(77)     # SM_YVIRTUALSCREEN
        width = user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        if width > 0 and height > 0:
            x = max(left, min(x, left + width - w))
            y = max(top, min(y, top + height - h))
    except Exception:
        pass
    return (x, y)


class FloatingWindow:
    def __init__(self, root: tk.Tk, *,
                 transparent_key: str | None = None,
                 pos: tuple | None = None,
                 topmost: bool = True):
        self.root = root
        root.overrideredirect(True)          # 无边框
        root.attributes("-topmost", topmost)

        # 逐像素透明（Windows）；不支持则退化为普通白底窗口
        self._transparent_key = transparent_key
        bg = "#ffffff"
        if transparent_key:
            try:
                root.attributes("-transparentcolor", transparent_key)
                bg = transparent_key
            except tk.TclError:
                self._transparent_key = None

        self.canvas = tk.Canvas(root, width=WINDOW_W, height=WINDOW_H,
                                bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        x, y = pos if pos else self._default_position()
        x, y = clamp_to_screen(x, y, WINDOW_W, WINDOW_H)
        root.geometry(f"{WINDOW_W}x{WINDOW_H}+{x}+{y}")
        root.update_idletasks()

        self._drag_offset: tuple | None = None

    # ---------- 状态 ----------
    @property
    def position(self) -> tuple:
        return (self.root.winfo_x(), self.root.winfo_y())

    @property
    def topmost(self) -> bool:
        try:
            return bool(self.root.attributes("-topmost"))
        except tk.TclError:
            return True

    def set_topmost(self, enabled: bool):
        self.root.attributes("-topmost", enabled)

    def close(self):
        self.root.destroy()

    # ---------- 拖拽 ----------
    def bind_drag(self, tag_or_id):
        """把拖拽绑定到画布元素（一般是卡片底）。"""
        self.canvas.tag_bind(tag_or_id, "<Button-1>", self._press)
        self.canvas.tag_bind(tag_or_id, "<B1-Motion>", self._dragging)

    def _press(self, event):
        self._drag_offset = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())

    def _dragging(self, event):
        if not self._drag_offset:
            return
        dx, dy = self._drag_offset
        x, y = clamp_to_screen(event.x_root - dx, event.y_root - dy,
                               WINDOW_W, WINDOW_H)
        self.root.geometry(f"+{x}+{y}")

    # ---------- 右键菜单挂载 ----------
    def on_context_menu(self, handler):
        self.canvas.bind("<Button-3>", handler)

    # ---------- 默认定位 ----------
    @staticmethod
    def _default_position() -> tuple:
        """默认落在主屏右上角。"""
        sw, _ = primary_screen()
        return (max(0, sw - WINDOW_W - 40), 60)
