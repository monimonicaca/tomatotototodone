# -*- coding: utf-8 -*-
"""番茄钟悬浮小窗 · 应用入口。

结构（依赖只向下，不回头）：
    main -> controller -> ui(window/timer_view/todo_view/stats_view/sticker_wall)
                     +-> storage -> engine/history
                     +-> todo_store(SQLite) -> todo
    engine / history / todo：纯逻辑，零 UI 依赖
    sound / applock：独立小模块，按需被引用

数据持久化：
    config.json —— 时长/统计/历史/窗口位置等低频设置
    todos.db    —— 待办（SQLite，高频增删改查）

运行：python main.py（或资源管理器双击）。
双开后第二个实例会弹提示退出；启动失败会弹窗展示堆栈而非一闪而过。
"""
from __future__ import annotations

import datetime
import traceback

import tkinter as tk
from tkinter import messagebox

from tomato.applock import AppLock
from tomato.constants import CONFIG_FILE, LOCK_FILE, TODO_DB
from tomato.controller import PomodoroController
from tomato.engine import PomodoroEngine
from tomato.storage import ConfigStore
from tomato.theme import MACARON
from tomato.todo_store import TodoStore
from tomato.ui.sticker_wall import StickerWall
from tomato.ui.window import FloatingWindow


def build(config_file=CONFIG_FILE, todo_db=TODO_DB) -> PomodoroController:
    """装配全部组件并返回控制器。

    路径参数可注入：集成/视觉测试传临时路径即可，完全不碰真实数据。
    """
    store = ConfigStore(config_file)
    cfg = store.load()

    today = datetime.date.today().isoformat()
    # 今日完成数以历史账本为准（stats.count 只作引擎运行态）
    cfg.stats.count = cfg.history.count(today)

    # 待办从 SQLite 读（跨天自动接班归档）；
    # 库里还没有条目而旧版 config.json 里有 → 一次性迁移（旧数据按原日期入桶）
    todo_store = TodoStore(todo_db)
    todos = todo_store.load(today)
    if not todos.items and cfg.legacy_todos.items:
        legacy = cfg.legacy_todos
        if legacy.date and legacy.date < today and legacy.items:
            todo_store.save(legacy)    # 原日期封存整份快照（含已完成）
        todos = legacy
        todos.rollover(today)          # 未完成项顺延为今天的桶
        todo_store.save(todos)

    root = tk.Tk()
    root.title("番茄钟悬浮窗")
    window = FloatingWindow(root,
                            transparent_key=MACARON.transparent_key,
                            pos=cfg.pos,
                            topmost=cfg.topmost)
    engine = PomodoroEngine(cfg.durations, cfg.stats)
    sticker = StickerWall(root, MACARON, MACARON.transparent_key)
    return PomodoroController(window, engine, store, MACARON,
                              todos=todos,
                              history=cfg.history,
                              sticker=sticker,
                              stickers_on=cfg.stickers,
                              todo_store=todo_store)


def _alert(text: str, timeout_ms: int = 4000):
    """提示弹窗，超时自动关闭。

    优先用 Windows 原生 MessageBoxTimeoutW：原生模态消息泵里
    tkinter 的 after 定时器不会触发，超时必须由系统实现，
    否则第二个实例的“已在运行”提示会一直挂着等点击。
    系统调用不可用时退回 tkinter 版本（可能需手动点击）。
    """
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxTimeoutW(
            0, text, "番茄钟", 0, 0, int(timeout_ms))
        return
    except Exception:
        pass
    try:
        root = tk.Tk()
        root.withdraw()
        root.after(timeout_ms, root.destroy)
        messagebox.showinfo("番茄钟", text)
        root.destroy()
    except tk.TclError:
        pass


def main() -> None:
    lock = AppLock(LOCK_FILE)
    if not lock.acquire():
        _alert("番茄钟已经在运行了")
        return
    try:
        controller = build()
        controller.window.root.mainloop()
    finally:
        lock.release()
        # 保险：正常 UI 退出走 controller.exit_app() 的 os._exit；
        # 若 mainloop 以其他方式返回，也强制进程立即结束——避免依赖
        # Tcl 析构路径（该路径存在堆损坏 panic 导致进程挂死的已知问题）。
        import os
        os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 双击运行时没有控制台：把致命错误摆到用户面前
        try:
            _alert("启动失败：\n" + traceback.format_exc(limit=3),
                   timeout_ms=15000)
        except Exception:
            pass
        raise
