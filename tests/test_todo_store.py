# -*- coding: utf-8 -*-
"""待办 SQLite 存储单元测试（按天归档语义）。运行：py -3 tests/test_todo_store.py"""
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tomato.todo import TodoList
from tomato.todo_store import TodoStore

D1, D2, D3 = "2026-11-04", "2026-11-05", "2026-11-06"


def make_snapshot(day=D1, with_done=True):
    """构造一份某天的快照：一条未完成（poms=1）+ 可选一条已完成。"""
    tl = TodoList()
    tl.date = day
    a = tl.add("进行中的任务")
    tl.bump_poms(a.id)
    if with_done:
        tl.add("已完成的任务")
        tl.set_done(tl.items[1].id, True)
    tl.active_id = a.id
    return tl, a.id


def test_fresh_db_empty(tmp: Path):
    store = TodoStore(tmp / "fresh.db")
    tl = store.load(D2)
    store.close()
    assert tl.items == [] and tl.date == D2 and tl.active_id is None


def test_same_day_roundtrip(tmp: Path):
    store = TodoStore(tmp / "t.db")
    snap, aid = make_snapshot(D1)
    assert store.save(snap) is True

    tl = store.load(D1)                 # 当天再读：原样返回（含已完成）
    store.close()
    assert [t.text for t in tl.items] == ["进行中的任务", "已完成的任务"]
    assert tl.items[1].done is True
    assert tl.items[0].poms == 1
    assert tl.active_id == aid


def test_rollover_seeds_pending_and_archives(tmp: Path):
    """跨天：未完成项接班为今天的桶；旧桶保留完整快照。"""
    db = tmp / "t.db"
    store = TodoStore(db)
    snap, aid = make_snapshot(D1)       # 1 未完成(poms=1) + 1 已完成
    store.save(snap)
    store.close()

    s2 = TodoStore(db)
    tl = s2.load(D2)                    # D1 -> D2 跨天
    assert tl.date == D2
    assert [t.text for t in tl.items] == ["进行中的任务"]   # 只带未完成
    assert tl.items[0].id == snap.items[0].id              # 血缘沿用
    assert tl.items[0].poms == 1                           # 累计番茄沿用
    assert tl.active_id == aid

    old = s2.load_day(D1)               # 旧桶完整封存（含已完成）
    assert [t.text for t in old.items] == ["进行中的任务", "已完成的任务"]
    assert old.items[1].done is True
    assert s2.days() == [D2, D1]        # 降序：今天的桶 + 旧桶
    s2.close()


def test_rollover_all_done_seeds_empty(tmp: Path):
    db = tmp / "t.db"
    store = TodoStore(db)
    tl = TodoList()
    tl.date = D1
    a = tl.add("独任务")
    tl.set_done(a.id, True)
    store.save(tl)
    store.close()

    s2 = TodoStore(db)
    seeded = s2.load(D2)
    assert seeded.date == D2 and seeded.items == []
    assert s2.load_day(D1).items[0].done is True          # 旧桶不丢
    assert s2.days() == [D1]                              # 空桶不成日
    s2.close()


def test_midnight_rollover_keeps_yesterday_bucket(tmp: Path):
    """运行中跨天（in-memory rollover + save）时旧桶同样封存。"""
    db = tmp / "t.db"
    store = TodoStore(db)
    tl = TodoList()
    tl.date = D1
    a = tl.add("带着走的任务")
    tl.bump_poms(a.id)
    tl.set_done(tl.add("做完的").id, True)
    store.save(tl)                       # D1 最终状态落桶
    tl.rollover(D2)                      # （controller 的跨天动作）
    store.save(tl)                       # 新的一天写自己的桶
    store.close()

    s2 = TodoStore(db)
    assert [t.text for t in s2.load_day(D1).items] == ["带着走的任务", "做完的"]
    assert s2.load(D2).items[0].poms == 1
    s2.close()


def test_save_only_replaces_that_day(tmp: Path):
    store = TodoStore(tmp / "t.db")
    store.save(make_snapshot(D1)[0])
    store.save(make_snapshot(D2)[0])

    # 改 D1：D2 的桶必须原封不动
    edited = TodoList()
    edited.date = D1
    edited.add("改过的D1新条目")
    store.save(edited)

    d1 = store.load_day(D1)
    d2 = store.load_day(D2)
    store.close()
    assert [t.text for t in d1.items] == ["改过的D1新条目"]
    assert len(d2.items) == 2            # 快照原样


