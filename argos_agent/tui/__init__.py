"""Argos Textual TUI 包。"""
import os

# Textual 8.2.7("The more Kitty Release")默认启用 Kitty 键盘协议。部分终端宣称支持
# 却误解析其转义流 → 可打印键送不到已聚焦的 Input(只负责渲染的 widget 仍正常),
# 表现为"打字完全不显示、只剩光标"。这里默认禁用 Kitty 协议(保守、最大兼容)。
#
# 放在 TUI 包 __init__ 里:它保证早于任何 textual 导入执行 —— textual.constants.
# DISABLE_KITTY_KEY 在 `import textual.constants` 那一刻就定格(只认值恰为 "1"),
# 之后再设环境变量无效。setdefault 不覆盖用户已显式设置的值:想 opt-in 回 Kitty,
# 显式 `export TEXTUAL_DISABLE_KITTY_KEY=0`(任何非 "1" 值都让 Textual 启用 Kitty)。
os.environ.setdefault("TEXTUAL_DISABLE_KITTY_KEY", "1")
