# -*- coding: utf-8 -*-
"""提示音：Windows winsound，跨平台/静音环境下静默降级。"""
from __future__ import annotations


def play_phase_end(*, was_focus: bool) -> None:
    """阶段结束提示音。was_focus=True 表示刚结束的是专注。任何失败都静默跳过。"""
    try:
        import winsound
        if was_focus:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)   # 专注结束
        else:
            winsound.MessageBeep(winsound.MB_OK)             # 休息结束
    except Exception:
        pass
