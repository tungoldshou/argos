"""TranscriptLog:流式 markdown/token 增量(spec §4.2)。

token_delta 高频到达 → 用 RichLog 追加 + 内部 buffer 累计当前 assistant 段。
封装隔离 Textual API(风险:Textual API churn,spec §13)——外部只调 append_token/append_line/flush。
"""
from __future__ import annotations

import re

from textual.widgets import RichLog

_FENCE_BLOCK = re.compile(r"```[^\n]*\n.*?```\n?", re.DOTALL)  # 连吃闭围栏后的换行,块间塌缩干净


def strip_code_fences(text: str) -> str:
    """剥掉 ```...``` 完整代码块 + 尾部未闭合的 ```(流式中途)。
    代码权威展示在 CodeActionBlock,这里只留散文,避免代码显示两遍 / backtick 漏出。"""
    text = _FENCE_BLOCK.sub("", text)
    idx = text.rfind("```")        # 残留的开围栏(未闭合)
    if idx != -1:
        text = text[:idx]
    return text.strip("\n")


class TranscriptLog(RichLog):
    """主对话区。append_token 累计当前流式段;append_line 落一行系统/状态文本。

    can_focus=False:RichLog 默认可聚焦(键盘滚动),会在启动时抢走焦点 → 输入框收不到
    键,用户打不了字。把它移出焦点链,保证唯一可聚焦的是输入框(滚动用鼠标/PageUp 仍可)。"""

    can_focus = False

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("wrap", True)
        kwargs.setdefault("markup", True)
        kwargs.setdefault("highlight", False)
        super().__init__(*args, **kwargs)
        self._buffer: str = ""
        self._flushed: str = ""

    @property
    def buffer(self) -> str:
        """当前未落定的流式段(测试可读)。"""
        return self._buffer

    def append_token(self, text: str) -> None:
        """token_delta 增量:累计到 buffer;每到换行就 flush 一行进 RichLog(避免逐 token 刷屏)。"""
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.write(line)
            self._flushed += line + "\n"

    def flush(self) -> None:
        """段结束(如下一个 phase/工具)时把残余 buffer 落定。"""
        if self._buffer:
            self.write(self._buffer)
            self._flushed += self._buffer
            self._buffer = ""

    def append_line(self, text: str) -> None:
        """落一行系统/状态文本(escalation/error 摘要等)。"""
        self.flush()
        self.write(text)
        self._flushed += text + "\n"
