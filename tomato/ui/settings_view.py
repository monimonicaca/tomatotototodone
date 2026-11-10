# -*- coding: utf-8 -*-
"""时长设置对话框：输入合法性交给 Durations 统一钳制，确定后回调。"""
from __future__ import annotations

import tkinter as tk

from ..constants import MAX_MINUTES, MIN_MINUTES
from ..engine import Durations
from ..theme import Theme

FIELDS = (
    ("focus", "专注（分钟）"),
    ("short", "短休息（分钟）"),
    ("long", "长休息（分钟）"),
)


class SettingsDialog:
    def __init__(self, parent, durations: Durations, on_apply, theme: Theme):
        self._on_apply = on_apply
        self._theme = theme

        self.win = tk.Toplevel(parent)
        self.win.title("时长设置")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=theme.card, padx=14, pady=10)

        self._vars: dict[str, tk.StringVar] = {}
        for i, (key, label) in enumerate(FIELDS):
            tk.Label(self.win, text=label, bg=theme.card,
                     fg=theme.ink).grid(row=i, column=0, sticky="w",
                                        padx=(0, 12), pady=5)
            var = tk.StringVar(value=str(getattr(durations, key)))
            sb = tk.Spinbox(self.win, from_=MIN_MINUTES, to=MAX_MINUTES,
                            width=6, textvariable=var, bg=theme.pill,
                            relief="flat", buttonbackground=theme.pill)
            sb.grid(row=i, column=1, pady=5)
            self._vars[key] = var

        tk.Label(self.win, text="每完成 4 个专注，自动进入长休息；运行中的阶段不受修改影响。",
                 bg=theme.card, fg=theme.faint,
                 font=("Segoe UI", 8)).grid(row=len(FIELDS), column=0,
                                            columnspan=2, sticky="w",
                                            pady=(6, 10))
        bar = tk.Frame(self.win, bg=theme.card)
        bar.grid(row=len(FIELDS) + 1, column=0, columnspan=2)
        tk.Button(bar, text="应用", bg=theme.lavender, fg=theme.btn_ink,
                  relief="flat", padx=14, command=self._apply
                  ).pack(side="left", padx=6)
        tk.Button(bar, text="取消", bg=theme.pill, fg=theme.ink,
                  relief="flat", padx=14,
                  command=self.win.destroy).pack(side="left")

        try:
            self.win.grab_set()   # 模态，避免和主窗交互打架
        except tk.TclError:
            pass
        self.win.lift()

    def _apply(self):
        try:
            d = Durations(focus=self._vars["focus"].get(),
                          short=self._vars["short"].get(),
                          long=self._vars["long"].get())
        except Exception:
            return
        self._on_apply(d)
        self.win.destroy()
