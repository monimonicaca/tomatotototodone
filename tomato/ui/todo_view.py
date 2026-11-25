# -*- coding: utf-8 -*-
"""今日待办面板：添加 / 选中 / 开始番茄 / 完成 / 删除 / 编辑完成度 + 按天归档浏览。

视图不持有业务状态：所有动作通过 TodoHandlers 回调给 controller，
列表数据直接读传入的 TodoList，refresh() 随取随画。

面板放大到 420x560：每条待办双行布局（上行文字 + 行内按钮，
下行完成度进度条 + 百分比 + 番茄数），全部功能一屏可见。

两种形态（set_list 切换）：
- 今日（editable=True）：完整交互；
- 历史档案（editable=False）：只读快照——无输入行、无行按钮、不可选中，
  底部提示换为"历史归档·只读"。完成度仅展示不可改。
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import END

from ..constants import clean_progress
from ..theme import Theme
from ..todo import TodoList
from .canvas_helpers import fit_text, round_rect, text_width
from .window import clamp_to_screen

W, H = 420, 560
PANEL_W, PANEL_H = W, H                  # 供 controller 定位引用（防硬编码漂移）
CARD = (12, 8, W - 12, H - 8, 24)
LIST_TOP, LIST_BOT = 62, H - 70          # 列表区可视范围
ROW = 44                                 # 单条目高（双行：文字 + 完成度条）
X_TEXT = 52                              # 文本起点
BTN_X = {"detail": 114, "start": 88, "done": 62, "del": 36}   # 距右边缘
ADD_BTN = (W - 118, H - 56, 100, 40)     # 添加按钮（右下角）：x,y,宽,高
HINT_Y = H - 32                          # 底部提示基线
HINT_MAX_W = 268                         # 提示文字最大宽（让开右下角按钮）
WEEKHINT_FONT = ("Segoe UI", 8)
TEXT_FONT = ("Segoe UI", 9)
PCT_FONT = ("Segoe UI", 8, "bold")       # 完成度百分比 / 番茄次数
ICON_FONT = ("Segoe UI Symbol", 12, "bold")   # 行内图标：细笔画字形需大号加粗才抗锯齿后仍清晰
HEADER_FONT = ("Segoe UI", 13, "bold")
SUB_FONT = ("Segoe UI", 8, "bold")
NAV_FONT = ("Segoe UI Symbol", 10, "bold")
DATE_FONT = ("Segoe UI", 8, "bold")
# 导航簇（副标题行右侧）：◀ 日期 ▶
NAV_PREV_X, NAV_DATE_X, NAV_NEXT_X, NAV_Y = W - 116, W - 78, W - 36, 44
# 单条目完成度条（第二行）
BAR_X1, BAR_X2 = X_TEXT, W - 142         # 轨道范围
PCT_X = W - 130                          # 百分比文字起点
POMS_X = W - 70                          # 番茄图标中线

HINT_TODAY = "点条目选中 · ▶ 开始 · ✔ 完成 · ✕ 删除 · ⋯ 详情/编辑（可改完成度）· 右下添加"
HINT_ARCHIVE = "历史归档 · 只读（✔ 为已完成） · ⋯ 详情"


@dataclass
class TodoHandlers:
    """视图 -> controller 的回调集合。"""
    on_add: callable          # (text, note, progress)
    on_select: callable       # (todo_id)
    on_start: callable        # (todo_id)
    on_toggle_done: callable  # (todo_id)
    on_remove: callable       # (todo_id)
    on_edit: callable         # (todo_id, text, note, progress)
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
        self._children = []      # 面板打开的子弹窗（详情/新建），随面板关闭一并销毁

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

        # 底部提示（set_list 切换文案）
        self._hint_id = cv.create_text(28, HINT_Y, text=HINT_TODAY,
                                       font=WEEKHINT_FONT, fill=th.faint,
                                       anchor="w")

        # 右下角「添加」按钮：点开新建待办弹窗（档案态隐藏）
        self._add_btn = tk.Button(
            self.win, text="＋ 添加", font=("Segoe UI", 10, "bold"),
            bg=th.lavender, fg=th.btn_ink, relief="flat",
            activebackground=th.pill_active, command=self._open_add_dialog)
        self._add_btn.place(in_=self.cv, x=ADD_BTN[0], y=ADD_BTN[1],
                            width=ADD_BTN[2], height=ADD_BTN[3])

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
                      text=fit_text(cv,
                                    HINT_TODAY if editable else HINT_ARCHIVE,
                                    WEEKHINT_FONT, HINT_MAX_W))

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

        # 添加按钮只在今日形态出现
        if self.editable:
            self._add_btn.place(in_=self.cv, x=ADD_BTN[0], y=ADD_BTN[1],
                                width=ADD_BTN[2], height=ADD_BTN[3])
        else:
            self._add_btn.place_forget()

        self.refresh()

    def _open_add_dialog(self):
        if not self.editable:
            return
        x = self.win.winfo_x() + (W - TodoFormDialog.W) // 2
        y = self.win.winfo_y() + 40
        dlg = TodoFormDialog(self.win, self.theme, self.h.on_add, pos=(x, y))
        self._children.append(dlg)

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
        yc1 = y + 15                          # 第一行：文本 + 行内按钮
        yc2 = y + 33                          # 第二行：完成度条 + 番茄数
        active = (todo.id == self.todos.active_id)

        # 行背景既是状态底色，也是"点行选中"的命中区（仅今日形态可点）
        if active:
            bg = round_rect(cv, 20, y + 2, W - 20, y + ROW - 2, 12,
                            fill=th.pill_active, outline=th.lavender_deep,
                            width=1, tags="row")
        else:
            bg = round_rect(cv, 20, y + 2, W - 20, y + ROW - 2, 12,
                            fill=th.card, width=0, tags="row")
        if self.editable:
            cv.tag_bind(bg, "<Button-1>",
                        lambda e, i=todo.id: self.h.on_select(i))
        # 双击任意处查看该条详情（今日/档案皆可）
        self._bind_detail(bg, todo)

        # 状态标记（整条目垂直居中；✔ 为粗笔画字形，细的 ✓ 太淡）
        if todo.done:
            state, color = "✔", th.mint_ink
        elif active:
            state, color = "●", th.pink_ink
        else:
            state, color = "○", th.lavender_deep
        cv.create_text(36, y + ROW // 2, text=state,
                       font=ICON_FONT, fill=color, tags="row")

        # 文本 + 完成删除线（第一行）
        text = fit_text(cv, todo.text, TEXT_FONT, W - 126 - X_TEXT)
        text_id = cv.create_text(X_TEXT, yc1, text=text, font=TEXT_FONT,
                                 fill=(th.faint if todo.done else th.ink),
                                 anchor="w", tags="row")
        self._bind_detail(text_id, todo)
        if todo.done:
            tw = text_width(cv, text, TEXT_FONT)
            cv.create_line(X_TEXT - 2, yc1, X_TEXT + tw + 2, yc1,
                           fill=th.faint, width=1, tags="row")

        # 完成度（第二行）：轨道 + 填充 + 百分比（0% 只画空轨道）
        pct = min(100, max(0, int(todo.progress)))
        bx1, bx2 = BAR_X1, BAR_X2
        round_rect(cv, bx1, yc2 - 4, bx2, yc2 + 4, 4,
                   fill=th.track, width=0, tags="row")
        if todo.done:
            fill, ink = th.mint, th.mint_ink
        elif active:
            fill, ink = th.pink, th.pink_ink
        else:
            fill, ink = th.lavender, th.lavender_ink
        if pct > 0:
            fw = max(6, int((bx2 - bx1) * pct / 100))
            round_rect(cv, bx1, yc2 - 4, bx1 + fw, yc2 + 4,
                       max(1, min(4, fw // 2)),
                       fill=fill, width=0, tags="row")
            cv.create_text(PCT_X, yc2, text=f"{pct}%",
                           font=PCT_FONT, fill=ink, anchor="w", tags="row")

        # 番茄小图标 + 次数（第二行右端）
        if todo.poms > 0:
            self._mini_tomato(POMS_X, yc2)
            cv.create_text(POMS_X + 9, yc2, text=str(todo.poms),
                           font=PCT_FONT, fill=th.muted, anchor="w", tags="row")

        # 详情按钮（今日/档案都可点，点开该条详情）
        self._row_btn(cv, "⋯", W - BTN_X["detail"], yc1, th.lavender_ink,
                      lambda e, t=todo: self._open_detail(t))
        # 行按钮仅今日形态（已完成行提供 ↺ 撤销完成）
        if not self.editable:
            return
        if not todo.done:
            self._row_btn(cv, "▶", W - BTN_X["start"], yc1, th.lavender_ink,
                          lambda e, i=todo.id: self.h.on_start(i))
            self._row_btn(cv, "✔", W - BTN_X["done"], yc1, th.mint_ink,
                          lambda e, i=todo.id: self.h.on_toggle_done(i))
        else:
            self._row_btn(cv, "↺", W - BTN_X["done"], yc1, th.mint_ink,
                          lambda e, i=todo.id: self.h.on_toggle_done(i))
        self._row_btn(cv, "✕", W - BTN_X["del"], yc1, th.muted,
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
        x = self.win.winfo_x() + W - 60
        y = self.win.winfo_y() + 10
        dlg = TodoDetail(self.win, self.theme, todo, pos=(x, y),
                         on_edit=lambda: self._open_edit(todo, dlg))
        self._children.append(dlg)

    def _open_edit(self, todo, detail=None):
        """从详情里点「编辑」：关掉只读详情，用预填好的编辑表单替换。"""
        self._close_child(detail)
        x = self.win.winfo_x() + (W - TodoFormDialog.W) // 2
        y = self.win.winfo_y() + 40
        edit = TodoFormDialog(
            self.win, self.theme,
            lambda text, note, progress: self.h.on_edit(todo.id, text,
                                                        note, progress),
            pos=(x, y), initial_text=todo.text, initial_note=todo.note,
            initial_progress=todo.progress,
            title="编辑待办", submit_label="保存")
        self._children.append(edit)

    def _close_child(self, dlg):
        """从面板关闭一个子弹窗并从跟踪列表移除（幂等）。"""
        if dlg is None:
            return
        if dlg in self._children:
            self._children.remove(dlg)
        try:
            dlg.close()
        except Exception:
            pass

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
        """关闭面板并级联销毁其打开的子弹窗（详情/新建待办）。"""
        for dlg in self._children:
            try:
                dlg.close()
            except Exception:
                pass
        self._children = []
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class TodoDetail:
    """单条待办详情弹窗（只读）——展示任务文字、完成度与详情说明。

    独立 Toplevel，可拖动、置顶；双击待办条目时由 TodoView 打开。
    """
    drag_tag = "todo_detail_card"
    W, H = 320, 240

    def __init__(self, root, theme: Theme, todo, pos=None, on_edit=None):
        self.theme = theme
        self.on_edit = on_edit
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

        # 标题：任务名 + 编辑 + 关闭
        self.cv.create_text(28, 26, text="●", font=("Segoe UI", 12),
                            fill=th.pink_deep, anchor="w")
        self.cv.create_text(
            46, 26, text=fit_text(self.cv, todo.text, HEADER_FONT,
                                  self.W - 140),
            font=HEADER_FONT, fill=th.ink, anchor="w")
        if on_edit is not None:
            self._icon("✎", self.W - 52, 26, th.lavender_ink, on_edit)  # 编辑
        self._icon("✕", self.W - 26, 26, th.muted, self.close)

        # 完成度：标签 + 条 + 百分比
        pct = min(100, max(0, int(todo.progress)))
        if todo.done:
            bar_fill, bar_ink = th.mint, th.mint_ink
        else:
            bar_fill, bar_ink = th.lavender, th.lavender_ink
        self.cv.create_text(28, 58, text="完成度", font=SUB_FONT,
                            fill=th.faint, anchor="w")
        bx1, bx2 = 84, self.W - 110
        round_rect(self.cv, bx1, 51, bx2, 65, 7, fill=th.track, width=0)
        if pct > 0:
            fw = max(8, int((bx2 - bx1) * pct / 100))
            round_rect(self.cv, bx1, 51, bx1 + fw, 65,
                       max(1, min(7, fw // 2)), fill=bar_fill, width=0)
        self.cv.create_text(self.W - 78, 58, text=f"{pct}%",
                            font=("Segoe UI", 9, "bold"), fill=bar_ink)

        # 详情区标签
        self.cv.create_text(28, 86, text="详情", font=SUB_FONT,
                            fill=th.faint, anchor="w")

        # 只读正文（自动换行 + 滚动）
        body_y, body_h = 94, self.H - 110
        self.txt = tk.Text(self.win, font=TEXT_FONT, bg=th.card, fg=th.ink,
                           wrap="word", relief="flat", highlightthickness=0,
                           bd=0, padx=0, pady=0)
        sb = tk.Scrollbar(self.win, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.place(x=22, y=body_y, width=self.W - 52, height=body_h)
        sb.place(x=self.W - 24, y=body_y, height=body_h)
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


class TodoFormDialog:
    """待办表单弹窗（模态）：输入标题 / 完成度 / 详情，
    确认后回调 on_submit(title, note, progress)。

    新建与编辑共用：编辑时传 initial_* 预填、标题/按钮换文案。
    完成度用 Spinbox（0-100，步进 5），旁边带一条实时预览进度条。
    独立 Toplevel，可拖动、置顶；从面板右下「添加」或详情里的「编辑」打开。
    """
    drag_tag = "todo_form_card"
    W, H = 340, 350

    PREV_X1, PREV_X2 = 130, 300          # 完成度预览条轨道范围
    PREV_TOP, PREV_BOT = 163, 177        # 预览条上下边

    def __init__(self, root, theme: Theme, on_submit, pos=None, *,
                 initial_text: str = "", initial_note: str = "",
                 initial_progress: int = 0,
                 title: str = "新建待办", submit_label: str = "添加"):
        self.theme = theme
        self.on_submit = on_submit
        self._drag_state = None
        self.win = tk.Toplevel(root)
        self.win.title("番茄钟·待办")
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
        # 卡片底
        round_rect(self.cv, 8, 8, self.W - 8, self.H - 8, 18, fill=th.card,
                   outline=th.card_edge, width=1, tags=self.drag_tag)
        self._bind_drag(self.drag_tag)

        # 头部：粉色圆点 + 标题 + 关闭，下接一条细分隔线
        self.cv.create_text(30, 38, text="●", font=("Segoe UI", 13),
                            fill=th.pink_deep, anchor="w")
        self.cv.create_text(48, 38, text=title, font=HEADER_FONT,
                            fill=th.ink, anchor="w")
        self._icon("✕", self.W - 28, 38, th.muted, self.close)
        self.cv.create_line(24, 58, self.W - 24, 58, fill=th.card_edge,
                            width=1)

        # 标题字段（软填充输入框）
        self.cv.create_text(30, 88, text="标题", font=SUB_FONT,
                            fill=th.muted, anchor="w")
        self.title_entry = tk.Entry(
            self.win, font=TEXT_FONT, bg=th.pill, fg=th.ink,
            insertbackground=th.ink, relief="flat", highlightthickness=1,
            highlightbackground=th.card_edge, highlightcolor=th.lavender_deep)
        self.title_entry.place(x=30, y=98, width=self.W - 60, height=32)
        self.title_entry.insert(0, initial_text)
        self.title_entry.bind("<Return>", lambda e: self._submit())

        # 完成度字段：Spinbox（0-100 步进 5）+ 实时预览条
        self.cv.create_text(30, 150, text="完成度（%）", font=SUB_FONT,
                            fill=th.muted, anchor="w")
        self.progress_var = tk.StringVar(value=str(clean_progress(
            initial_progress)))
        spin = tk.Spinbox(
            self.win, from_=0, to=100, increment=5, width=5,
            textvariable=self.progress_var, font=TEXT_FONT, bg=th.pill,
            fg=th.ink, insertbackground=th.ink, relief="flat",
            buttonbackground=th.pill, highlightthickness=1,
            highlightbackground=th.card_edge,
            highlightcolor=th.lavender_deep,
            command=self._update_preview)
        spin.place(x=30, y=160, width=78, height=30)
        spin.bind("<KeyRelease>", lambda e: self._update_preview())
        round_rect(self.cv, self.PREV_X1, self.PREV_TOP,
                   self.PREV_X2, self.PREV_BOT, 7,
                   fill=th.track, width=0)
        self._preview_fill = None
        self._update_preview()

        # 详情字段（多行，柔和底）
        self.cv.create_text(30, 212, text="详情（可选）", font=SUB_FONT,
                            fill=th.muted, anchor="w")
        self.detail_text = tk.Text(
            self.win, font=TEXT_FONT, bg=th.pill, fg=th.ink,
            insertbackground=th.ink, wrap="word", relief="flat",
            highlightthickness=1, highlightbackground=th.card_edge,
            highlightcolor=th.lavender_deep)
        self.detail_text.place(x=30, y=222, width=self.W - 60, height=56)
        self.detail_text.insert("1.0", initial_note)

        # 底部按钮（与详情框留足间距，不重叠）
        cancel = tk.Button(self.win, text="取消", font=TEXT_FONT, bg=th.pill,
                           fg=th.muted, relief="flat",
                           activebackground=th.pill_active,
                           command=self.close)
        cancel.place(x=self.W - 154, y=self.H - 46, width=56, height=30)
        submit = tk.Button(self.win, text=submit_label,
                           font=("Segoe UI", 10, "bold"), bg=th.lavender,
                           fg=th.btn_ink, relief="flat",
                           activebackground=th.pill_active,
                           command=self._submit)
        submit.place(x=self.W - 90, y=self.H - 46, width=60, height=30)

        self._focus_title()
        try:
            self.win.grab_set()          # 模态：必须先关本窗才能操作面板
        except tk.TclError:
            pass

    def _focus_title(self):
        self.title_entry.focus_set()
        self.title_entry.icursor(END)

    def _update_preview(self):
        """重画完成度预览条的填充（值变了就删旧画新，永远叠在轨道上方）。"""
        cv, th = self.cv, self.theme
        if self._preview_fill is not None:
            cv.delete(self._preview_fill)
            self._preview_fill = None
        pct = clean_progress(self.progress_var.get())
        w = int((self.PREV_X2 - self.PREV_X1) * pct / 100)
        if w > 2:
            self._preview_fill = round_rect(
                cv, self.PREV_X1, self.PREV_TOP,
                self.PREV_X1 + w, self.PREV_BOT,
                max(1, min(7, w // 2)),
                fill=th.lavender, width=0)

    def _submit(self):
        title = self.title_entry.get().strip()
        note = self.detail_text.get("1.0", END).strip()
        progress = clean_progress(self.progress_var.get())
        if title:
            try:
                self.on_submit(title, note, progress)
            except Exception:
                pass
            self.close()

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
            self.win.grab_release()
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
