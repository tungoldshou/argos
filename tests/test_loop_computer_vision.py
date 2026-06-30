"""2b.2 + 2c:loop._maybe_attach_screenshot —— 模型能看图就把截图当图像挂到反馈消息 + 告知像素
坐标空间;看不了 / 无截图 → 诚实降级纯文本(不挂图、不改 content)。

视觉能力读 self._vision_capable(run 起始经 override→缓存→探针解析),不再只认用户声明的
override —— 后者默认 None,曾导致 computer use 截图被静默丢弃(回路恒死)。test_resolve_* 锁死
"CU 开启 → run 起始照样解析能力"这条修复主线。

用 object.__new__ 绕过 AgentLoop 重型 __init__。
"""
from __future__ import annotations

import base64
import json

import pytest

from argos.core.loop import AgentLoop

# 合法 1x1 PNG(sniff_media_type 据 PNG 魔数判 image/png)
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _loop_with_vision(capable: bool | None) -> AgentLoop:
    loop = object.__new__(AgentLoop)  # 绕过 __init__,只装方法需要的 _vision_capable
    loop._vision_capable = capable  # type: ignore[attr-defined]
    return loop


def test_attach_when_capable(tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(_PNG_1x1)
    loop = _loop_with_vision(True)
    fb = {"role": "user", "content": "执行结果"}
    loop._maybe_attach_screenshot(fb, (str(png), (120, 80)))
    assert "attachments" in fb and len(fb["attachments"]) == 1
    assert fb["attachments"][0].media_type == "image/png"
    assert "120x80" in fb["content"]          # 2c:告知像素坐标空间
    assert "像素坐标" in fb["content"]
    assert not png.exists()                    # Bug3:读入内存后删临时文件,长会话不堆 /tmp


def test_no_attach_when_not_capable(tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(_PNG_1x1)
    loop = _loop_with_vision(False)
    fb = {"role": "user", "content": "执行结果"}
    loop._maybe_attach_screenshot(fb, (str(png), (120, 80)))
    assert "attachments" not in fb            # 看不了:不挂图(诚实)
    assert fb["content"] == "执行结果"          # content 不改


def test_no_attach_when_capability_unresolved(tmp_path):
    # 根因 fail-closed:_vision_capable=None(未解析)绝不挂图。修复前 gate 读 tier.multimodal
    # (默认 None)→ not None == True → 截图被丢;修复后未解析同样不挂(但 CU 起始会解析,见下)。
    png = tmp_path / "shot.png"
    png.write_bytes(_PNG_1x1)
    loop = _loop_with_vision(None)
    fb = {"role": "user", "content": "x"}
    loop._maybe_attach_screenshot(fb, (str(png), (10, 10)))
    assert "attachments" not in fb


def test_no_shot_is_noop(tmp_path):
    loop = _loop_with_vision(True)
    fb = {"role": "user", "content": "x"}
    loop._maybe_attach_screenshot(fb, None)
    assert "attachments" not in fb
    assert fb["content"] == "x"


def test_unreadable_path_degrades_to_text(tmp_path):
    loop = _loop_with_vision(True)
    fb = {"role": "user", "content": "执行结果"}
    loop._maybe_attach_screenshot(fb, (str(tmp_path / "missing.png"), (10, 10)))
    assert "attachments" not in fb            # 读图失败 → 诚实降级纯文本,不崩
    assert fb["content"] == "执行结果"


@pytest.mark.asyncio
async def test_resolve_warms_from_cache_for_computer_use(monkeypatch, tmp_path):
    # 真正的修复:tier.multimodal=None(未声明)+ 开 computer use → run 起始照样解析视觉能力。
    # 修复前 _maybe_attach_screenshot 只读 override(None)→ 截图回路恒死。
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "vision_cache.json").write_text(
        json.dumps({"https://api.x/v1": {"m1": {"verified": True, "ts": 0}}})
    )
    loop = object.__new__(AgentLoop)

    class _Tier:
        multimodal = None
        base_url = "https://api.x/v1"
        model = "m1"

    class _Model:
        tier = _Tier()

    loop._model = _Model()  # type: ignore[attr-defined]
    await loop._resolve_vision_capable(None)   # 无附件,但 CU 开 → 仍解析
    assert loop._vision_capable is True


@pytest.mark.asyncio
async def test_resolve_skipped_for_plain_text_run(monkeypatch):
    # 纯文本路径(无附件 + 未开 CU)零开销:不探针、不读缓存,_vision_capable 留 None。
    monkeypatch.delenv("ARGOS_COMPUTER_USE", raising=False)
    loop = object.__new__(AgentLoop)
    loop._model = None  # type: ignore[attr-defined]
    await loop._resolve_vision_capable(None)
    assert loop._vision_capable is None
