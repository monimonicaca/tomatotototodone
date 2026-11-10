# -*- coding: utf-8 -*-
"""单实例锁：防止双开导致的双悬浮窗与配置互踩。

实现：对 run.lock 文件加一把非阻塞独占锁；
进程退出或被强杀时由操作系统自动释放，不会留下死锁。
"""
from __future__ import annotations

import sys
from pathlib import Path


class AppLock:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._handle = None

    def acquire(self) -> bool:
        """尝试加锁。成功返回 True；已被其他实例持有返回 False。"""
        try:
            self._handle = open(self._path, "a+")
            if sys.platform == "win32":
                import msvcrt
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._handle.fileno(),
                            fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except Exception:
            if self._handle:
                try:
                    self._handle.close()
                except OSError:
                    pass
                self._handle = None
            return False

    def release(self):
        if self._handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        finally:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None
