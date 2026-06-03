"""TranscriptLog:流式 markdown/token 增量(spec §4.2)。

token_delta 高频到达 → 用 RichLog 追加 + 内部 buffer 累计当前 assistant 段。
封装隔离 Textual API(风险:Textual API churn,spec §13)——外部只调 append_token/append_line/flush。
"""
from __future__ import annotations

from textual.widgets import RichLog


class TranscriptLog(RichLog):
    """主对话区。append_token 累计当前流式段;append_line 落一行系统/状态文本。"""

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
