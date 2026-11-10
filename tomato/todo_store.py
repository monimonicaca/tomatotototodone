# -*- coding: utf-8 -*-
"""待办的 SQLite 持久化层（todos.db）——按天归档。

设计（schema v2）：
    todos     (day, id) 复合主键 —— 每天一个"桶"，互不干扰；
              同一任务跨天顺延时沿用同一 id，保持任务血缘。
    todo_meta (key, value)        date（当前列表归属日）/ active_id

按天归档语义：
- 任意一天的桶是该日的最终快照：做完的 ✔ 项永久保留，随时可回看；
- 跨天（load 新日期时）自动"接班"：把最近一天桶里未完成项复制到新桶
  （id/累计番茄数沿用），旧桶原样封存；
- save() 只写 todos.date 对应的桶（单事务整桶替换），翻看历史永不改写旧桶。

容错：库损坏 -> 转存 *.corrupt.db 保留现场并空库重建；行级脏数据丢弃不连坐。
旧 v1 库（无 day 列）在连接时自动迁移到 v2（按 meta date 整体入桶）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .constants import to_nonneg_int
from .todo import Todo, TodoList, clean_note, clean_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    day  TEXT NOT NULL,
    id   TEXT NOT NULL,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    poms INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    seq  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, id)
);
CREATE TABLE IF NOT EXISTS todo_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class TodoStore:
    """todos.db 的唯一读写入口。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None

    # ---------- 连接 ----------
    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self.path))
            try:
                self._ensure_schema(conn)
            except sqlite3.DatabaseError:
                # 损坏库（连 PRAGMA 都失败）：转存现场后换全新空库
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
                self._backup_corrupt()
                conn = sqlite3.connect(str(self.path))
                conn.executescript(SCHEMA)
            self._conn = conn
        return self._conn

    def _ensure_schema(self, conn: sqlite3.Connection):
        cols = [r[1] for r in conn.execute("PRAGMA table_info(todos)")]
        if not cols:
            conn.executescript(SCHEMA)                    # 全新库
        elif "day" not in cols:
            self._migrate_v1_to_v2(conn)                  # 旧库升级
        elif "note" not in cols:
            # v2 未带 note 列（旧版本库）：原地补列，不碰数据
            conn.execute(
                "ALTER TABLE todos ADD COLUMN note TEXT NOT NULL DEFAULT ''")

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection):
        """v1（无 day 列）-> v2：旧条目按 v1 meta 的 date 整体入桶。"""
        old_rows = conn.execute(
            "SELECT id, text, done, poms, seq FROM todos ORDER BY seq"
        ).fetchall()
        meta: dict = {}
        try:
            meta = dict(conn.execute("SELECT key, value FROM todo_meta")
                        .fetchall())
        except sqlite3.Error:
            pass
        day = meta.get("date")
        if not isinstance(day, str) or not day:
            day = ""                                       # 无日期归属则丢弃
        conn.execute("DROP TABLE todos")
        conn.executescript(SCHEMA)
        if day:
            rows = self._clean([tuple(r)[:4] for r in old_rows])
            if rows:
                conn.executemany(
                    "INSERT INTO todos (day, id, text, done, poms, note, seq) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(day, tid, text, done, poms, note, i)
                     for i, (tid, text, done, poms, note) in enumerate(rows)])
        conn.commit()

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

    def _backup_corrupt(self):
        """库文件损坏时改名保留现场，下次连接以全新空库启动。"""
        self.close()
        try:
            if self.path.exists():
                self.path.replace(self.path.with_suffix(".corrupt.db"))
        except OSError:
            pass

    # ---------- 读 ----------
    def load(self, today: str) -> TodoList:
        """装载"当前列表"（以 meta.date 为准）；跨天时自动接班。

        today 是"今天"的 ISO 日期。若 meta.date 早于 today：
        最近一天的桶保持封存，未完成项复制为今天的桶；否则直接返回
        meta.date 当天的现有桶（容忍系统时间回拨，不做倒滚）。
        """
        try:
            return self._load_current(today)
        except sqlite3.DatabaseError:
            self._backup_corrupt()
            try:
                return self._load_current(today)
            except sqlite3.Error:
                return TodoList(date=today)
        except sqlite3.Error:
            return TodoList(date=today)

    def _load_current(self, today: str) -> TodoList:
        conn = self._connection()
        meta = dict(conn.execute(
            "SELECT key, value FROM todo_meta").fetchall())

        current = meta.get("date")
        if not isinstance(current, str) or not current:
            current = today

        if current < today:
            # 新的一天：未完成项顺延为今天的桶（id 与累计番茄数沿用）
            snapped = self.load_day(current)
            seeded = TodoList(date=today)
            seeded.items = [t for t in snapped.items if not t.done]
            active = meta.get("active_id")
            seeded.active_id = (active if isinstance(active, str)
                                and seeded.get(active) else None)
            self.save(seeded)
            return seeded

        tl = self.load_day(current)
        active = meta.get("active_id")
        tl.active_id = (active if isinstance(active, str)
                        and tl.get(active) else None)
        return tl

    def load_day(self, day: str) -> TodoList:
        """读取某一天的桶（最终快照，只读语义；不涉及 meta）。"""
        day = str(day)
        try:
            rows = self._connection().execute(
                "SELECT id, text, done, poms, note FROM todos "
                "WHERE day = ? ORDER BY seq", (day,)).fetchall()
        except sqlite3.DatabaseError:
            self._backup_corrupt()
            return TodoList(date=day)
        except sqlite3.Error:
            return TodoList(date=day)
        tl = TodoList(date=day)
        tl.items = [Todo(id=tid, text=text, done=bool(done),
                         poms=to_nonneg_int(poms), note=clean_note(note))
                    for tid, text, done, poms, note in self._clean(rows)]
        return tl

    def days(self) -> list:
        """有内容的桶，按日期降序（用于历史导航）。"""
        try:
            rows = self._connection().execute(
                "SELECT DISTINCT day FROM todos ORDER BY day DESC").fetchall()
        except sqlite3.Error:
            return []
        return [r[0] for r in rows if isinstance(r[0], str) and r[0]]

    # ---------- 写 ----------
    def save(self, todos: TodoList) -> bool:
        """整桶替换：只重写 todos.date 这一天的行，其他天的桶不动。"""
        day = todos.date or ""
        try:
            conn = self._connection()
            with conn:
                conn.execute("DELETE FROM todos WHERE day = ?", (day,))
                conn.executemany(
                    "INSERT INTO todos (day, id, text, done, poms, note, seq) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(day, t.id, t.text, int(t.done), int(t.poms), t.note, i)
                     for i, t in enumerate(todos.items)])
                conn.execute(
                    "INSERT OR REPLACE INTO todo_meta (key, value) "
                    "VALUES ('date', ?)", (day,))
                if todos.active_id:
                    conn.execute(
                        "INSERT OR REPLACE INTO todo_meta (key, value) "
                        "VALUES ('active_id', ?)", (todos.active_id,))
                else:
                    conn.execute(
                        "DELETE FROM todo_meta WHERE key = 'active_id'")
            return True
        except sqlite3.Error:
            return False

    # ---------- 工具 ----------
    @staticmethod
    def _clean(rows):
        """行级清洗：丢掉缺 id / 空文本的脏行，poms 容错转非负整数。

        输入行可能带或不带 note 列（兼容旧 SELECT），统一清洗为 5 元组。
        """
        out = []
        for row in rows:
            rid, text, done, poms, note = (tuple(row) + ("", ""))[:5]
            text = clean_text(text)
            if not isinstance(rid, str) or not rid or not text:
                continue
            out.append((rid, text, bool(done), to_nonneg_int(poms),
                        clean_note(note)))
        return out
