# -*- coding: utf-8 -*-
"""统计视图：今日 / 本周 / 本月 + 近 7 天柱状图。

普通 Toplevel（带系统标题栏，瞬态对话框），数据由 make_snapshot
从 HistoryLog 一次性算好传入——视图不直接依赖存储。
"""
from __future__ import annotations

import datetime
import tkinter as tk
from dataclasses import dataclass

from ..history import HistoryLog
from ..theme import Theme

WEEKDAY_CN = "一二三四五六日"     # ISO weekday: 0=周一
NUM_FONT = ("Bahnschrift", 26, "bold")
LABEL_FONT = ("Segoe UI", 9)
SMALL_FONT = ("Segoe UI", 8)


@dataclass
class StatsSnapshot:
    today: int
    week: int
    month: int
    total: int
    bars: list          # [(label, count, is_today), ...] 正序


def make_snapshot(history: HistoryLog, today: str) -> StatsSnapshot:
    """把历史聚合成渲染快照（周一起始的 ISO 周、自然月）。"""
    bars = []
    for date, cnt in history.last_days(today, 7):
        try:
            wd = datetime.date.fromisoformat(date).weekday()
        except (TypeError, ValueError):
            continue
        label = "今天" if date == today else WEEKDAY_CN[wd]
        bars.append((label, cnt, date == today))
    return StatsSnapshot(
        today=history.day_total(today),
        week=history.week_total(today),
        month=history.month_total(today),
        total=history.total(),
        bars=bars,
    )


class StatsView:
    def __init__(self, parent, theme: Theme, snap: StatsSnapshot):
        self.theme = theme
        self.snap = snap

        self.win = tk.Toplevel(parent)
        self.win.title("番茄钟 · 统计")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=theme.card)

        self._build()
        self.win.grab_set()
        self.win.focus_set()

    # ---------- 构建 ----------
    def _build(self):
        th = self.theme
        self.win.configure(padx=22, pady=16)

        # 三个数字
        nums = tk.Frame(self.win, bg=th.card)
        nums.pack(pady=(0, 12))
        cells = [("今日", snap_val := self.snap.today, th.pink_ink),
                 ("本周", self.snap.week, th.lavender_ink),
                 ("本月", self.snap.month, th.mint_ink)]
        for i, (label, val, color) in enumerate(cells):
            cell = tk.Frame(nums, bg=th.card)
            cell.grid(row=0, column=i, padx=16)
            tk.Label(cell, text=label, bg=th.card, fg=th.muted,
                     font=LABEL_FONT).pack()
            tk.Label(cell, text=str(val), bg=th.card, fg=color,
                     font=NUM_FONT).pack()

        # 近 7 天柱状图
        self.chart = tk.Canvas(self.win, width=296, height=150,
                               bg=th.card, highlightthickness=0)
        self.chart.pack()
        self._draw_bars()

        # 累计
        tk.Label(self.win, text=f"累计 {self.snap.total} 个番茄",
                 bg=th.card, fg=th.faint,
                 font=SMALL_FONT).pack(pady=(6, 0))

    def _draw_bars(self):
        cv, th = self.chart, self.theme
        n = len(self.snap.bars) or 1
        slot = 296 / n
        base_y, max_h = 112, 82
        max_v = max((c for _, c, _ in self.snap.bars), default=0) or 1

        for i, (label, cnt, is_today) in enumerate(self.snap.bars):
            x1 = 14 + i * slot + slot * 0.22
            x2 = 14 + (i + 1) * slot - slot * 0.22
            h = int(cnt / max_v * max_h)
            y1 = base_y - h
            fill = th.lavender if is_today else th.pill
            outline = th.lavender_deep if is_today else th.pill_active
            cv.create_rectangle(x1, y1, x2, base_y, fill=fill,
                                outline=outline, width=1)
            if cnt > 0:
                cv.create_text((x1 + x2) / 2, y1 - 10, text=str(cnt),
                               font=LABEL_FONT, fill=th.muted)
            cv.create_text((x1 + x2) / 2, base_y + 14, text=label,
                           font=(LABEL_FONT + ("bold",)) if is_today else LABEL_FONT,
                           fill=(th.pink_ink if is_today else th.faint))
        # 基线
        cv.create_line(10, base_y, 286, base_y, fill=th.pill_active, width=1)
