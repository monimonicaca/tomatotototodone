# -*- coding: utf-8 -*-
"""每日待办：纯数据模型，零 UI 依赖。

规则：
- 列表属于"某一天"，跨天时已完成项清掉、未完成项顺延（poms 计数跟随任务保留）；
- active_id 指向"当前正为之计时的待办"，永远指向存在的条目。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .constants import (MAX_TODO_NOTE, MAX_TODO_TEXT, TODO_ACTIVE_KEY,
                        TODO_DATE_KEY, TODO_ITEMS_KEY, clean_progress,
                        to_nonneg_int)


def clean_text(text) -> str:
    """规范化待办文本：去首尾空白、限长；非法输入返回空串。"""
    if not isinstance(text, str):
        return ""
    return text.strip()[:MAX_TODO_TEXT]


def clean_note(text) -> str:
    """规范化待办详情：去首尾空白、限长；非法输入返回空串。"""
    if not isinstance(text, str):
        return ""
    return text.strip()[:MAX_TODO_NOTE]


@dataclass
class Todo:
    id: str
    text: str
    done: bool = False
    poms: int = 0               # 这条任务累计吃掉的番茄数
    note: str = ""              # 这条任务的详情/备注说明
    progress: int = 0           # 完成度 0-100（百分比）

    @classmethod
    def make(cls, text: str, note: str = "", progress=0) -> "Todo":
        return cls(id=uuid.uuid4().hex[:8], text=clean_text(text),
                   note=clean_note(note), progress=clean_progress(progress))


@dataclass
class TodoList:
    date: str = ""              # 列表归属日 YYYY-MM-DD
    items: list = field(default_factory=list)
    active_id: str | None = None

    # ---------- 增删改 ----------
    def add(self, text, note="", progress=0) -> Todo | None:
        """新增待办；文本为空则忽略。首条自动成为当前任务。"""
        t = clean_text(text)
        if not t:
            return None
        todo = Todo.make(t, note, progress)
        self.items.append(todo)
        if not self.active_id:
            self.active_id = todo.id
        return todo

    def get(self, todo_id):
        for t in self.items:
            if t.id == todo_id:
                return t
        return None

    def edit(self, todo_id, text, note="", progress=None) -> Todo | None:
        """编辑条目（标题 + 详情 + 可选完成度）；标题为空则忽略。

        progress 传 None 表示本次不动完成度（兼容只改文字的旧调用方）。
        返回被修改的条目或 None。
        """
        t = self.get(todo_id)
        if t is None:
            return None
        new_text = clean_text(text)
        if not new_text:
            return None
        t.text = new_text
        t.note = clean_note(note)
        if progress is not None:
            t.progress = clean_progress(progress)
        return t

    def set_progress(self, todo_id, pct) -> Todo | None:
        """独立设置完成度（0-100，超界钳制）；不存在条目静默。"""
        t = self.get(todo_id)
        if t is not None:
            t.progress = clean_progress(pct)
        return t

    def remove(self, todo_id):
        """删除条目；删的是当前任务则清空 active_id。"""
        self.items = [t for t in self.items if t.id != todo_id]
        if self.active_id == todo_id:
            self.active_id = None

    def set_done(self, todo_id, done: bool) -> Todo | None:
        t = self.get(todo_id)
        if t is not None:
            t.done = bool(done)
        return t

    def bump_poms(self, todo_id):
        t = self.get(todo_id)
        if t is not None:
            t.poms += 1

    @property
    def done_count(self) -> int:
        return sum(1 for t in self.items if t.done)

    # ---------- 跨天 ----------
    def rollover(self, new_date: str) -> bool:
        """滚动到新的一天：清已完成、留未完成。同日重复调用无副作用。

        当前任务若被清掉（它已完成），自动顺延到第一条未完成；
        列表为空则清空 active_id。
        """
        if self.date == new_date:
            return False
        self.date = new_date
        self.items = [t for t in self.items if not t.done]
        if not self.get(self.active_id):
            self.active_id = next((t.id for t in self.items), None)
        return True

    # ---------- 持久化 ----------
    def as_dict(self) -> dict:
        return {
            TODO_DATE_KEY: self.date,
            TODO_ITEMS_KEY: [
                {"id": t.id, "text": t.text, "done": t.done,
                 "poms": t.poms, "note": t.note, "progress": t.progress}
                for t in self.items
            ],
            TODO_ACTIVE_KEY: self.active_id,
        }

    @classmethod
    def from_dict(cls, data) -> "TodoList":
        tl = cls()
        if not isinstance(data, dict):
            return tl
        d = data.get(TODO_DATE_KEY)
        tl.date = d if isinstance(d, str) else ""
        raw = data.get(TODO_ITEMS_KEY)
        if isinstance(raw, list):
            for it in raw:
                if not isinstance(it, dict):
                    continue
                tid = it.get("id")
                text = clean_text(it.get("text"))
                if not isinstance(tid, str) or not tid or not text:
                    continue
                tl.items.append(Todo(id=tid, text=text,
                                     done=bool(it.get("done")),
                                     poms=to_nonneg_int(it.get("poms")),
                                     note=clean_note(it.get("note")),
                                     progress=clean_progress(
                                         it.get("progress", 0))))
        aid = data.get(TODO_ACTIVE_KEY)
        tl.active_id = aid if isinstance(aid, str) and tl.get(aid) else None
        return tl
