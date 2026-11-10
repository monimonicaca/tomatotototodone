# -*- coding: utf-8 -*-
"""番茄钟状态机单元测试（纯逻辑，无窗口）。运行：py -3 tests/test_engine.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tomato.engine import DailyStats, Durations, PomodoroEngine


def test_initial():
    e = PomodoroEngine()
    assert e.mode == "focus" and e.remaining == 1500 and not e.running


def test_switch_mode():
    e = PomodoroEngine()
    e.switch_mode("short")
    assert e.remaining == 300 and not e.running
    e.switch_mode("long")
    assert e.remaining == 900
    try:
        e.switch_mode("nap")
        assert False, "非法阶段应当抛 ValueError"
    except ValueError:
        pass


def test_finish_focus_then_short():
    e = PomodoroEngine()
    r = e.finish_phase(counted=True)
    assert r.previous == "focus" and r.current == "short" and r.counted
    assert e.stats.count == 1 and e.stats.in_set == 1 and not e.running
    assert e.remaining == 300


def test_break_returns_to_focus():
    e = PomodoroEngine()
    e.finish_phase(True)
    assert e.finish_phase(True).current == "focus"


def test_long_break_after_four():
    e = PomodoroEngine()
    e.stats.in_set = 3
    r = e.finish_phase(counted=True)
    assert r.current == "long" and e.stats.in_set == 0
    assert e.stats.count == 1
    assert e.finish_phase(True).current == "focus"


def test_skip_not_counted():
    e = PomodoroEngine()
    r = e.finish_phase(counted=False)
    assert r.current == "short" and r.counted is False
    assert e.stats.count == 0 and e.stats.in_set == 0


def test_set_durations():
    e = PomodoroEngine()
    e.start()
    e.set_durations(Durations(focus=40))          # 运行中：不打扰当前阶段
    assert e.remaining == 1500 and e.total == 1500
    e.pause()
    e.set_durations(Durations(focus=40))          # 空闲：重建当前阶段
    assert e.total == 2400 == e.remaining


def test_durations_clamped():
    d = Durations(focus=999, short=0, long="abc")
    assert d.focus == 120 and d.short == 1 and d.long == 15


def test_daily_rollover():
    s = DailyStats(date="2000-01-01", count=9, in_set=2)
    e = PomodoroEngine(stats=s)
    assert e.stats.count == 0 and e.stats.in_set == 0
    assert e.stats.date == e.today


def test_reset_phase():
    e = PomodoroEngine()
    e.start()
    e.set_remaining(10)
    e.reset_phase()
    assert e.remaining == 1500 and not e.running


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("ENGINE_OK")
