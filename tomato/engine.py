# -*- coding: utf-8 -*-
"""番茄钟状态机：纯逻辑，零 UI 依赖。

职责边界：
- 输入：阶段切换 / 起停 / 跳过 / 完成阶段 / 修改时长；
- 输出：当前阶段、剩余秒数、今日统计；
- 不做：计时调度（controller 的单调时钟负责）、渲染（view 负责）、落盘（storage 负责）。

时序说明：引擎只保存"剩余秒数"，不自己走表；控制器每拍把按单调时钟
算出的剩余秒数写回（set_remaining），因此事件循环卡顿不会累积漂移。
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from .constants import DEFAULT_DURATIONS, POMODOROS_BEFORE_LONG, clamp_minutes

MODES = ("focus", "short", "long")
MODE_LABELS = {"focus": "专注", "short": "短休息", "long": "长休息"}


@dataclass
class Durations:
    """三阶段时长（分钟）。构造即钳制，永远是合法值。"""

    focus: int = DEFAULT_DURATIONS["focus"]
    short: int = DEFAULT_DURATIONS["short"]
    long: int = DEFAULT_DURATIONS["long"]

    def __post_init__(self):
        for name in ("focus", "short", "long"):
            setattr(self, name,
                    clamp_minutes(getattr(self, name), DEFAULT_DURATIONS[name]))

    def seconds(self, mode: str) -> int:
        return getattr(self, mode) * 60

    def as_dict(self) -> dict:
        return {"focus": self.focus, "short": self.short, "long": self.long}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Durations":
        data = data if isinstance(data, dict) else {}
        d = cls()
        for name in ("focus", "short", "long"):
            if name in data:
                setattr(d, name, clamp_minutes(data[name], DEFAULT_DURATIONS[name]))
        return d


@dataclass
class DailyStats:
    """今日统计：完成番茄数、本轮进度。date 为 YYYY-MM-DD。"""

    date: str = ""
    count: int = 0      # 今日已完成番茄数
    in_set: int = 0     # 本轮已完成专注数（0 .. POMODOROS_BEFORE_LONG-1）

    @staticmethod
    def _nonneg(v) -> int:
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def from_dict(cls, data) -> "DailyStats":
        if not isinstance(data, dict):
            return cls()
        date = data.get("date")
        return cls(
            date=date if isinstance(date, str) else "",
            count=cls._nonneg(data.get("count")),
            in_set=cls._nonneg(data.get("in_set")),
        )

    def as_dict(self) -> dict:
        return {"date": self.date, "count": self.count, "in_set": self.in_set}


@dataclass(frozen=True)
class PhaseResult:
    """一次阶段结束的结果。previous 供提示音区分"专注结束/休息结束"。"""

    previous: str
    current: str
    counted: bool


class PomodoroEngine:
    """番茄周期状态机。"""

    def __init__(self, durations: Durations | None = None,
                 stats: DailyStats | None = None,
                 today: str | None = None):
        self.durations = durations or Durations()
        self.stats = stats if stats is not None else DailyStats()
        self.today = today or datetime.date.today().isoformat()
        self.mode = "focus"
        self.running = False
        self._rollover_if_new_day()
        self.total = self.durations.seconds(self.mode)
        self.remaining = self.total

    # ---------- 日结 ----------
    def _rollover_if_new_day(self):
        today = datetime.date.today().isoformat()
        self.today = today
        if self.stats.date != today:   # 以 stats 里记录的日期为准
            self.stats.date = today
            self.stats.count = 0
            self.stats.in_set = 0

    # ---------- 阶段 ----------
    def switch_mode(self, mode: str):
        """手动切换阶段；非法阶段直接抛错（fail-fast，不猜意图）。"""
        if mode not in MODES:
            raise ValueError(f"未知阶段: {mode!r}")
        self.mode = mode
        self.running = False
        self.total = self.durations.seconds(mode)
        self.remaining = self.total

    def reset_phase(self):
        """重置当前阶段（不起不停，只恢复满时长）。"""
        self.running = False
        self.total = self.durations.seconds(self.mode)
        self.remaining = self.total

    def start(self):
        self.running = True

    def pause(self):
        self.running = False

    def set_remaining(self, seconds: int):
        """控制器每拍写回按单调时钟校准的剩余秒数。"""
        self.remaining = max(0, int(seconds))

    def set_durations(self, durations: Durations):
        """更新时长；仅空闲时重建当前阶段计时，运行中的阶段不受打扰。"""
        self.durations = durations
        if not self.running:
            self.total = durations.seconds(self.mode)
            self.remaining = self.total

    # ---------- 周期推进 ----------
    def finish_phase(self, counted: bool = True) -> PhaseResult:
        """结束当前阶段并推进到下一阶段。

        counted=True：自然计时完成——专注会计入统计并推进轮次；
        counted=False：手动跳过——不计入统计，仅切换阶段。
        """
        prev = self.mode
        self.running = False
        if prev == "focus" and counted:
            self.stats.count += 1
            self.stats.in_set += 1
            if self.stats.in_set >= POMODOROS_BEFORE_LONG:
                self.stats.in_set = 0
                self.mode = "long"
            else:
                self.mode = "short"
        else:
            # 跳过的专注 -> 短休；任何休息结束 -> 专注
            self.mode = "short" if prev == "focus" else "focus"
        self._rollover_if_new_day()
        self.total = self.durations.seconds(self.mode)
        self.remaining = self.total
        return PhaseResult(previous=prev, current=self.mode, counted=counted)
