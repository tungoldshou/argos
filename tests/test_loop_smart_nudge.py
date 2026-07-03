from __future__ import annotations

from argos.core.loop import _looks_like_lazy_claim


def test_empty_or_blank_is_lazy():
    assert _looks_like_lazy_claim("") is True
    assert _looks_like_lazy_claim("   \n  ") is True


def test_substantive_conversational_reply_is_not_lazy():
    assert _looks_like_lazy_claim("你好！我是 Argos，请问有什么可以帮你？") is False
    assert _looks_like_lazy_claim(
        "装饰器是一种修改函数行为的语法糖：它接受一个函数并返回新函数。"
    ) is False


def test_claim_to_act_is_lazy():
    assert _looks_like_lazy_claim("我来修复这几处代码问题。") is True
    assert _looks_like_lazy_claim("让我先看看这个文件。") is True
    assert _looks_like_lazy_claim("Let me fix that for you.") is True


def test_claim_completed_is_lazy():
    assert _looks_like_lazy_claim("我觉得完成了。") is True   # test_loop_self_verified
    assert _looks_like_lazy_claim("任务完成了。") is True      # test_loop_verify_bounce
    assert _looks_like_lazy_claim("已修复，done.") is True
