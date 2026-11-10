# -*- coding: utf-8 -*-
"""今日待办面板：添加 / 选中 / 开始番茄 / 完成 / 删除 + 按天归档浏览。

视图不持有业务状态：所有动作通过 TodoHandlers 回调给 controller，
列表数据直接读传入的 TodoList，refresh() 随取随画。

两种形态（set_list 切换）：
- 今日（editable=True）：完整交互；
- 历史档案（editable=False）：只读快照——无输入行、无行按钮、不可选中，
  底部提示换为"历史归档·只读"。
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import END

from ..theme import Theme
from ..todo import TodoList
from .canvas_helpers import fit_text, round_rect, text_width
from .window import clamp_to_screen

W, H = 330, 430
CARD = (12, 8, W - 12, H - 8, 24)
LIST_TOP, LIST_BOT = 118, H - 50        # 列表区可视范围
ROW = 34                                 # 单行高
X_TEXT = 52                              # 文本起点
BTN_X = {"start": 96, "done": 64, "del": 36}   # 距右边缘
# 输入区（今日形态）：任务行 + 详情行，右侧按钮跨两行
ENTRY_Y, ENTRY_H = 56, 24               # 任务输入框
NOTE_LABEL = (34, 94)                    # “详情”小标签
NOTE_ENTRY = (50, 84, 180, 24)          # 详情输入框
ADD_BTN = (230, 56, 70, 56)             # 添加按钮（覆盖两行）
WEEKHINT_FONT = ("Segoe UI", 8)
TEXT_FONT = ("Segoe UI", 9)
ICON_FONT = ("Segoe UI Symbol", 12, "bold")   # 行内图标：细笔画字形需大号加粗才抗锯齿后仍清晰
HEADER_FONT = ("Segoe UI", 13, "bold")
SUB_FONT = ("Segoe UI", 8, "bold")
NAV_FONT = ("Segoe UI Symbol", 10, "bold")
DATE_FONT = ("Segoe UI", 8, "bold")
# 导航簇（副标题行右侧）：◀ 日期 ▶
NAV_PREV_X, NAV_DATE_X, NAV_NEXT_X, NAV_Y = 214, 252, 294, 44

HINT_TODAY = "点条目选中任务 · ▶ 开始番茄 · ✓ 完成（计时中自动结束） · ✕ 删除 · 双击看详情"
HINT_ARCHIVE = "历史归档 · 只读（✔ 为当天已完成项，番茄数为截至当天累计） · 双击看详情"


@dataclass
class TodoHandlers:
    """视图 -> controller 的回调集合。"""
    on_add: callable          # (text, note)
    on_select: callable       # (todo_id)
    on_start: callable        # (todo_id)
    on_toggle_done: callable  # (todo_id)
    on_remove: callable       # (todo_id)
    on_close: callable        # ()
    on_prev_day: callable     # ()  浏览更早一天
    on_next_day: callable     # ()  浏览更近一天（直到今天）


@dataclass
class NavState:
    """导航簇可用性（由 controller 根据归档天计算）。"""
    has_prev: bool = False
    has_next: bool = False
    visible: bool = True      # 完全没有历史桶时整个导航簇隐藏


class TodoView:
    drag_tag = "todo_card"

    def __init__(self, root, theme: Theme, todos: TodoList,
                 handlers: TodoHandlers, pos=None):
        self.theme = theme
        self.todos = todos
        self.h = handlers
        self.editable = True
        self._offset = 0
        self._drag_state = None

        self.win = tk.Toplevel(root)
        self.win.title("番茄钟·待办")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
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
            pos = (80, 80)
        self.win.geometry(f"{W}x{H}+{clamp_to_screen(pos[0], pos[1], W, H)[0]}"
                          f"+{clamp_to_screen(pos[0], pos[1], W, H)[1]}")

        self._build()
        self.refresh()
        self.set_list(todos, editable=True, label="今天",
                      nav=NavState(visible=False))

    # ---------- 构建 ----------
    def _build(self):
        cv, th = self.cv, self.theme
        round_rect(cv, *CARD, fill=th.card, outline=th.card_edge, width=1,
                   tags=self.drag_tag)
        self._bind_drag(self.drag_tag)

        # 标题（今日/档案二态，set_list 切换文案）
        cv.create_text(34, 26, text="●", font=("Segoe UI", 13),
                       fill=th.pink_deep, anchor="w")
        self._title_id = cv.create_text(50, 26, text="今日待办",
                                        font=HEADER_FONT, fill=th.ink,
                                        anchor="w")
        self._sub_id = cv.create_text(50, 44, text="DAILY TODO",
                                      font=SUB_FONT, fill=th.faint, anchor="w")
        self._count_id = cv.create_text(W - 40, 32, text="", font=TEXT_FONT,
                                        fill=th.muted, anchor="e")
        self._icon(cv, "✕", W - 38, 26, th.muted, self.h.on_close)

        # 日期导航簇（副标题行右侧）
        self._nav_prev_id = self._glyph(cv, "◀", NAV_PREV_X, NAV_Y)
        cv.tag_bind(self._nav_prev_id, "<Button-1>",
                    lambda e: self.h.on_prev_day())
        self._nav_date_id = cv.create_text(NAV_DATE_X, NAV_Y, text="今天",
                                           font=DATE_FONT, fill=th.ink)
        self._nav_next_id = self._glyph(cv, "▶", NAV_NEXT_X, NAV_Y)
        cv.tag_bind(self._nav_next_id, "<Button-1>",
                    lambda e: self.h.on_next_day())

        # 输入区（Entry/Button 是 tk 部件，place 覆盖在画布上；档案态隐藏）
        self.entry = tk.Entry(self.win, font=TEXT_FONT, bg=th.card, fg=th.ink,
                              insertbackground=th.ink, relief="flat",
                              highlightthickness=1,
                              highlightbackground=th.pill_active,
                              highlightcolor=th.lavender_deep)
        self.entry.place(in_=self.cv, x=26, y=ENTRY_Y, width=196,
                         height=ENTRY_H)
        add_btn = tk.Button(self.win, text="添加", font=TEXT_FONT,
                            bg=th.lavender, fg=th.btn_ink, relief="flat",
                            activebackground=th.pill_active,
                            command=self._add_from_entry)
        add_btn.place(in_=self.cv, x=ADD_BTN[0], y=ADD_BTN[1],
                      width=ADD_BTN[2], height=ADD_BTN[3])
        self._add_btn = add_btn
        self.entry.bind("<Return>", lambda e: self._add_from_entry())

        # 详情输入行：任务可附带一句话说明（可选）
        self._note_label_id = cv.create_text(NOTE_LABEL[0], NOTE_LABEL[1],
                                             text="详情", font=WEEKHINT_FONT,
                                             fill=th.faint, anchor="w")
        self.note_entry = tk.Entry(self.win, font=TEXT_FONT, bg=th.card,
                                   fg=th.muted, insertbackground=th.ink,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=th.pill_active,
                                   highlightcolor=th.lavender_deep)
        self.note_entry.place(in_=self.cv, x=NOTE_ENTRY[0], y=NOTE_ENTRY[1],
                              width=NOTE_ENTRY[2], height=NOTE_ENTRY[3])
        self.note_entry.bind("<Return>", lambda e: self._add_from_entry())

        # 底部提示（set_list 切换文案）
        self._hint_id = cv.create_text(28, H - 30, text=HINT_TODAY,
                                       font=WEEKHINT_FONT, fill=th.faint,
                                       anchor="w")

        # 列表滚轮
        self.win.bind("<MouseWheel>", self._on_wheel)
        self.cv.bind("<MouseWheel>", self._on_wheel)

    # ---------- 切换形态（今日 / 历史档案）----------
    def set_list(self, todos: TodoList, *, editable: bool, label: str,
                 nav: NavState):
        """换一套要显示的列表（今日=活引用可编辑；档案=只读快照）。"""
        self.todos = todos
        self.editable = bool(editable)
        self._offset = 0
        cv, th = self.cv, self.theme

        cv.itemconfig(self._title_id,
                      text="今日待办" if editable else "待办档案")
        cv.itemconfig(self._sub_id,
                      text="DAILY TODO" if editable else "TODO ARCHIVE")
        cv.itemconfig(self._nav_date_id,
                      text=label if isinstance(label, str) else "")
        cv.itemconfig(self._hint_id,
                      text=HINT_TODAY if editable else HINT_ARCHIVE)

        # 导航簇：无历史整体隐藏；不可用方向置灰
        state = "normal" if nav and nav.visible else "hidden"
        cv.itemconfigure(self._nav_prev_id, state=state)
        cv.itemconfigure(self._nav_date_id, state=state)
        cv.itemconfigure(self._nav_next_id, state=state)
        cv.itemconfig(self._nav_prev_id,
                      fill=th.lavender_ink if nav and nav.has_prev
                      else th.faint)
        cv.itemconfig(self._nav_next_id,
                      fill=th.lavender_ink if nav and nav.has_next
                      else th.faint)

        # 输入行只在今日形态出现
        if self.editable:
            self.entry.place(in_=self.cv, x=26, y=ENTRY_Y, width=196,
                             height=ENTRY_H)
            self._add_btn.place(in_=self.cv, x=ADD_BTN[0], y=ADD_BTN[1],
                                width=ADD_BTN[2], height=ADD_BTN[3])
            self.note_entry.place(in_=self.cv, x=NOTE_ENTRY[0],
                                  y=NOTE_ENTRY[1], width=NOTE_ENTRY[2],
                                  height=NOTE_ENTRY[3])
            cv.itemconfigure(self._note_label_id, state="normal")
        else:
            self.entry.place_forget()
            self._add_btn.place_forget()
            self.note_entry.place_forget()
            cv.itemconfigure(self._note_label_id, state="hidden")

        self.refresh()

    def _add_from_entry(self):
        if not self.editable:
            return
        text = self.entry.get()
        note = self.note_entry.get()
        self.entry.delete(0, END)
        self.note_entry.delete(0, END)
        if text.strip():
            self.h.on_add(text, note)

    # ---------- 渲染 ----------
    def refresh(self):
        cv, th = self.cv, self.theme
        cv.delete("row")
        self.cv.itemconfig(self._count_id,
                           text=f"{self.todos.done_count}/{len(self.todos.items)}")

        items = self.todos.items
        if not items:
            empty = "暂无待办，先添加一条吧" if self.editable else "这天没有待办记录"
            cv.create_text(W // 2, (LIST_TOP + LIST_BOT) // 2,
                           text=empty, font=TEXT_FONT, fill=th.faint,
                           tags="row")
            return

        # 只画可视窗内的完整行（简单可靠的行级裁剪）
        visible_h = LIST_BOT - LIST_TOP
        i_start = self._offset // ROW
        i_end = min(len(items),
                    (self._offset + visible_h + ROW - 1) // ROW)
        for i in range(i_start, i_end):
            self._draw_row(items[i], LIST_TOP + i * ROW - self._offset)

    def _draw_row(self, todo, y):
        cv, th = self.cv, self.theme
        yc = y + ROW // 2
        active = (todo.id == self.todos.active_id)

        # 行背景既是状态底色，也是"点行选中"的命中区（仅今日形态可点）
        if active:
            bg = round_rect(cv, 20, y + 2, W - 20, y + ROW - 2, 10,
                            fill=th.pill_active, outline=th.lavender_deep,
                            width=1, tags="row")
        else:
            bg = round_rect(cv, 20, y + 2, W - 20, y + ROW - 2, 10,
                            fill=th.card, width=0, tags="row")
        if self.editable:
            cv.tag_bind(bg, "<Button-1>",
                        lambda e, i=todo.id: self.h.on_select(i))
        # 双击任意处查看该条详情（今日/档案皆可）
        self._bind_detail(bg, todo)

        # 状态标记（✔ 为粗笔画字形，细的 ✓ 抗锯齿后视觉上太淡）
        if todo.done:
            state, color = "✔", th.mint_ink
        elif active:
            state, color = "●", th.pink_ink
        else:
            state, color = "○", th.lavender_deep
        cv.create_text(36, yc, text=state,
                       font=ICON_FONT, fill=color, tags="row")

        # 文本 + 完成删除线
        text = fit_text(cv, todo.text, TEXT_FONT, W - 150 - X_TEXT)
        text_id = cv.create_text(X_TEXT, yc, text=text, font=TEXT_FONT,
                                 fill=(th.faint if todo.done else th.ink),
                                 anchor="w", tags="row")
        self._bind_detail(text_id, todo)
        if todo.done:
            tw = text_width(cv, text, TEXT_FONT)
            cv.create_line(X_TEXT - 2, yc, X_TEXT + tw + 2, yc,
                           fill=th.faint, width=1, tags="row")

        # 番茄小图标 + 次数
        if todo.poms > 0:
            self._mini_tomato(W - 128, yc)
            cv.create_text(W - 119, yc, text=str(todo.poms),
                           font=TEXT_FONT, fill=th.muted, anchor="w",
                           tags="row")

        # 行按钮仅今日形态（已完成行提供 ↺ 撤销完成）
        if not self.editable:
            return
        if not todo.done:
            self._row_btn(cv, "▶", W - BTN_X["start"], yc, th.lavender_ink,
                          lambda e, i=todo.id: self.h.on_start(i))
            self._row_btn(cv, "✔", W - BTN_X["done"], yc, th.mint_ink,
                          lambda e, i=todo.id: self.h.on_toggle_done(i))
        else:
            self._row_btn(cv, "↺", W - BTN_X["done"], yc, th.mint_ink,
                          lambda e, i=todo.id: self.h.on_toggle_done(i))
        self._row_btn(cv, "✕", W - BTN_X["del"], yc, th.muted,
                      lambda e, i=todo.id: self.h.on_remove(i))

    def _mini_tomato(self, x, y):
        th = self.theme
        self.cv.create_oval(x - 6, y - 6, x + 6, y + 6,
                            fill=th.pink, outline=th.pink_deep,
                            width=1, tags="row")

    def _row_btn(self, cv, glyph, x, y, color, cb):
        item = cv.create_text(x, y, text=glyph, font=ICON_FONT,
                              fill=color, tags="row")
        cv.tag_bind(item, "<Button-1>", cb)

    def _bind_detail(self, item, todo):
        """双击条目（背景或文本）弹出详情。"""
        self.cv.tag_bind(item, "<Double-Button-1>",
                         lambda e, t=todo: self._open_detail(t))

    def _open_detail(self, todo):
        x = self.win.winfo_x() + self.W - 60
        y = self.win.winfo_y() + 10
        TodoDetail(self.win, self.theme, todo, pos=(x, y))

    def _glyph(self, cv, glyph, x, y):
        return cv.create_text(x, y, text=glyph, font=NAV_FONT,
                              fill=self.theme.lavender_ink)

    def _icon(self, cv, glyph, x, y, color, cb):
        item = cv.create_text(x, y, text=glyph, font=ICON_FONT,
                              fill=color)
        cv.tag_bind(item, "<Button-1>", lambda e: cb())

    # ---------- 滚动 ----------
    def _on_wheel(self, event):
        n_rows = len(self.todos.items)
        max_off = max(0, n_rows * ROW - (LIST_BOT - LIST_TOP))
        step = ROW if event.delta < 0 else -ROW
        self._offset = max(0, min(max_off, self._offset + step))
        self.refresh()

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


class TodoDetail:
    """单条待办详情弹窗（只读）——展示任务文字与详情说明。

    独立 Toplevel，可拖动、置顶；双击待办条目时由 TodoView 打开。
    """
    drag_tag = "todo_detail_card"
    W, H = 320, 210

    def __init__(self, root, theme: Theme, todo, pos=None):
        self.theme = theme
        self._drag_state = None
        self.win = tk.Toplevel(root)
        self.win.title("番茄钟·待办详情")
        self.win.overrideredirect(True)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        bg = theme.card
        try:
            self.win.attributes("-transparentcolor", theme.transparent_key)
            bg = theme.transparent_key
        except tk.TclError:
            pass
        self.cv = tk.Canvas(self.win, width=self.W, height=self.H, bg=bg,
                            highlightthickness=0, bd=0)
        self.cv.pack()
        if pos is None:
            pos = (0, 0)
        px, py = clamp_to_screen(pos[0], pos[1], self.W, self.H)
        self.win.geometry(f"{self.W}x{self.H}+{px}+{py}")

        th = theme
        round_rect(self.cv, 8, 8, self.W - 8, self.H - 8, 18, fill=th.card,
                   outline=th.card_edge, width=1, tags=self.drag_tag)
        self._bind_drag(self.drag_tag)

        # 标题：任务名 + 关闭
        self.cv.create_text(28, 26, text="●", font=("Segoe UI", 12),
                            fill=th.pink_deep, anchor="w")
        self.cv.create_text(
            46, 26, text=fit_text(self.cv, todo.text, HEADER_FONT,
                                  self.W - 110),
            font=HEADER_FONT, fill=th.ink, anchor="w")
        self._icon("✕", self.W - 26, 26, th.muted, self.close)

        # 详情区标签
        self.cv.create_text(28, 52, text="详情", font=SUB_FONT,
                            fill=th.faint, anchor="w")

        # 只读正文（自动换行 + 滚动）
        self.txt = tk.Text(self.win, font=TEXT_FONT, bg=th.card, fg=th.ink,
                           wrap="word", relief="flat", highlightthickness=0,
                           bd=0, padx=0, pady=0)
        sb = tk.Scrollbar(self.win, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.place(x=22, y=56, width=self.W - 52, height=self.H - 78)
        sb.place(x=self.W - 24, y=56, height=self.H - 78)
        self.txt.insert(END, todo.note if todo.note else "（无详情说明）")
        self.txt.config(state="disabled")

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
        x, y = clamp_to_screen(event.x_root - dx, event.y_root - dy,
                               self.W, self.H)
        self.win.geometry(f"+{x}+{y}")

    def _icon(self, glyph, x, y, color, cb):
        item = self.cv.create_text(x, y, text=glyph, font=ICON_FONT,
                                   fill=color)
        self.cv.tag_bind(item, "<Button-1>", lambda e: cb())

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
