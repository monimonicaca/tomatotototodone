# -*- coding: utf-8 -*-
"""控制器：连接状态机、待办、历史、视图、窗口、持久化——唯一"认识所有人"的层。

计时策略：以 time.monotonic 的截止时刻为准。事件循环即使卡顿几秒，
恢复后显示也会立刻校准到真实剩余时间，不依赖"每秒减一"的累积。

联动规则（需求）：
- 每完成一个专注（自然走完 / 完成待办提前收束）→ 今日计数 +1、贴一颗桌面贴纸、
  历史按天落账、当前任务 poms +1；
- 从待办面板 ▶ 启动 = 选中该任务并把状态机切到专注后开表；
- 手动标记任务完成时，若该任务正在计时的专注尚未结束 → 立即结束（计一次番茄）。
"""
from __future__ import annotations

import time
import tkinter as tk

from .engine import PomodoroEngine
from .history import HistoryLog
from .sound import play_phase_end
from .storage import AppConfig, ConfigStore
from .theme import Theme
from .todo import TodoList
from .todo_store import TodoStore
from .ui.mini_view import MiniView, H as MINI_H, W as MINI_W
from .ui.settings_view import SettingsDialog
from .ui.stats_view import StatsView, make_snapshot
from .ui.timer_view import TimerHandlers, TimerSnapshot, TimerView
from .ui.todo_view import (PANEL_H, PANEL_W, NavState, TodoHandlers,
                           TodoView)
from .ui.window import FloatingWindow, clamp_to_screen

TICK_MS = 250   # 刷新节奏；精度由单调时钟保证，与节奏解耦


