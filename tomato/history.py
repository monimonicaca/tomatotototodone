# -*- coding: utf-8 -*-
"""番茄历史：按天计数的记录 + 日/周/月聚合查询。

只存"某天完成了几个"，周月都是查询时聚合——单条记录永不重复存储。
输入一律走容错解析：坏日期/坏数字直接丢弃，不抛异常。
"""
from __future__ import annotations

import datetime

from .constants import MAX_HISTORY_DAYS


def _parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


class HistoryLog:
    def __init__(self, data=None):
        self._data: dict[str, int] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                d = _parse_date(k)
                if d is None:
                    continue
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    continue
                if n > 0:                      # 0/负数不存，天然省空间
                    self._data[d.isoformat()] = n

    # ---------- 单日 ----------
    def count(self, date: str) -> int:
        return self._data.get(str(date), 0)

    def set_count(self, date: str, n: int):
        try:
            n = int(n)
        except (TypeError, ValueError):
            return
        if n <= 0:
            self._data.pop(str(date), None)
        else:
            self._data[str(date)] = n

    def total(self) -> int:
        return sum(self._data.values())

    # ---------- 聚合 ----------
    def day_total(self, date: str) -> int:
        return self.count(date)

    def week_total(self, date: str) -> int:
        """ISO 周（周一起始）从周一到指定日的合计。"""
        d = _parse_date(date)
        if d is None:
            return 0
        monday = d - datetime.timedelta(days=d.weekday())
        return sum(self.count((monday + datetime.timedelta(days=i)).isoformat())
                   for i in range((d - monday).days + 1))

    def month_total(self, date: str) -> int:
        """指定日所在自然月，从 1 号到指定日的合计。"""
        d = _parse_date(date)
        if d is None:
            return 0
        day = d.replace(day=1)
        total = 0
        while day <= d:
            total += self.count(day.isoformat())
            day += datetime.timedelta(days=1)
        return total

    def last_days(self, date: str, n=7) -> list:
        """截至 date 的最近 n 天，按时间正序 [(date, count), ...]。"""
        d = _parse_date(date) or datetime.date.today()
        try:
            n = max(1, int(n))
        except (TypeError, ValueError):
            n = 7
        out = []
        for i in range(n - 1, -1, -1):
            day = d - datetime.timedelta(days=i)
            out.append((day.isoformat(), self.count(day.isoformat())))
        return out

    # ---------- 维护 ----------
    def prune(self, keep_days=MAX_HISTORY_DAYS, today=None):
        """只保留最近 keep_days 天。"""
        t = _parse_date(today) or datetime.date.today()
        try:
            keep_days = max(1, int(keep_days))
        except (TypeError, ValueError):
            return
        for k in list(self._data):
            d = _parse_date(k)
            if d is None or (t - d).days >= keep_days:
                self._data.pop(k, None)

    def as_dict(self) -> dict:
        return dict(self._data)
