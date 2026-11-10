# -*- coding: utf-8 -*-
"""待办模型单元测试。运行：py -3 tests/test_todo.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tomato.todo import TodoList, clean_note, clean_text


def test_add_and_active():
    tl = TodoList()
    assert tl.add("  写周报  ") is not None          # 去首尾空白
    assert tl.items[0].text == "写周报"
    assert tl.active_id == tl.items[0].id            # 首条自动选中
    assert tl.add("   ") is None                     # 空文本忽略
    tl.add("回邮件")
    assert len(tl.items) == 2 and tl.done_count == 0


def test_text_limit():
    assert len(clean_text("x" * 100)) == 60
    assert clean_text(123) == ""                     # 非字符串容错


def test_add_with_note():
    tl = TodoList()
    t = tl.add("写周报", "包含预算与时间表")
    assert t.note == "包含预算与时间表"
    tl.add("无备注任务", "   ")                     # 空白详情 -> 空串
    assert tl.items[1].note == ""
    assert len(clean_note("x" * 500)) == 200         # 详情限长
    assert clean_note(123) == ""


def test_set_done_and_poms():
    tl = TodoList()
    t = tl.add("采购清单")
    tl.set_done(t.id, True)
    assert t.done is True and tl.done_count == 1
    tl.set_done(t.id, False)
    assert t.done is False
    tl.bump_poms(t.id)
    tl.bump_poms(t.id)
    assert t.poms == 2
    tl.bump_poms("不存在")                           # 静默忽略
    assert t.poms == 2


def test_remove_clears_active():
    tl = TodoList()
    a = tl.add("任务A")
    b = tl.add("任务B")
    tl.remove(a.id)
    assert len(tl.items) == 1
    assert tl.active_id is None
    tl.remove("不存在")                              # 幂等
    assert len(tl.items) == 1


def test_rollover_drops_done_keeps_pending():
    tl = TodoList()
    a = tl.add("完成A")
    b = tl.add("进行中B")
    tl.set_done(a.id, True)
    tl.bump_poms(b.id)
    tl.rollover("2026-11-04")
    assert tl.rollover("2026-11-04") is False        # 同日幂等
    tl.rollover("2026-11-05")
    assert [t.text for t in tl.items] == ["进行中B"]
    assert tl.items[0].poms == 1                     # poms 跟随任务
    assert tl.active_id == b.id


def test_rollover_drops_dead_active():
    tl = TodoList()
    a = tl.add("选中后被删")
    tl.active_id = a.id
    tl.set_done(a.id, True)
    tl.rollover("2026-11-05")
    assert tl.active_id is None and tl.items == []


def test_persistence_roundtrip():
    tl = TodoList()
    a = tl.add("roundtrip任务", "附上详情")
    tl.set_done(a.id, True)
    tl.add("留下来的")
    data = tl.as_dict()
    tl2 = TodoList.from_dict(data)
    assert [t.text for t in tl2.items] == ["roundtrip任务", "留下来的"]
    assert tl2.items[0].done is True
    assert tl2.items[0].note == "附上详情"             # 详情随持久化
    assert tl2.items[1].note == ""
    assert tl2.active_id == a.id                     # active 存活才恢复


def test_from_dict_tolerance():
    tl = TodoList.from_dict({
        "date": 123,                                  # 非字符串
        "items": [
            {"id": "ok1", "text": " 有效 "},          # 正常
            {"text": "没有id"},                       # 缺 id
            {"id": "ok2", "text": "   "},             # 空文本
            "garbage",                                # 非字典
            {"id": "ok3", "text": "坏poms", "poms": "x", "done": 1},
        ],
        "active_id": "ghost",                         # 指向不存在条目
    })
    assert [t.text for t in tl.items] == ["有效", "坏poms"]
    assert tl.items[1].poms == 0
    assert tl.items[1].done is True
    assert tl.active_id is None
    assert TodoList.from_dict("not-dict").items == []


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("TODO_OK")
