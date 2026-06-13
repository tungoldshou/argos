"""token 流式契约 —— 守住:最终答复逐 token 流出 text 增量,中间工具决策轮不外发 token。

用假 chunk 模拟 LangGraph astream(messages 模式)的 message_chunk 结构,
不连真模型。纯逻辑、快。
"""
from argos.core import text_delta


class _Chunk:
    def __init__(self, content):
        self.content = content


def test_text_delta_str():
    assert text_delta(_Chunk("Hel")) == "Hel"


def test_text_delta_list_keeps_only_text():
    c = [{"type": "thinking", "thinking": "嗯"}, {"type": "text", "text": "答案"}]
    assert text_delta(_Chunk(c)) == "答案"


def test_text_delta_thinking_only_is_empty():
    # 工具决策轮常只有 thinking / 无 text → 不产生 token。
    c = [{"type": "thinking", "thinking": "我要调工具"}]
    assert text_delta(_Chunk(c)) == ""


def test_text_delta_empty():
    assert text_delta(_Chunk([])) == ""
    assert text_delta(_Chunk(None)) == ""
