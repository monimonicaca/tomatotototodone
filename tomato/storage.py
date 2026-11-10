# -*- coding: utf-8 -*-
"""配置持久化：读写、字段级校验、损坏自愈。

鲁棒性策略：
- 读：文件不存在 -> 默认值；JSON 损坏 -> 转存 .corrupt 备份并回默认值；
      任何字段缺失/类型错/越界 -> 该字段单独回默认，其余字段保留
      （各字段由领域对象的 from_dict 负责容错，这里只做分发）；
- 写：先写 .tmp 再原子替换（os.replace），进程中途被杀也不会留下半截配置。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .constants import (KEY_DURATIONS, KEY_HISTORY, KEY_POS, KEY_STATS,
                        KEY_STICKERS, KEY_TODOS, KEY_TOPMOST)
from .engine import DailyStats, Durations
from .history import HistoryLog
from .todo import TodoList


@dataclass
class AppConfig:
    """一份可持久化的完整应用配置。"""

    durations: Durations
    stats: DailyStats
    history: HistoryLog = field(default_factory=HistoryLog)
    legacy_todos: TodoList = field(default_factory=TodoList)
    topmost: bool = True
    pos: tuple | None = None      # (x, y)，None 表示用默认位置
    stickers: bool = True         # 是否显示桌面贴纸墙

    def as_dict(self) -> dict:
        return {
            KEY_DURATIONS: self.durations.as_dict(),
            KEY_STATS: self.stats.as_dict(),
            KEY_HISTORY: self.history.as_dict(),
            # 待办已迁移至 todos.db（SQLite）：不再是本文件的职责，
            # legacy_todos 只作为旧版 JSON 的一次性迁移源，读取后不再写回。
            KEY_TOPMOST: bool(self.topmost),
            KEY_POS: list(self.pos) if self.pos else None,
            KEY_STICKERS: bool(self.stickers),
        }


class ConfigStore:
    """config.json 的唯一读写入口。"""

    def __init__(self, path: Path):
        self.path = Path(path)

    # ---------- 读 ----------
    def load(self) -> AppConfig:
        data = self._read_json()
        if not isinstance(data, dict):
            return AppConfig(durations=Durations(), stats=DailyStats())
        return AppConfig(
            durations=Durations.from_dict(data.get(KEY_DURATIONS)),
            stats=DailyStats.from_dict(data.get(KEY_STATS)),
            history=HistoryLog(data.get(KEY_HISTORY)),
            legacy_todos=TodoList.from_dict(data.get(KEY_TODOS)),
            topmost=self._bool(data.get(KEY_TOPMOST), default=True),
            pos=self._pos(data.get(KEY_POS)),
            stickers=self._bool(data.get(KEY_STICKERS), default=True),
        )

    def _read_json(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            self._backup_corrupt()
            return None

    def _backup_corrupt(self):
        """损坏文件改名保留现场，避免每次启动都撞同一份坏数据。"""
        try:
            if self.path.exists():
                self.path.replace(self.path.with_suffix(".corrupt.json"))
        except OSError:
            pass

    # ---------- 写 ----------
    def save(self, config: AppConfig) -> bool:
        try:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(config.as_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)   # 原子替换
            return True
        except OSError:
            return False

    # ---------- 字段级容错 ----------
    @staticmethod
    def _bool(v, default=True) -> bool:
        return v if isinstance(v, bool) else default

    @staticmethod
    def _pos(v):
        if isinstance(v, (list, tuple)) and len(v) == 2:
            try:
                return (int(v[0]), int(v[1]))
            except (TypeError, ValueError):
                return None
        return None
