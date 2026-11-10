# -*- coding: utf-8 -*-
"""全局常量：尺寸、取值范围、配置键名、路径。

只放跨模块共享的"事实"，不放任何行为逻辑。
"""
from pathlib import Path

# ---- 窗口尺寸（主卡）----
WINDOW_W = 340
WINDOW_H = 430

# ---- 番茄周期 ----
POMODOROS_BEFORE_LONG = 4      # 完成几个专注后进入长休息

# ---- 时长取值范围（分钟）----
MIN_MINUTES = 1
MAX_MINUTES = 120
DEFAULT_DURATIONS = {"focus": 25, "short": 5, "long": 15}

# ---- 配置键名（config.json 字段）----
KEY_DURATIONS = "durations"
KEY_STATS = "stats"
KEY_TOPMOST = "topmost"
KEY_POS = "pos"
KEY_HISTORY = "history"
KEY_TODOS = "todos"
KEY_STICKERS = "stickers"

# ---- 待办 ----
TODO_DATE_KEY = "date"
TODO_ITEMS_KEY = "items"
TODO_ACTIVE_KEY = "active_id"
MAX_TODO_TEXT = 60             # 单条待办文字上限（字符）
MAX_TODO_NOTE = 200            # 单条待办详情上限（字符）

# ---- 历史 ----
MAX_HISTORY_DAYS = 370         # 历史保留天数（按天一条，防无限膨胀）

# ---- 路径：根目录 = tomato/ 的上一级 ----
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"
TODO_DB = BASE_DIR / "todos.db"      # 待办 SQLite 库
LOCK_FILE = BASE_DIR / "run.lock"


def clamp_minutes(value, fallback=None):
    """把任意输入钳制到合法分钟范围。

    类型错误回退 fallback（未提供时用专注默认值 25）。
    所有时长输入（配置文件、设置对话框）都经过这里，保证引擎不会收到脏数据。
    """
    if fallback is None:
        fallback = DEFAULT_DURATIONS["focus"]
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = fallback
    return max(MIN_MINUTES, min(MAX_MINUTES, n))


def to_nonneg_int(value, fallback=0) -> int:
    """容错取非负整数：坏数据回退，不抛异常。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, n)
