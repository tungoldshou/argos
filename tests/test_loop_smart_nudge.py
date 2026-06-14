"""聪明催(2026-06-14):act 的 0 动作守卫只催'疑似偷懒',实质对话答复直接收尾。

背景:真机实测"你好"耗时 20s——act 第一轮模型已给完整回复(无 ```python 代码块),但旧
0 动作守卫(_actions==0 必催一轮)以为模型偷懒,强制再调一次模型(+17s)才收尾。守卫初衷是防
"说做完了却没写代码"的伪完成(对任务有价值),但它分不清"对话回应"和"任务偷懒"。

修:`_looks_like_lazy_claim(text)` —— 模型无代码块时,只有空/极短/含"将做或声称完成"措辞才催;
实质对话答复(问候/问答/解释,不含这些措辞)→ 直接收尾(对话秒回,不白调一轮)。
"""
from __future__ import annotations

from argos.core.loop import _looks_like_lazy_claim


def test_empty_or_blank_is_lazy():
    assert _looks_like_lazy_claim("") is True
    assert _looks_like_lazy_claim("   \n  ") is True


def test_substantive_conversational_reply_is_not_lazy():
    """实质对话答复 → 不催(收尾)。"""
    assert _looks_like_lazy_claim("你好！我是 Argos，请问有什么可以帮你？") is False
    assert _looks_like_lazy_claim(
        "装饰器是一种修改函数行为的语法糖：它接受一个函数并返回新函数。"
    ) is False


def test_claim_to_act_is_lazy():
    """'我来/让我/将做'措辞但 0 动作 → 催(可能没真做)。"""
    assert _looks_like_lazy_claim("我来修复这几处代码问题。") is True
    assert _looks_like_lazy_claim("让我先看看这个文件。") is True
    assert _looks_like_lazy_claim("Let me fix that for you.") is True


def test_claim_completed_is_lazy():
    """声称完成但 0 动作 → 催(伪完成嫌疑)。这两条覆盖现有 verify 测试的措辞。"""
    assert _looks_like_lazy_claim("我觉得完成了。") is True   # test_loop_self_verified
    assert _looks_like_lazy_claim("任务完成了。") is True      # test_loop_verify_bounce
    assert _looks_like_lazy_claim("已修复，done.") is True
