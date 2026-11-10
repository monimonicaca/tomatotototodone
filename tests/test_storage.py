# -*- coding: utf-8 -*-
"""配置存储单元测试。运行：py -3 tests/test_storage.py"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tomato.engine import DailyStats, Durations
from tomato.history import HistoryLog
from tomato.todo import TodoList
from tomato.storage import AppConfig, ConfigStore


def test_missing_file_defaults(tmp: Path):
    cfg = ConfigStore(tmp / "absent.json").load()
    assert cfg.durations == Durations()
    assert cfg.stats == DailyStats(count=0, in_set=0)
    assert cfg.topmost is True and cfg.pos is None
    assert cfg.history.total() == 0
    assert cfg.legacy_todos.items == []     # 待办已迁往 SQLite，JSON 侧默认空
    assert cfg.stickers is True


def test_roundtrip(tmp: Path):
    store = ConfigStore(tmp / "config.json")
    cfg = AppConfig(
        durations=Durations(focus=40, short=10, long=20),
        stats=DailyStats(date="2026-11-04", count=5, in_set=2),
        history=HistoryLog({"2026-11-03": 3, "2026-11-04": 5}),
        topmost=False,
        pos=(123, 456),
        stickers=False,
    )
    assert store.save(cfg) is True
    cfg2 = store.load()
    assert cfg2.durations == cfg.durations
    assert cfg2.stats == cfg.stats
    assert cfg2.topmost is False
    assert tuple(cfg2.pos) == (123, 456)
    assert cfg2.stickers is False
    assert cfg2.history.count("2026-11-04") == 5
    assert cfg2.history.count("2026-11-03") == 3


def test_legacy_todos_read_once_not_written(tmp: Path):
    """旧版 JSON 里的待办可读（供迁移），但保存时不再写回。"""
    store = ConfigStore(tmp / "legacy.json")
    store.path.write_text(json.dumps({
        "durations": {"focus": 30},
        "todos": {"date": "2026-11-05", "items": [
            {"id": "a1", "text": "旧任务", "done": False, "poms": 1},
            {"id": "a2", "text": "旧任务二", "done": True, "poms": 0},
        ], "active_id": "a1"},
    }), encoding="utf-8")
    cfg = store.load()
    assert [t.text for t in cfg.legacy_todos.items] == ["旧任务", "旧任务二"]
    assert cfg.legacy_todos.items[1].done is True
    assert cfg.legacy_todos.active_id == "a1"

    store.save(cfg)
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert "todos" not in raw               # 不再随 config.json 落盘


def test_corrupt_file_self_heal(tmp: Path):
    store = ConfigStore(tmp / "bad.json")
    store.path.write_text("{oops", encoding="utf-8")
    cfg = store.load()
    assert cfg.durations.focus == 25          # 回默认
    assert (tmp / "bad.corrupt.json").exists()  # 现场被保留


def test_field_level_tolerances(tmp: Path):
    store = ConfigStore(tmp / "dirty.json")
    store.path.write_text(json.dumps({
        "durations": {"focus": -5, "short": "abc", "long": 30},
        "stats": {"date": 1, "count": "x", "in_set": -3},
        "history": {"2026-11-04": 2, "junk": "x"},
        "todos": "not-a-dict",
        "topmost": "yes",
        "pos": [1, 2, 3],
        "stickers": 0,
    }), encoding="utf-8")
    c = store.load()
    assert c.durations.focus == 1             # 越界钳制
    assert c.durations.short == 5             # 类型错 -> 该字段默认
    assert c.durations.long == 30
    assert c.stats.count == 0 and c.stats.in_set == 0 and c.stats.date == ""
    assert c.topmost is True                  # 非布尔 -> 默认
    assert c.pos is None                      # 非二元坐标 -> 默认
    assert c.history.count("2026-11-04") == 2  # 历史好条目保留
    assert c.history.count("junk") == 0        # 坏条目丢弃
    assert c.legacy_todos.items == []          # 非字典 -> 空（仅作迁移源）
    assert c.stickers is True                  # 0/1 之外的假值 -> 默认


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, fn in sorted(list(globals().items())):
            if name.startswith("test_") and callable(fn):
                fn(tmp)
                print(f"  ok {name}")
    print("STORAGE_OK")
