# -*- coding: utf-8 -*-
"""历史记录单元测试。运行：py -3 tests/test_history.py"""
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tomato.history import HistoryLog

TODAY = datetime.date(2026, 11, 4).isoformat()      # 周三


def make():
    # 2026-11-01 周日（上周）、02 周一、03 周二、04 周三（今天）
    return HistoryLog({"2026-11-01": 2, "2026-11-02": 3,
                       "2026-11-03": 4, "2026-11-04": 5})


def test_counts_and_tolerance():
    h = HistoryLog({"2026-11-04": 1, "bogus": 7, "2026-11-03": "x",
                    "2026-11-02": -3, "2026-11-01": 0})
    assert h.count("2026-11-04") == 1
    assert h.count("2026-11-03") == 0        # 坏值被丢弃
    assert h.count("bogus") == 0
    assert h.total() == 1
    assert HistoryLog("not-dict").total() == 0


def test_set_count_removes_zero():
    h = HistoryLog({"2026-11-04": 5})
    h.set_count("2026-11-04", 7)
    assert h.count("2026-11-04") == 7
    h.set_count("2026-11-04", 0)
    assert h.total() == 0 and h.as_dict() == {}


def test_day_week_month_totals():
    h = make()
    assert h.day_total(TODAY) == 5
    assert h.week_total(TODAY) == 3 + 4 + 5        # 周一起：02/03/04
    assert h.month_total(TODAY) == 2 + 3 + 4 + 5   # 自然月含上周日 11-01
    assert h.week_total("bad-date") == 0
    assert HistoryLog().week_total(TODAY) == 0


def test_last_days():
    h = make()
    days = h.last_days(TODAY, 3)
    assert [d for d, _ in days] == ["2026-11-02", "2026-11-03", "2026-11-04"]
    assert [c for _, c in days] == [3, 4, 5]
    assert len(h.last_days(TODAY, 7)) == 7


def test_prune():
    h = HistoryLog({"2026-11-01": 1, "2026-11-03": 1,
                    "2026-11-04": 1})
    h.prune(keep_days=2, today="2026-11-04")       # 保留 11-03/11-04
    assert set(h.as_dict()) == {"2026-11-03", "2026-11-04"}


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("HISTORY_OK")
