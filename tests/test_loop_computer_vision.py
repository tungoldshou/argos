"""2b.2 + 2c:loop._maybe_attach_screenshot —— 多模态模型把截图当图像挂到反馈消息 + 告知像素
坐标空间;非多模态 / 无截图 → 诚实降级纯文本(不挂图、不改 content)。

用 object.__new__ 绕过 AgentLoop 重型 __init__(本方法只用 self._model),OS/视觉无需真环境。
"""
from __future__ import annotations

import base64

from argos.core.loop import AgentLoop

# 合法 1x1 PNG(sniff_media_type 据 PNG 魔数判 image/png)
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _loop_with_model(multimodal: bool) -> AgentLoop:
    loop = object.__new__(AgentLoop)  # 绕过 __init__,只装方法需要的 _model
    class _Tier:
        pass
    tier = _Tier()
    tier.multimodal = multimodal
    class _Model:
        pass
    model = _Model()
    model.tier = tier
    loop._model = model  # type: ignore[attr-defined]
    return loop


def test_attach_when_multimodal(tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(_PNG_1x1)
    loop = _loop_with_model(multimodal=True)
    fb = {"role": "user", "content": "执行结果"}
    loop._maybe_attach_screenshot(fb, (str(png), (120, 80)))
    assert "attachments" in fb and len(fb["attachments"]) == 1
    assert fb["attachments"][0].media_type == "image/png"
    assert "120x80" in fb["content"]          # 2c:告知像素坐标空间
    assert "像素坐标" in fb["content"]


def test_no_attach_when_not_multimodal(tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(_PNG_1x1)
    loop = _loop_with_model(multimodal=False)
    fb = {"role": "user", "content": "执行结果"}
    loop._maybe_attach_screenshot(fb, (str(png), (120, 80)))
    assert "attachments" not in fb            # 非多模态:不挂图(诚实)
    assert fb["content"] == "执行结果"          # content 不改


def test_no_shot_is_noop(tmp_path):
    loop = _loop_with_model(multimodal=True)
    fb = {"role": "user", "content": "x"}
    loop._maybe_attach_screenshot(fb, None)
    assert "attachments" not in fb
    assert fb["content"] == "x"


def test_unreadable_path_degrades_to_text(tmp_path):
    loop = _loop_with_model(multimodal=True)
    fb = {"role": "user", "content": "执行结果"}
    loop._maybe_attach_screenshot(fb, (str(tmp_path / "missing.png"), (10, 10)))
    assert "attachments" not in fb            # 读图失败 → 诚实降级纯文本,不崩
    assert fb["content"] == "执行结果"