def test_v1_schema_migration(tmp: Path):
    """旧 v1 库（无 day 列）自动按 meta date 入桶。"""
    db = tmp / "v1.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE todos (id TEXT PRIMARY KEY, text TEXT, done INTEGER,
                            poms INTEGER, seq INTEGER);
        CREATE TABLE todo_meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO todos VALUES ('a1', '旧任务A', 0, 2, 0);
        INSERT INTO todos VALUES ('a2', '旧任务B', 1, 0, 1);
        INSERT INTO todo_meta VALUES ('date', '2026-11-04');
        INSERT INTO todo_meta VALUES ('active_id', 'a1');
    """)
    conn.commit()
    conn.close()

    store = TodoStore(db)
    tl = store.load(D1)                  # 同日读取：迁移后原样
    assert [t.text for t in tl.items] == ["旧任务A", "旧任务B"]
    assert tl.items[0].poms == 2 and tl.items[1].done is True
    assert tl.active_id == "a1"
    store.close()

    # 跨天后同样能接班/归档
    s2 = TodoStore(db)
    seeded = s2.load(D2)
    assert [t.text for t in seeded.items] == ["旧任务A"]
    assert s2.load_day(D1).items[1].done is True
    s2.close()


def test_corrupt_db_self_heal(tmp: Path):
    db = tmp / "bad.db"
    db.write_bytes(b"this is definitely not a sqlite database " * 20)
    store = TodoStore(db)

    tl = store.load(D2)
    assert tl.items == []                      # 损坏 -> 空表兜底
    assert (tmp / "bad.corrupt.db").exists()   # 现场保留

    # 自愈后可正常读写，且按天语义正常
    snap, _ = make_snapshot(D2)
    assert store.save(snap) is True
    assert [t.text for t in store.load(D2).items] == ["进行中的任务", "已完成的任务"]
    store.close()


def test_note_roundtrip(tmp: Path):
    """详情字段随当天桶持久化（同天读写 + 跨天接班）。"""
    db = tmp / "t.db"
    store = TodoStore(db)
    tl = TodoList()
    tl.date = D1
    a = tl.add("买详情的任务", "这是详细说明，写清楚每一步")
    tl.bump_poms(a.id)
    store.save(tl)
    store.close()

    s2 = TodoStore(db)
    loaded = s2.load(D1)
    assert loaded.items[0].note == "这是详细说明，写清楚每一步"
    s2.close()


def test_note_rollover_keeps_note(tmp: Path):
    """跨天接班：未完成项的详情随 id 一并沿用。"""
    db = tmp / "t.db"
    store = TodoStore(db)
    tl = TodoList()
    tl.date = D1
    tl.add("带备注的任务", "备注内容")
    store.save(tl)
    store.close()

    s2 = TodoStore(db)
    seeded = s2.load(D2)
    assert seeded.items[0].note == "备注内容"
    s2.close()


def test_v2_schema_adds_note_column(tmp: Path):
    """旧 v2 库（无 note 列）连接时自动补列，数据不丢、可写回。"""
    db = tmp / "oldv2.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE todos (
            day TEXT NOT NULL, id TEXT NOT NULL, text TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0, poms INTEGER NOT NULL DEFAULT 0,
            seq INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, id));
        CREATE TABLE todo_meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO todos VALUES ('2026-11-04', 'a1', '旧任务', 0, 2, 0);
        INSERT INTO todo_meta VALUES ('date', '2026-11-04');
        INSERT INTO todo_meta VALUES ('active_id', 'a1');
    """)
    conn.commit()
    conn.close()

    store = TodoStore(db)
    tl = store.load(D1)
    assert [t.text for t in tl.items] == ["旧任务"]
    assert tl.items[0].note == ""                # 补列后 note 默认空
    tl.items[0].note = "新写的详情"
    store.save(tl)                                # 写回正常
    store.close()

    s2 = TodoStore(db)
    assert s2.load(D1).items[0].note == "新写的详情"
    s2.close()


def test_dirty_rows_tolerated(tmp: Path):
    """绕过 save 直接写脏数据（模拟手动改库），读取必须不崩。"""
    db = tmp / "dirty.db"
    store = TodoStore(db)
    snap, _ = make_snapshot(D1)
    store.save(snap)

    conn = sqlite3.connect(str(db))
    with conn:
        conn.execute("INSERT INTO todos VALUES (?, 'x1', '   ', 0, 0, '', 9)", (D1,))     # 空文本
        conn.execute("INSERT INTO todos VALUES (?, 'x2', '坏poms', 0, 'zx', '备注', 8)", (D1,))  # 坏poms/带备注
        conn.execute("INSERT OR REPLACE INTO todo_meta VALUES "
                     "('active_id', 'ghost')")
    conn.close()

    tl = store.load_day(D1)
    store.close()
    assert [t.text for t in tl.items] == ["进行中的任务", "已完成的任务", "坏poms"]
    assert tl.items[2].poms == 0              # 坏 poms 回 0
    assert tl.active_id is None               # 悬空 active 丢弃


def test_days_listing(tmp: Path):
    store = TodoStore(tmp / "t.db")
    store.save(make_snapshot(D1)[0])
    store.save(make_snapshot(D2)[0])          # D2 save 会接 meta，days 仍按桶列出
    store.close()

    s2 = TodoStore(tmp / "t.db")
    assert s2.days() == [D2, D1]
    s2.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, fn in sorted(list(globals().items())):
            if name.startswith("test_") and callable(fn):
                fn(tmp)
                print(f"  ok {name}")
    print("TODO_STORE_OK")