class PomodoroController:
    def __init__(self, window: FloatingWindow, engine: PomodoroEngine,
                 store: ConfigStore, theme: Theme, *,
                 todos: TodoList | None = None,
                 history: HistoryLog | None = None,
                 sticker=None,
                 stickers_on: bool = True,
                 todo_store: TodoStore | None = None):
        self.window = window
        self.engine = engine
        self.store = store
        self.theme = theme
        self.todos = todos if todos is not None else TodoList()
        self.history = history if history is not None else HistoryLog()
        self.todo_store = todo_store
        self.sticker = sticker
        self._stickers_on = stickers_on
        self._todo_panel = None
        self._todo_day: str | None = None   # 待办面板正在浏览的日子（None=今日）
        self._mini = None                   # 迷你折叠窗（None=完整主卡）
        self._deadline: float | None = None
        self._tick_job: str | None = None

        # 启动即对齐今天：待办滚动、贴纸恢复
        self.todos.rollover(self.engine.today)
        if self.sticker is not None:
            self.sticker.set_enabled(self._stickers_on)
            self.sticker.set_count(self.engine.stats.count)

        # 视图由控制器装配：回调全部指向自己的公开方法
        self.view = TimerView(
            window.canvas, theme,
            TimerHandlers(
                on_toggle=self.toggle,
                on_reset=self.reset,
                on_skip=self.skip,
                on_switch_mode=self.switch_mode,
                on_open_settings=self.open_settings,
                on_open_todos=self.open_todos,
                on_toggle_pin=self.toggle_pin,
                on_collapse=self.collapse,
                on_close=self.exit_app,
            ),
        )
        window.bind_drag(TimerView.drag_tag)
        window.on_context_menu(self._open_menu)
        self._render()

    # ==================== 计时器操作 ====================
    def toggle(self):
        if self.engine.running:
            if self._deadline is not None:
                self.engine.set_remaining(
                    max(0, round(self._deadline - time.monotonic())))
            self.engine.pause()
            self._cancel_tick()
            self._deadline = None
        else:
            self.engine.start()
            self._deadline = time.monotonic() + self.engine.remaining
            self._schedule_tick()
        self._render()

    def reset(self):
        self._cancel_tick()
        self._deadline = None
        self.engine.reset_phase()
        self._render()

    def skip(self):
        self.complete_phase(counted=False)

    def switch_mode(self, mode: str):
        self._cancel_tick()
        self._deadline = None
        self.engine.switch_mode(mode)
        self._render()

    def complete_phase(self, counted: bool = True):
        """结束当前阶段（自然完成或提前收束）→ 提示音 + 推进 + 落盘。"""
        self._cancel_tick()
        result = self.engine.finish_phase(counted=counted)
        self._deadline = None
        play_phase_end(was_focus=result.previous == "focus")
        if counted and result.previous == "focus":
            self._after_focus_counted()
        self._render()
        self._persist()

    def open_settings(self):
        SettingsDialog(self.window.root, self.engine.durations,
                       self._apply_durations, self.theme)

    def toggle_pin(self):
        """图钉：切换固定置顶（主卡 + 贴纸墙同动，并持久化）。"""
        self._set_topmost(not self.window.topmost)

    # ==================== 折叠 / 展开（迷你窗）====================
    def collapse(self):
        """把主卡折叠成迷你小窗：只显示标题 + 剩余时间。

        隐藏主窗，在它原本的位置弹出迷你 Toplevel（仍是主窗的子窗，
        主窗关闭时会一并销毁）。迷你窗随计时 _render 逐拍刷新。
        """
        if self._mini is not None:
            return
        x, y = self.window.root.winfo_x(), self.window.root.winfo_y()
        self._mini = MiniView(
            self.window.root, self.theme,
            on_expand=self.expand,
            on_close=self.exit_app,
            pos=clamp_to_screen(x, y, MINI_W, MINI_H),
            topmost=self.window.topmost,
        )
        try:
            self.window.root.withdraw()      # 隐藏主卡
        except tk.TclError:
            pass
        self._render()                      # 同步迷你窗内容

    def expand(self):
        """展开迷你小窗，恢复完整主卡。"""
        if self._mini is None:
            return
        mini, self._mini = self._mini, None
        mini.close()
        try:
            self.window.root.deiconify()
        except tk.TclError:
            pass
        self._render()

    def _close_mini(self):
        """清理迷你窗（退出/测试时调用，幂等）。"""
        if self._mini is None:
            return
        try:
            self._mini.close()
        except tk.TclError:
            pass
        self._mini = None

    def close_app(self):
        """测试用关闭：正常走 Tcl 析构（destroy + mainloop 自然返回）。"""
        self._cancel_tick()
        self._close_mini()
        if self._todo_panel is not None:
            self._todo_panel.close()
            self._todo_panel = None
        self._persist()
        if self.todo_store is not None:
            self.todo_store.close()
        self.window.close()

    def exit_app(self):
        """用户退出：落盘 -> 关库 -> os._exit(0) 硬终止。

        为什么不走 root.destroy()：本机 Tk 8.6 销毁这套窗口树
        （透明键 + 图钉自绘 + 多 Toplevel）会在 Tcl 析构中触发
        'alloc: invalid block' 堆损坏 panic，进程当场挂死不退出
        （任务管理器里 pythonw/pyw 永远残留）。所有状态在 os._exit
        之前已持久化；Windows 会自动回收窗口与文件锁。
        """
        import os
        self._cancel_tick()
        self._close_mini()
        if self._todo_panel is not None:
            try:
                self._todo_panel.close()
            except tk.TclError:
                pass
            self._todo_panel = None
        try:
            self._persist()
        finally:
            if self.todo_store is not None:
                self.todo_store.close()
            os._exit(0)

    # ==================== 待办 ====================
    def open_todos(self):
        """打开/前置待办面板（单实例，默认回到今日形态）。"""
        if self._todo_panel is not None:
            try:
                if self._todo_panel.win.winfo_exists():
                    self._todo_panel.win.lift()
                    return
            except tk.TclError:
                pass
            self._todo_panel = None

        mx, my = self.window.root.winfo_x(), self.window.root.winfo_y()
        x = mx - PANEL_W - 24
        if x < 10:
            x = mx + 340 + 24
        pos = clamp_to_screen(x, my + 30, PANEL_W, PANEL_H)

        self._todo_day = None          # None = 今日（活列表）
        self._todo_panel = TodoView(
            self.window.root, self.theme, self.todos,
            TodoHandlers(
                on_add=self.todo_add,
                on_select=self.todo_select,
                on_start=self.todo_start,
                on_toggle_done=self.todo_toggle_done,
                on_remove=self.todo_remove,
                on_edit=self.todo_edit,
                on_close=self._close_todo_panel,
                on_prev_day=lambda: self.todo_nav("prev"),
                on_next_day=lambda: self.todo_nav("next"),
            ),
            pos=pos,
        )
        self._apply_panel_day()

    # ---------- 历史导航（按天归档浏览）----------
    def todo_nav(self, direction: str):
        """待办面板日期导航：prev 更早一天，next 更近一天（直到今日）。

        历史日永远是只读快照；self.todos（今日活列表）不受浏览影响。
        """
        if self._todo_panel is None:
            return
        archived = self._archived_days()
        view = self._todo_day or self.engine.today
        if direction == "prev":
            pool = [d for d in archived if d < view]
            if not pool:
                return                      # 已是最早：原地不动
            self._todo_day = max(pool)
        else:
            if self._todo_day is None:
                return                      # 已在今日，无处更近
            pool = [d for d in archived if d > view]
            self._todo_day = min(pool) if pool else None   # None = 回到今日
        self._apply_panel_day()

    def _archived_days(self) -> list:
        """早于今日且有内容的桶，降序（历史导航的目的地）。"""
        if self.todo_store is None:
            return []
        today = self.engine.today
        try:
            return [d for d in self.todo_store.days() if d < today]
        except Exception:
            return []

    def _apply_panel_day(self):
        """把当前浏览日对应的列表/形态装进面板。"""
        panel = self._todo_panel
        if panel is None:
            return
        try:
            if not panel.win.winfo_exists():
                return
        except tk.TclError:
            return

        archived = self._archived_days()
        view = self._todo_day or self.engine.today
        nav = NavState(
            visible=bool(archived) or self._todo_day is not None,
            has_prev=any(d < view for d in archived),
            has_next=self._todo_day is not None,
        )

        if self._todo_day is None:
            panel.set_list(self.todos, editable=True, label="今天", nav=nav)
        else:
            snapshot = (self.todo_store.load_day(self._todo_day)
                        if self.todo_store is not None
                        else TodoList(date=self._todo_day))
            panel.set_list(snapshot, editable=False,
                           label=self._fmt_day(self._todo_day), nav=nav)

    @staticmethod
    def _fmt_day(day: str) -> str:
        return day[5:7] + "-" + day[8:10] if len(day) == 10 else day

    def _close_todo_panel(self):
        if self._todo_panel is not None:
            self._todo_panel.close()
            self._todo_panel = None

    def todo_add(self, text: str, note: str = "", progress: int = 0):
        if self.todos.add(text, note, progress) is not None:
            self._refresh_panel()
            self._render()
            self._persist()

    def todo_select(self, todo_id: str):
        """点选条目设为当前任务（左上角标题/胶囊随之切换）。"""
        todo = self.todos.get(todo_id)
        if todo is None or todo.done:
            return          # 已完成的条目不再作为当前任务
        self.todos.active_id = todo_id
        self._refresh_panel()
        self._render()
        self._persist()

    def todo_start(self, todo_id: str):
        """选中该任务 → 切到专注 → 开表（已开着就只换任务）。"""
        todo = self.todos.get(todo_id)
        if todo is None or todo.done:
            return          # 已完成的条目不能开番茄
        self.todos.active_id = todo_id
        if self.engine.mode != "focus":
            self._cancel_tick()
            self._deadline = None
            self.engine.switch_mode("focus")
        if not self.engine.running:
            self.engine.start()
            self._deadline = time.monotonic() + self.engine.remaining
            self._schedule_tick()
        self._refresh_panel()
        self._render()
        self._persist()

    def todo_toggle_done(self, todo_id: str):
        """标记/撤销完成。标记完成且该任务正计时的专注未结束 → 自动结束计一次。

        完成度联动：标记完成 → 100%；撤销完成 → 0%（未完成即无进度）。
        """
        todo = self.todos.get(todo_id)
        if todo is None:
            return
        new_done = not todo.done
        self.todos.set_done(todo_id, new_done)
        self.todos.set_progress(todo_id, 100 if new_done else 0)

        if new_done and self.todos.active_id == todo_id:
            should_end = (self.engine.mode == "focus"
                          and (self.engine.running
                               or self.engine.remaining < self.engine.total))
            if should_end:
                self.complete_phase(counted=True)
            self.todos.active_id = None     # 任务完结，解除绑定

        self._refresh_panel()
        self._render()
        self._persist()

    def todo_remove(self, todo_id: str):
        self.todos.remove(todo_id)
        self._refresh_panel()
        self._render()
        self._persist()

    def todo_edit(self, todo_id: str, text: str, note: str = "",
                  progress=None):
        """编辑条目（标题 + 详情 + 完成度）；标题为空则忽略。刷新面板/主卡并落盘。"""
        if self.todos.edit(todo_id, text, note, progress) is not None:
            self._refresh_panel()
            self._render()
            self._persist()

    # ==================== 统计 ====================
    def open_stats(self):
        StatsView(self.window.root, self.theme,
                  make_snapshot(self.history, self.engine.today))

    # ==================== 完成专注的后置动作 ====================
    def _after_focus_counted(self):
        # 跨天：滚动待办（清已完成）、贴纸自动归零换新的一天
        self.todos.rollover(self.engine.today)
        self.history.set_count(self.engine.today, self.engine.stats.count)
        if self.todos.active_id:
            self.todos.bump_poms(self.todos.active_id)
        if self.sticker is not None:
            self.sticker.set_count(self.engine.stats.count)
        self._refresh_panel()

    # ==================== 计时循环 ====================
    def _schedule_tick(self):
        self._cancel_tick()
        self._tick_job = self.window.root.after(TICK_MS, self._on_tick)

    def _cancel_tick(self):
        if self._tick_job is not None:
            try:
                self.window.root.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None

    def _on_tick(self):
        self._tick_job = None
        if not self.engine.running or self._deadline is None:
            return
        remaining = round(self._deadline - time.monotonic())
        if remaining <= 0:
            self.complete_phase(counted=True)
            return
        self.engine.set_remaining(remaining)
        self._render()
        self._schedule_tick()

    # ==================== 右键菜单 ====================
    def _open_menu(self, event):
        menu = tk.Menu(self.window.root, tearoff=0)
        menu.add_command(label="待办清单", command=self.open_todos)
        menu.add_command(label="统计", command=self.open_stats)
        menu.add_separator()
        top_var = tk.BooleanVar(value=self.window.topmost)
        menu.add_checkbutton(label="置顶", variable=top_var,
                             command=lambda: self._set_topmost(top_var.get()))
        stick_var = tk.BooleanVar(value=self._stickers_on)
        menu.add_checkbutton(label="贴纸墙", variable=stick_var,
                             command=lambda: self._set_stickers(
                                 stick_var.get()))
        menu.add_command(label="时长设置…", command=self.open_settings)
        menu.add_separator()
        menu.add_command(label="关闭", command=self.exit_app)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _set_topmost(self, enabled: bool):
        self.window.set_topmost(enabled)
        if self.sticker is not None:
            self.sticker.set_topmost(enabled)
        self._persist()
        self._render()          # 同步图钉图标状态

    def _set_stickers(self, enabled: bool):
        self._stickers_on = bool(enabled)
        if self.sticker is not None:
            self.sticker.set_enabled(self._stickers_on)
        self._persist()

    # ==================== 内部 ====================
    def _apply_durations(self, durations):
        self.engine.set_durations(durations)
        self._render()
        self._persist()

    def _refresh_panel(self):
        if self._todo_panel is None:
            return
        try:
            if self._todo_panel.win.winfo_exists():
                self._todo_panel.refresh()
            else:
                self._todo_panel = None
        except tk.TclError:
            self._todo_panel = None

    def _active_task_title(self) -> str:
        if not self.todos.active_id:
            return ""
        todo = self.todos.get(self.todos.active_id)
        return todo.text if todo and not todo.done else ""

    def _render(self):
        snap = TimerSnapshot(
            mode=self.engine.mode,
            remaining=self.engine.remaining,
            total=self.engine.total,
            running=self.engine.running,
            today_count=self.engine.stats.count,
            in_set=self.engine.stats.in_set,
            task_title=self._active_task_title(),
            pinned=self.window.topmost,
        )
        self.view.render(snap)
        if self._mini is not None:
            self._mini.render(snap)

    def _persist(self):
        """待办走 todos.db（SQLite），其余配置走 config.json。"""
        self.history.prune()
        if self.todo_store is not None:
            self.todo_store.save(self.todos)
        self.store.save(AppConfig(
            durations=self.engine.durations,
            stats=self.engine.stats,
            history=self.history,
            topmost=self.window.topmost,
            pos=self.window.position,
            stickers=self._stickers_on,
        ))
