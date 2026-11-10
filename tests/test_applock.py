# -*- coding: utf-8 -*-
"""单实例锁单元测试。运行：py -3 tests/test_applock.py"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tomato.applock import AppLock


def test_lock_exclusive(tmp: Path):
    lockfile = tmp / "run.lock"
    a = AppLock(lockfile)
    assert a.acquire() is True
    b = AppLock(lockfile)
    assert b.acquire() is False          # 第二个实例拿不到
    a.release()
    c = AppLock(lockfile)
    assert c.acquire() is True           # 释放后可重新获取
    c.release()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        test_lock_exclusive(Path(td))
    print("APPLOCK_OK")
