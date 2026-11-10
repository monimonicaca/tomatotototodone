# -*- coding: utf-8 -*-
"""计时器视图：把 TimerSnapshot 画到画布上。

视图不持有业务状态、不调度计时——每次 render 都是无副作用的纯绘制，
输入是完全自描述的快照对象，方便离屏测试或替换皮肤。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..constants import WINDOW_H, WINDOW_W as W
from ..engine import MODE_LABELS, MODES
from ..theme import Theme
from .canvas_helpers import fit_text, round_rect

# ---- 布局几何（仅视图关心）----
CARD = (12, 8, W - 12, WINDOW_H - 8, 26)   # x1, y1, x2, y2, 圆角
CX, CY, R, RW = W // 2, 158, 82, 8          # 圆环圆心/半径/线宽
PILLS_Y, PILL_H, PILL_GAP = 272, 32, 10
PILL_WIDTHS = {"focus": 78, "short": 92, "long": 92}
CTRL_Y = 328                                # 控制行中线
START_HALF_W, START_HALF_H = 64, 21         # 主按钮药丸半径
FOOT_Y = 378                                # 底部统计行
BRAND_FONT = ("Segoe UI", 14, "bold")       # 左上角品牌/任务标题
BRAND_SUB_FONT = ("Segoe UI", 8, "bold")
BRAND_MAX_W = 150                           # 标题最大宽度（不覆盖 ☰ 图标区）


@dataclass
class TimerHandlers:
    """视图 -> 外部的回调，全部是普通函数，不反向依赖控制器类型。"""
    on_toggle: Callable[[], None]
    on_reset: Callable[[], None]
    on_skip: Callable[[], None]
    on_switch_mode: Callable[[str], None]
    on_open_settings: Callable[[], None]
    on_open_todos: Callable[[], None]
    on_toggle_pin: Callable[[], None]
    on_close: Callable[[], None]


@dataclass
class TimerSnapshot:
    """一次渲染所需的全部状态快照。"""
    mode: str
    remaining: int
    total: int
    running: bool
    today_count: int
    in_set: int
    task_title: str = ""       # 当前任务，空串表示未绑定
    pinned: bool = False       # 是否固定置顶（图钉状态）

    @property
    def progress(self) -> float:
        return (self.remaining / self.total) if self.total > 0 else 0.0

    @property
    def digits(self) -> str:
        m, s = divmod(max(0, self.remaining), 60)
        return f"{m:02d}:{s:02d}"

    @property
    def sub_label(self) -> str:
        if self.running:
            return "保持专注" if self.mode == "focus" else "放松一下"
        return "准备开始" if self.remaining == self.total else "已暂停"

    @property
    def start_label(self) -> str:
        if self.running:
            return "暂停"
        return "开始专注" if self.remaining == self.total else "继续"


class TimerView:
    drag_tag = "card"   # 可拖拽区域 tag，由窗口层绑定拖拽

    def __init__(self, canvas, theme: Theme, handlers: TimerHandlers):
        self.cv = canvas
        self.theme = theme
        self.h = handlers
        self._build()

    # ---------- 构建静态元素 ----------
    def _build(self):
        cv, th = self.cv, self.theme

        # 卡片（唯一的拖拽区域）
        round_rect(cv, *CARD, fill=th.card, outline=th.card_edge,
                   width=1, tags=self.drag_tag)

        # 顶部品牌区（标题随当前任务切换，见 render）
        cv.create_text(34, 32, text="●", font=("Segoe UI", 15),
                       fill=th.pink, anchor="w")
        self._brand_title_id = cv.create_text(
            58, 26, text="番茄钟", font=BRAND_FONT, fill=th.ink, anchor="w")
        self._brand_sub_id = cv.create_text(
            58, 44, text="FOCUS · POMODORO", font=BRAND_SUB_FONT,
            fill=th.faint, anchor="w")
        self._top_icon(cv, "☰", W - 116, 30, self.h.on_open_todos)  # 待办
        self._pin_ids = self._draw_pin(cv, W - 90, 30)               # 固定
        self._top_icon(cv, "⚙", W - 64, 30, self.h.on_open_settings)
        self._top_icon(cv, "✕", W - 38, 30, self.h.on_close)        # 退出

        # 进度环（轨道为完整圆；进度环首次 render 时创建）
        self._ring_bbox = (CX - R, CY - R, CX + R, CY + R)
        cv.create_oval(self._ring_bbox, outline=th.track, width=RW)
        self._progress_id = None
        self._phase_id = cv.create_text(CX, CY - 60, text="",
                                        font=("Segoe UI", 10, "bold"),
                                        fill=th.muted)
        self._digits_id = cv.create_text(CX, CY + 2, text="25:00",
                                         font=("Bahnschrift", 44, "bold"),
                                         fill=th.ink)
        self._sub_id = cv.create_text(CX, CY + 54, text="准备开始",
                                      font=("Segoe UI", 9), fill=th.faint)

        # 阶段药丸
        self._pill_rects, self._pill_texts = {}, {}
        total_w = sum(PILL_WIDTHS.values()) + PILL_GAP * (len(MODES) - 1)
        x = W // 2 - total_w // 2
        for m in MODES:
            w = PILL_WIDTHS[m]
            rect = round_rect(cv, x, PILLS_Y, x + w, PILLS_Y + PILL_H, 16,
                              fill=th.pill, width=0, tags=f"pill::{m}")
            text = cv.create_text(x + w // 2, PILLS_Y + PILL_H // 2,
                                  text=MODE_LABELS[m],
                                  font=("Segoe UI", 11, "bold"),
                                  fill=th.muted, tags=f"pill::{m}")
            cv.tag_bind(f"pill::{m}", "<Button-1>",
                        lambda e, m=m: self.h.on_switch_mode(m))
            self._pill_rects[m], self._pill_texts[m] = rect, text
            x += w + PILL_GAP

        # 控制行
        self._clickable(cv.create_text(58, CTRL_Y, text="重置",
                                       font=("Segoe UI", 11, "bold"),
                                       fill=th.muted), self.h.on_reset)
        self._start_pill_id = round_rect(
            cv, W // 2 - START_HALF_W, CTRL_Y - START_HALF_H,
            W // 2 + START_HALF_W, CTRL_Y + START_HALF_H, 16,
            fill=th.lavender, width=0)
        self._start_text_id = cv.create_text(W // 2, CTRL_Y,
                                             text="开始专注",
                                             font=("Segoe UI", 12, "bold"),
                                             fill=th.btn_ink)
        self._clickable(self._start_pill_id, self.h.on_toggle)
        self._clickable(self._start_text_id, self.h.on_toggle)
        self._clickable(cv.create_text(W - 38, CTRL_Y, text="跳过",
                                       font=("Segoe UI", 11, "bold"),
                                       fill=th.muted), self.h.on_skip)

        # 底部统计
        cv.create_text(30, FOOT_Y, text="今日", font=("Segoe UI", 9),
                       fill=th.faint, anchor="w")
        self._count_id = cv.create_text(62, FOOT_Y, text="0 个番茄",
                                        font=("Segoe UI", 9),
                                        fill=th.muted, anchor="w")
        self._dots = []
        x = W - 44
        for _ in range(4):
            self._dots.append(cv.create_oval(x - 5, FOOT_Y - 5, x + 5,
                                             FOOT_Y + 5, fill=th.track,
                                             outline=""))
            x -= 17

    # ---------- 渲染 ----------
    def render(self, snap: TimerSnapshot):
        cv, th = self.cv, self.theme
        color = th.color_for_mode(snap.mode)

        # 左上角标题随当前任务切换（无任务时回归品牌名）
        if snap.task_title:
            cv.itemconfig(self._brand_title_id,
                          text=fit_text(cv, snap.task_title, BRAND_FONT,
                                        BRAND_MAX_W))
            cv.itemconfig(self._brand_sub_id, text="CURRENT TASK")
        else:
            cv.itemconfig(self._brand_title_id, text="番茄钟")
            cv.itemconfig(self._brand_sub_id, text="FOCUS · POMODORO")

        cv.itemconfig(self._digits_id, text=snap.digits)
        cv.itemconfig(self._phase_id, text=MODE_LABELS[snap.mode], fill=color)
        cv.itemconfig(self._sub_id, text=snap.sub_label)
        cv.itemconfig(self._start_text_id, text=snap.start_label)
        cv.itemconfig(self._start_pill_id, fill=color)

        # 进度环：满圆时钳到 ±359°，避免 tkinter 整圆 arc 退化不渲染
        extent = -359.0 * snap.progress
        if self._progress_id is None:
            self._progress_id = cv.create_arc(self._ring_bbox, start=90,
                                              extent=extent, style="arc",
                                              outline=color, width=RW)
        else:
            cv.itemconfig(self._progress_id, extent=extent, outline=color)

        for m, rect in self._pill_rects.items():
            active = (m == snap.mode)
            if active:
                # 选中态直接用该阶段的主题色（专注薰衣/短休薄荷/长休蜜桃）
                cv.itemconfig(rect, fill=th.color_for_mode(m))
                cv.itemconfig(self._pill_texts[m], fill=th.btn_ink)
            else:
                cv.itemconfig(rect, fill=th.pill)
                cv.itemconfig(self._pill_texts[m], fill=th.muted)

        cv.itemconfig(self._count_id, text=f"{snap.today_count} 个番茄")
        for i, dot in enumerate(self._dots):
            cv.itemconfig(dot, fill=th.pink if i < snap.in_set else th.track)

        self._style_pin(snap.pinned)

    # ---------- 图钉（固定置顶）----------
    def _draw_pin(self, cv, x, y):
        """自绘图钉：针头圆 + 针身线。矢量绘制保证两个状态都能自由着色。"""
        head = cv.create_oval(x - 4, y - 8, x + 4, y, width=1.5)
        needle = cv.create_line(x, y - 1, x, y + 6, width=1.5,
                                capstyle="round")
        for item in (head, needle):
            cv.tag_bind(item, "<Button-1>",
                        lambda e: self.h.on_toggle_pin())
        return (head, needle)

    def _style_pin(self, pinned: bool):
        """固定中：粉紫实心；未固定：灰色空心。"""
        cv, th = self.cv, self.theme
        head, needle = self._pin_ids
        if pinned:
            cv.itemconfig(head, fill=th.pink_deep, outline=th.pink_deep)
            cv.itemconfig(needle, fill=th.pink_deep)
        else:
            cv.itemconfig(head, fill="", outline=th.faint)
            cv.itemconfig(needle, fill=th.faint)

    # ---------- 工具 ----------
    def _top_icon(self, cv, glyph, x, y, cb):
        item = cv.create_text(x, y, text=glyph,
                              font=("Segoe UI Symbol", 12),
                              fill=self.theme.muted)
        cv.tag_bind(item, "<Button-1>", lambda e: cb())

    def _clickable(self, item, callback):
        self.cv.tag_bind(item, "<Button-1>", lambda e: callback())
