"""Internal documentation."""
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
    c = [{"type": "thinking", "thinking": "我要调工具"}]
    assert text_delta(_Chunk(c)) == ""


def test_text_delta_empty():
    assert text_delta(_Chunk([])) == ""
    assert text_delta(_Chunk(None)) == ""
