# -*- coding: utf-8 -*-
"""配色主题：马卡龙浅色系。

用户指定色板：#EFCEE8 淡粉 / #F3D7B5 蜜桃 / #FDFFDF 奶油 / #DAF9CA 薄荷 / #C7B3E5 薰衣
默认背景 #FFFFFF。

主题与逻辑完全解耦：只要 Theme 是 frozen dataclass 的实例，
界面/引擎/存储都不需要感知具体色值；换主题 = 换实例。
 *_deep 为派生深一档色，用于描边与强调，仍以色板为母色。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    # 基础
    card: str = "#ffffff"             # 卡片底（默认背景）
    card_edge: str = "#e8e0f4"        # 卡片描边（极淡薰衣）
    ink: str = "#4a4468"              # 主文字（深紫灰）
    muted: str = "#8b83ac"            # 次级文字
    faint: str = "#b7b0d1"            # 弱文字
    # 马卡龙色板（用户指定五种）
    pink: str = "#efcee8"             # 淡粉：番茄点、完成圆点
    peach: str = "#f3d7b5"            # 蜜桃：长休息
    cream: str = "#fdffdf"            # 奶油：备用浅底
    mint: str = "#daf9ca"             # 薄荷：短休息
    lavender: str = "#c7b3e5"         # 薰衣：专注
    # 派生
    track: str = "#f1eaf8"            # 进度环底
    pill: str = "#f3eefa"             # 按钮底
    pill_active: str = "#d9ccf0"      # 按钮选中
    btn_ink: str = "#5a5380"          # 主按钮文字
    transparent_key: str = "#ff00fe"  # 透明键色（仅交给窗口层，不用于绘制）
    # 深化一档（描边 / 强调，母色仍是色板色）
    pink_deep: str = "#e2b8d8"
    mint_deep: str = "#4a9d3f"      # ✓ 深绿：浅绿在白底不可读
    lavender_deep: str = "#ab95cf"
    peach_deep: str = "#dfb98d"
    # 再深一档：细笔画小图标前景（✓/▶/●）
    mint_ink: str = "#3d7a34"
    pink_ink: str = "#b05aa0"
    lavender_ink: str = "#6d5ba8"

    def color_for_mode(self, mode: str) -> str:
        """阶段 -> 主题色：专注薰衣 / 短休薄荷 / 长休蜜桃。"""
        try:
            return {"focus": self.lavender,
                    "short": self.mint,
                    "long": self.peach}[mode]
        except KeyError:
            return self.lavender


MACARON = Theme()
