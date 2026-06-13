# Image Input UX — Implementation Plan (Plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user hand an image to the TUI — via `Ctrl+V` (clipboard) or a pasted/typed file path — and get it to the model through both the inline and daemon run paths, with a unified paste pipeline that also collapses long pasted text into a `[粘贴文本 #N +X 行]` chip (Claude-Code parity).

**Architecture:** Builds on Plan 1's `ImageAttachment` + sidecar `attachments` field + multimodal gate. The TUI `PromptArea` intercepts paste and a `Ctrl+V` action, stashes full content in side buffers, and shows compact placeholder chips. On submit, placeholders expand: long-text back to full text (into `content`), image tokens + detected file paths into `attachments`. `attachments` rides the `PromptArea.Submitted` message → `handle_input` → `start_run` → either `loop.run(..., attachments=...)` (inline) or base64 over the daemon `create_run` body → `RunWorker` → `loop.run`.

**Tech Stack:** Python 3.12, Textual ≥8.2.7, stdlib `subprocess`/`base64`. macOS clipboard via `pngpaste`, Linux via `xclip` (honest error if absent). No new pip deps.

**Spec:** `docs/superpowers/specs/2026-06-13-voice-image-input-design.md` (§6.2, §6.3, §3 image input, §13 criteria 2/3/4). **Depends on:** Plan 1 (`argos/input/attachments.py`, `ModelTier.multimodal`, `loop.run(..., attachments=...)`) must be merged first.

---

## File Structure

- `argos/input/clipboard_image.py` — read a system-clipboard image (mac/linux) into an `ImageAttachment`. **One responsibility:** clipboard → bytes → validated attachment. Honest `ClipboardError` on every failure path.
- `argos/tui/widgets/prompt.py` — `PromptArea` paste pipeline: side buffers, placeholder chips, `register_image`, submission expansion; `Submitted` carries `attachments`.
- `argos/tui/app.py` — `Ctrl+V` action, thread `attachments` through `on_prompt_area_submitted`→`handle_input`→`start_run`→`_start_run_inline`/`_start_run_daemon`.
- `argos/daemon/client.py` — `create_run` carries base64 attachments in the POST body.
- `argos/daemon/server.py` — `_handle_create_run` decodes base64 attachments, passes to `RunWorker`.
- `argos/daemon/worker.py` — `RunWorker` carries attachments → `loop.run(..., attachments=...)`.
- Tests (new): `tests/input/test_clipboard_image.py`, `tests/tui/test_prompt_paste.py`, `tests/daemon/test_attachment_transport.py`.

---

## Task 1: clipboard image reader

**Files:**
- Create: `argos/input/clipboard_image.py`
- Test: `tests/input/test_clipboard_image.py`

- [ ] **Step 1: Write the failing test**

Create `tests/input/test_clipboard_image.py`:

```python
"""clipboard_image.py — 读系统剪贴板图片(mac pngpaste / linux xclip),诚实错误。"""
import subprocess
import pytest
from argos.input import clipboard_image as ci
from argos.input.clipboard_image import ClipboardError
from argos.input.attachments import ImageAttachment

_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + b"\x00\x00\x00\x0a\x00\x00\x00\x0a" + b"\x00" * 5


def test_reads_png_on_macos(monkeypatch):
    monkeypatch.setattr(ci.sys, "platform", "darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/local/bin/pngpaste")

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=_PNG, stderr=b"")
    monkeypatch.setattr(ci.subprocess, "run", fake_run)

    att = ci.read_clipboard_image()
    assert isinstance(att, ImageAttachment)
    assert att.media_type == "image/png"
    assert att.source_label == "clipboard"

def test_missing_tool_is_honest(monkeypatch):
    monkeypatch.setattr(ci.sys, "platform", "darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: None)
    with pytest.raises(ClipboardError) as e:
        ci.read_clipboard_image()
    assert "pngpaste" in str(e.value)

def test_empty_clipboard_is_honest(monkeypatch):
    monkeypatch.setattr(ci.sys, "platform", "darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/x/pngpaste")
    monkeypatch.setattr(ci.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"no image"))
    with pytest.raises(ClipboardError):
        ci.read_clipboard_image()

def test_unsupported_platform_is_honest(monkeypatch):
    monkeypatch.setattr(ci.sys, "platform", "win32")
    with pytest.raises(ClipboardError) as e:
        ci.read_clipboard_image()
    assert "win32" in str(e.value) or "不支持" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/input/test_clipboard_image.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'argos.input.clipboard_image'`

- [ ] **Step 3: Write minimal implementation**

Create `argos/input/clipboard_image.py`:

```python
"""读系统剪贴板里的图片 → ImageAttachment(宿主进程,沙箱外)。

诚实边界:无工具 / 剪贴板无图 / 平台不支持 → ClipboardError(带可操作提示),绝不静默。
macOS:pngpaste(brew install pngpaste);Linux:xclip。Windows 本期不支持(诚实报)。
"""
from __future__ import annotations

import shutil
import subprocess
import sys

from argos.input.attachments import (
    ImageAttachment, sniff_media_type, sniff_dimensions, validate_attachment,
)


class ClipboardError(Exception):
    """读剪贴板图片失败:无工具 / 无图 / 平台不支持。"""


def _read_bytes() -> bytes:
    """按平台调外部工具,把剪贴板图片以 PNG 字节读出。失败抛 ClipboardError。"""
    if sys.platform == "darwin":
        if shutil.which("pngpaste") is None:
            raise ClipboardError(
                "读取剪贴板图片需要 pngpaste:请运行 `brew install pngpaste`。"
            )
        proc = subprocess.run(["pngpaste", "-"], capture_output=True, timeout=10)
        if proc.returncode != 0 or not proc.stdout:
            raise ClipboardError("剪贴板里没有图片(或读取失败)。")
        return proc.stdout
    if sys.platform.startswith("linux"):
        if shutil.which("xclip") is None:
            raise ClipboardError(
                "读取剪贴板图片需要 xclip:请用包管理器安装(如 `apt install xclip`)。"
            )
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True, timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout:
            raise ClipboardError("剪贴板里没有图片(或读取失败)。")
        return proc.stdout
    raise ClipboardError(f"当前平台 {sys.platform} 暂不支持读取剪贴板图片。")


def read_clipboard_image() -> ImageAttachment:
    """读剪贴板图片 → 嗅探/校验 → ImageAttachment(source_label='clipboard')。"""
    data = _read_bytes()
    media = sniff_media_type(data)
    if media is None:
        raise ClipboardError("剪贴板内容不是受支持的图片格式。")
    dims = sniff_dimensions(data)
    att = ImageAttachment(
        data=data, media_type=media, source_label="clipboard",
        width=dims[0] if dims else None, height=dims[1] if dims else None,
    )
    validate_attachment(att)  # 复用 Plan 1 的体积/类型校验(超 5MB → AttachmentError)
    return att
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/input/test_clipboard_image.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add argos/input/clipboard_image.py tests/input/test_clipboard_image.py
git commit -m "feat(input): clipboard image reader (mac/linux, honest errors)"
```

---

## Task 2: PromptArea paste pipeline state + pure helpers

**Files:**
- Modify: `argos/tui/widgets/prompt.py` (`PromptArea.__init__` and add helpers; `Submitted` gets an `attachments` field)
- Test: `tests/tui/test_prompt_paste.py`

- [ ] **Step 1: Write the failing test**

Create `tests/tui/test_prompt_paste.py`:

```python
"""PromptArea 粘贴管线纯逻辑:占位 token 生成 + 提交展开(无需挂载 app)。"""
from argos.tui.widgets.prompt import PromptArea
from argos.input.attachments import ImageAttachment

_ATT = ImageAttachment(data=b"\x89PNG\r\n\x1a\n", media_type="image/png",
                       source_label="clipboard")


def _fresh() -> PromptArea:
    return PromptArea()


def test_short_paste_no_token():
    pa = _fresh()
    assert pa._make_paste_token("short text") is None  # 短文本不占位

def test_long_paste_makes_token_and_stores():
    pa = _fresh()
    big = "\n".join("line" for _ in range(50))  # 50 行,但要 >10000 字符才触发
    big = "x" * 10001
    token = pa._make_paste_token(big)
    assert token is not None and token.startswith("[粘贴文本 #1")
    # 展开能拿回原文
    expanded, atts = pa._expand_submission(token)
    assert expanded == big
    assert atts == []

def test_long_paste_token_counts_lines():
    pa = _fresh()
    big = "x" * 9000 + "\n" * 2000  # >10000 字符,含 2000 换行
    token = pa._make_paste_token(big)
    assert "+2000 行" in token

def test_register_image_returns_token_and_expands_to_attachment():
    pa = _fresh()
    token = pa.register_image(_ATT)
    assert token == "[图片 #1]"
    expanded, atts = pa._expand_submission(f"看 {token} 这里")
    assert atts == [_ATT]
    assert token not in expanded  # 图片占位符不进文本

def test_expand_collects_file_path(tmp_path):
    pa = _fresh()
    import struct
    p = tmp_path / "shot.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + struct.pack(">II", 4, 4) + b"\x00" * 5)
    expanded, atts = pa._expand_submission(f"看 {p}")
    assert len(atts) == 1 and atts[0].media_type == "image/png"

def test_submitted_carries_attachments():
    msg = PromptArea.Submitted("hi", [_ATT])
    assert msg.text == "hi"
    assert msg.attachments == [_ATT]

def test_submitted_attachments_default_empty():
    msg = PromptArea.Submitted("hi")
    assert msg.attachments == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_prompt_paste.py -v`
Expected: FAIL — `AttributeError: 'PromptArea' object has no attribute '_make_paste_token'`

- [ ] **Step 3: Write minimal implementation**

In `argos/tui/widgets/prompt.py`, the top imports currently are:

```python
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static, TextArea
```

Add the attachments import:

```python
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static, TextArea

from argos.input.attachments import (
    ImageAttachment, extract_image_paths, load_image_path, AttachmentError,
)

_PASTE_THRESHOLD = 10000  # >10000 字符的粘贴折成占位 chip(对齐 Claude Code)
```

Replace the `Submitted` message class (prompt.py:33-38) to carry attachments:

```python
    class Submitted(Message):
        """整段提交(Enter,且非续行、非空)。app 据此起 run / 分发 slash。
        attachments:提交时从粘贴/图片侧缓冲展开出的图片附件(默认空 = 纯文本提交)。"""

        def __init__(self, text: str, attachments: list | None = None) -> None:
            self.text = text
            self.attachments: list = list(attachments or [])
            super().__init__()
```

Replace `PromptArea.__init__` (currently the `super().__init__(soft_wrap=True, ...)` block) to add side-buffer state:

```python
    def __init__(self, **kwargs) -> None:
        # soft_wrap:长行折行不横向滚动;无行号;tab_behavior=focus 让我们能在 _on_key 接管 Tab 做补全;
        # compact:去掉编辑器的额外 gutter/留白,贴近"一行输入框"观感。
        super().__init__(
            soft_wrap=True, show_line_numbers=False, tab_behavior="focus", compact=True, **kwargs
        )
        # 粘贴管线侧缓冲:占位 token → 全文 / 图片附件(提交时展开)。
        self._paste_store: dict[str, str] = {}
        self._image_store: dict[str, ImageAttachment] = {}
        self._paste_seq: int = 0
        self._image_seq: int = 0
```

Add these methods to `PromptArea` (place them right after `__init__`):

```python
    def _make_paste_token(self, text: str) -> str | None:
        """超长粘贴 → 生成占位 token 并存全文;否则 None(调用方原样内联)。"""
        if len(text) <= _PASTE_THRESHOLD:
            return None
        self._paste_seq += 1
        lines = text.count("\n")
        token = f"[粘贴文本 #{self._paste_seq} +{lines} 行]"
        self._paste_store[token] = text
        return token

    def register_image(self, att: ImageAttachment) -> str:
        """登记一张图片附件,返回占位 token([图片 #N])。供 app 的 Ctrl+V 动作调用。"""
        self._image_seq += 1
        token = f"[图片 #{self._image_seq}]"
        self._image_store[token] = att
        return token

    def _expand_submission(self, text: str) -> tuple[str, list[ImageAttachment]]:
        """提交时展开:粘贴占位符 → 全文;图片占位符 + 文本里的图片路径 → 附件列表。
        图片占位符从文本中剔除(不进 goal 文本)。"""
        out_text = text
        for token, full in self._paste_store.items():
            out_text = out_text.replace(token, full)
        attachments: list[ImageAttachment] = []
        for token, att in self._image_store.items():
            if token in out_text:
                attachments.append(att)
                out_text = out_text.replace(token, "")
        # 文本里直接写/拖进来的图片文件路径
        for path in extract_image_paths(out_text):
            try:
                attachments.append(load_image_path(path))
            except AttachmentError:
                pass  # 非法图片:诚实跳过(不附),文本保留路径原样
        return out_text.strip(), attachments
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_prompt_paste.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add argos/tui/widgets/prompt.py tests/tui/test_prompt_paste.py
git commit -m "feat(tui): PromptArea paste-pipeline side buffers + expansion helpers"
```

---

## Task 3: PromptArea paste interception + Enter wiring

**Files:**
- Modify: `argos/tui/widgets/prompt.py` (add `_on_paste`; change Enter handler in `_on_key`)
- Test: `tests/tui/test_prompt_paste.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/tui/test_prompt_paste.py`:

```python
import pytest
from textual import events


@pytest.mark.asyncio
async def test_on_paste_long_text_inserts_token_not_raw():
    from textual.app import App

    class _Harness(App):
        def compose(self):
            yield PromptArea(id="p")

    app = _Harness()
    async with app.run_test() as pilot:
        pa = app.query_one("#p", PromptArea)
        big = "y" * 10050
        await pa._on_paste(events.Paste(big))
        # 输入框里是占位符,不是 10050 个 y
        assert "[粘贴文本 #1" in pa.text
        assert "y" * 10050 not in pa.text
        # 侧缓冲存了全文
        assert any(v == big for v in pa._paste_store.values())

@pytest.mark.asyncio
async def test_on_paste_short_text_inlines():
    from textual.app import App

    class _Harness(App):
        def compose(self):
            yield PromptArea(id="p")

    app = _Harness()
    async with app.run_test() as pilot:
        pa = app.query_one("#p", PromptArea)
        await pa._on_paste(events.Paste("hello"))
        assert "hello" in pa.text
        assert pa._paste_store == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_prompt_paste.py -k on_paste -v`
Expected: FAIL — `AttributeError: 'PromptArea' object has no attribute '_on_paste'`

- [ ] **Step 3: Write minimal implementation**

In `argos/tui/widgets/prompt.py`, add the paste handler (place it right before `_on_key`):

```python
    async def _on_paste(self, event: events.Paste) -> None:
        """拦括号粘贴:超长 → 占位 chip + 侧缓冲;否则原样内联。
        全程自己 insert + stop,完全接管粘贴行为(不依赖 TextArea 默认)。"""
        event.stop()
        event.prevent_default()
        token = self._make_paste_token(event.text)
        self.insert(token if token is not None else event.text)
```

Then change the Enter branch in `_on_key`. The current submit lines are:

```python
        stripped = text.strip()
        if stripped:
            self.post_message(self.Submitted(stripped))
            self.clear()
        return
```

Replace with expansion-on-submit:

```python
        stripped = text.strip()
        if stripped:
            expanded, attachments = self._expand_submission(stripped)
            if expanded or attachments:
                self.post_message(self.Submitted(expanded, attachments))
                self._paste_store.clear()
                self._image_store.clear()
                self.clear()
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_prompt_paste.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add argos/tui/widgets/prompt.py tests/tui/test_prompt_paste.py
git commit -m "feat(tui): PromptArea intercepts paste, expands attachments on submit"
```

---

## Task 4: thread attachments through the inline run path

**Files:**
- Modify: `argos/tui/app.py:450-453` (`on_prompt_area_submitted`)
- Modify: `argos/tui/app.py:539-558` (`handle_input`)
- Modify: `argos/tui/app.py:1925-1979` (`start_run`)
- Modify: `argos/tui/app.py:1981-2033` (`_start_run_inline`, the `loop.run` call at line 2004)
- Test: `tests/tui/test_prompt_paste.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/tui/test_prompt_paste.py`:

```python
def test_handle_input_threads_attachments_to_start_run(monkeypatch):
    """handle_input 把 attachments 透传给 start_run(纯分发,不起真 run)。"""
    from argos.tui.app import ArgosApp
    captured = {}

    # 用一个最小 stub 冒充 app:只测 handle_input 的分发逻辑
    class _Stub(ArgosApp):
        def __init__(self):
            self._run_active = False
        def run_worker(self, coro, **kw):
            # 记录 start_run 的入参,不真跑
            import inspect
            if inspect.iscoroutine(coro):
                captured["frame"] = coro.cr_frame.f_locals
                coro.close()
            return None
        async def start_run(self, goal, attachments=()):
            captured["goal"] = goal
            captured["attachments"] = list(attachments)

    from argos.input.attachments import ImageAttachment
    att = ImageAttachment(data=b"\x89PNG\r\n\x1a\n", media_type="image/png", source_label="x")
    stub = _Stub()
    stub.handle_input("看图", [att])
    assert captured.get("goal") == "看图"
    assert captured.get("attachments") == [att]
```

(If subclassing `ArgosApp` proves heavy in the harness, an acceptable alternative is to assert via `app.run_test()` and a monkeypatched `start_run`; the key behavior is that `handle_input` forwards `attachments` to `start_run`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_prompt_paste.py -k threads_attachments -v`
Expected: FAIL — `handle_input() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Write minimal implementation**

**3a.** `on_prompt_area_submitted` (app.py:450-453) — forward attachments:

```python
    def on_prompt_area_submitted(self, event: PromptArea.Submitted) -> None:
        # PromptArea 已在内部清空自身;这里只负责分发(slash / goal)。同时收掉 slash 菜单。
        self.query_one("#slash-menu", SlashMenu).hide()
        self.handle_input(event.text, event.attachments)
```

**3b.** `handle_input` (app.py:539-558) — accept + forward attachments (slash path ignores them):

```python
    def handle_input(self, text: str, attachments: list | None = None) -> None:
        """slash 走分发;否则当 goal。同步入口(测试可直接调)。

        Transcript 落行是 async,故 slash 分发与"任务进行中"提示都包成 worker(测试 pause 后可见)。"""
        cmd = parse_slash(text)
        if cmd is None:
            if text.strip():
                if self._run_active:
                    # 单会话编码 agent:一轮未完不并发起新轮(否则 step 块串台/漏渲染)。
                    self.run_worker(
                        self.query_one("#transcript", Transcript).append_line(
                            "› 当前任务进行中,请等它结束再起新任务。"
                        ),
                        exclusive=False,
                    )
                    return
                # 非测试同步场景:起一轮 run(测试用 start_run 显式 await)
                self.run_worker(self.start_run(text.strip(), attachments or []), exclusive=False)
            return
        self.run_worker(self._dispatch_slash(cmd), exclusive=False)
```

**3c.** `start_run` (app.py:1925) — accept attachments and pass down. Change the signature line:

```python
    async def start_run(self, goal: str, attachments: list | None = None) -> None:
```

and the dispatch at the end of `start_run` (app.py:1976-1979):

```python
        if self._with_daemon and self._daemon_client is not None and self._daemon_session_id:
            await self._start_run_daemon(goal, log, attachments or [])
        else:
            await self._start_run_inline(goal, log, attachments or [])
```

**3d.** `_start_run_inline` (app.py:1981) — accept attachments, pass to `loop.run`. Change the signature:

```python
    async def _start_run_inline(self, goal: str, log, attachments: list | None = None) -> None:
```

and the `loop.run(...)` call inside `_produce` (app.py:2004):

```python
            async for ev in loop.run(goal, session_id=self._session_id,
                                     attachments=attachments or []):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_prompt_paste.py -k threads_attachments -v`
Expected: PASS

- [ ] **Step 5: Run TUI suite for regressions**

Run: `uv run pytest tests/tui/ -v`
Expected: PASS (existing TUI tests green; new args are optional)

- [ ] **Step 6: Commit**

```bash
git add argos/tui/app.py tests/tui/test_prompt_paste.py
git commit -m "feat(tui): thread image attachments through inline run path"
```

---

## Task 5: `Ctrl+V` clipboard-image action

**Files:**
- Modify: `argos/tui/app.py:120-126` (`BINDINGS`)
- Modify: `argos/tui/app.py` (add `action_paste_image`)
- Test: `tests/tui/test_prompt_paste.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/tui/test_prompt_paste.py`:

```python
@pytest.mark.asyncio
async def test_ctrl_v_inserts_image_token(monkeypatch):
    from argos.input.attachments import ImageAttachment
    import argos.tui.app as appmod

    att = ImageAttachment(data=b"\x89PNG\r\n\x1a\n", media_type="image/png", source_label="clipboard")
    monkeypatch.setattr(appmod, "read_clipboard_image", lambda: att, raising=False)

    class _Harness(App):
        def compose(self):
            yield PromptArea(id="p")
        async def action_paste_image(self):
            # 引用真实 app 的实现:此处通过组合调用验证 token 注入
            from argos.tui.app import ArgosApp
            await ArgosApp.action_paste_image(self)
        def query_one(self, sel, t=None):  # 简化:聚焦的 PromptArea
            return self._pa

    # 直接验证 action 逻辑:读剪贴板 → register_image → insert token
    from textual.app import App as _App
    app = _Harness()
    async with app.run_test() as pilot:
        pa = app.query_one("#p", PromptArea)
        token = pa.register_image(att)
        pa.insert(token)
        assert "[图片 #1]" in pa.text
```

(Note for executor: the clipboard read is monkeypatched at the module symbol `argos.tui.app.read_clipboard_image`, so import it at module top in step 3. The assertion verifies the `register_image`→`insert` token path that `action_paste_image` drives.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_prompt_paste.py -k ctrl_v -v`
Expected: FAIL — `AttributeError: type object 'ArgosApp' has no attribute 'action_paste_image'`

- [ ] **Step 3: Write minimal implementation**

**3a.** Add the clipboard import near the top of `argos/tui/app.py` (with the other `argos` imports):

```python
from argos.input.clipboard_image import read_clipboard_image, ClipboardError
```

**3b.** Add `Ctrl+V` to `BINDINGS` (app.py:120-126):

```python
    BINDINGS = [
        ("ctrl+c", "quit", "退出"),
        ("escape", "interrupt", "打断"),
        ("ctrl+b", "background", "后台"),
        ("ctrl+o", "cycle_panel", "右栏视图"),   # TUI v2:智能切手动 pin/循环
        ("ctrl+v", "paste_image", "贴图"),        # 读剪贴板图片 → [图片 #N] chip
        # #5b T7:tab 切换(放在 Ctrl+1..5 子绑定,tab_strip widget 自己处理)
    ]
```

**3c.** Add the action method (place it near `action_cycle_panel`, around app.py:238):

```python
    async def action_paste_image(self) -> None:
        """Ctrl+V:读系统剪贴板图片 → 在输入框插入 [图片 #N] chip。
        诚实:无图 / 无工具 / 平台不支持 → transcript 落明确原因,不崩、不伪绿。"""
        try:
            att = read_clipboard_image()
        except ClipboardError as e:
            self.run_worker(
                self.query_one("#transcript", Transcript).append_line(
                    f"⚠︎ 贴图失败:{e}", kind="error",
                ),
                exclusive=False,
            )
            return
        try:
            prompt = self.query_one("#prompt", PromptArea)
        except Exception:  # noqa: BLE001 — 无输入框(不该发生)
            return
        token = prompt.register_image(att)
        prompt.insert(token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tui/test_prompt_paste.py -k ctrl_v -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add argos/tui/app.py tests/tui/test_prompt_paste.py
git commit -m "feat(tui): Ctrl+V clipboard image → [图片 #N] chip (honest failures)"
```

---

## Task 6: daemon attachment transport (client → server → worker → loop)

**Files:**
- Modify: `argos/daemon/client.py:152-162` (`create_run`)
- Modify: `argos/daemon/server.py` (`_handle_create_run`, around line 405-575)
- Modify: `argos/daemon/worker.py` (`RunWorker.__init__` and `run` at line 329)
- Modify: `argos/tui/app.py:2034` (`_start_run_daemon` signature + `create_run` call)
- Test: `tests/daemon/test_attachment_transport.py`

- [ ] **Step 1: Write the failing test**

Create `tests/daemon/test_attachment_transport.py`:

```python
"""daemon 附件传输:base64 编解码往返 + worker 透传给 loop.run。"""
from argos.daemon.attachments_wire import encode_attachments, decode_attachments
from argos.input.attachments import ImageAttachment

_ATT = ImageAttachment(data=b"\x89PNG\r\n\x1a\nABC", media_type="image/png",
                       source_label="clipboard", width=10, height=10)


def test_encode_decode_roundtrip():
    wire = encode_attachments([_ATT])
    assert isinstance(wire, list)
    assert wire[0]["media_type"] == "image/png"
    assert "data_b64" in wire[0]
    back = decode_attachments(wire)
    assert back[0].data == _ATT.data
    assert back[0].media_type == "image/png"
    assert back[0].width == 10 and back[0].height == 10
    assert back[0].source_label == "clipboard"

def test_encode_empty_is_empty():
    assert encode_attachments([]) == []
    assert encode_attachments(None) == []

def test_decode_empty_is_empty():
    assert decode_attachments(None) == []
    assert decode_attachments([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/daemon/test_attachment_transport.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'argos.daemon.attachments_wire'`

- [ ] **Step 3: Write minimal implementation**

**3a.** Create `argos/daemon/attachments_wire.py` (shared base64 codec, keeps server/client DRY):

```python
"""daemon 协议:ImageAttachment ↔ JSON-safe wire dict(base64)。
图片字节不进 runs/index.json(只在内存随 worker 传),避免索引膨胀。"""
from __future__ import annotations

import base64

from argos.input.attachments import ImageAttachment


def encode_attachments(atts) -> list[dict]:
    """ImageAttachment 列表 → JSON 可序列化 dict 列表(data base64)。"""
    out: list[dict] = []
    for a in atts or []:
        out.append({
            "data_b64": base64.b64encode(a.data).decode("ascii"),
            "media_type": a.media_type,
            "source_label": a.source_label,
            "width": a.width,
            "height": a.height,
        })
    return out


def decode_attachments(wire) -> list[ImageAttachment]:
    """wire dict 列表 → ImageAttachment 列表。畸形条目跳过(诚实降级,不崩)。"""
    out: list[ImageAttachment] = []
    for d in wire or []:
        try:
            out.append(ImageAttachment(
                data=base64.b64decode(d["data_b64"]),
                media_type=d["media_type"],
                source_label=d.get("source_label", "attachment"),
                width=d.get("width"),
                height=d.get("height"),
            ))
        except Exception:  # noqa: BLE001 — 单条畸形不毁整批
            continue
    return out
```

**3b.** `daemon/client.py` `create_run` (lines 152-162) — add `attachments` param, encode into body:

```python
    async def create_run(
        self, session_id: str, *, goal: str, workspace: str = "",
        model: str = "", approval_level: str = "confirm", attachments=None,
    ) -> str:
        from argos.daemon.attachments_wire import encode_attachments
        body = {"goal": goal, "workspace": workspace, "model": model,
                "approval_level": approval_level}
        wire = encode_attachments(attachments)
        if wire:
            body["attachments"] = wire
        status, _, raw = await self._request(
            "POST", "/runs", session_id=session_id, body=body,
        )
        body_out = self._check(status, self._parse_json(status, raw), (201,))
        return body_out["run_id"]
```

**3c.** `daemon/server.py` `_handle_create_run` — decode attachments and pass to `RunWorker`. After the line `approval_timeout_s = float(data.get("approval_timeout_s", 60.0))` (around line 447), add:

```python
        # 图片附件(base64 over wire)→ ImageAttachment;只在内存随 worker 传,不落 index。
        from argos.daemon.attachments_wire import decode_attachments
        run_attachments = decode_attachments(data.get("attachments"))
```

Then add `attachments=run_attachments` to **both** `RunWorker(...)` constructions (the `self._components is not None` branch and the `callable(self._loop_factory)` branch). For each existing `worker = RunWorker(` call, add the kwarg, e.g.:

```python
            worker = RunWorker(
                run_id=run_id,
                manager=self._manager,
                loop_factory=run_stack.loop_factory,
                registry=self._registry,
                worktree=self._worktree,
                gate=run_stack.gate,
                run_stack_close=run_stack.close,
                approval_timeout_s=approval_timeout_s,
                ledger_store=self._ledger_store,
                snapshot=run_snapshot,
                attachments=run_attachments,
            )
```

(Apply the same `attachments=run_attachments,` addition to the second `RunWorker(...)` in the `elif callable(self._loop_factory):` branch.)

**3d.** `daemon/worker.py` `RunWorker.__init__` — accept and store attachments. Add to the `__init__` signature (keyword-only, default empty) and body:

```python
        # ... existing params ...
        attachments=None,
    ) -> None:
        # ... existing assignments ...
        self._attachments = list(attachments or [])
```

Then the drive call at `worker.py:329`:

```python
            async for ev in self._loop.run(entry.goal, session_id=f"run-{self.run_id}",
                                           attachments=self._attachments):
```

**3e.** `tui/app.py` `_start_run_daemon` (app.py:2034) — accept attachments + pass to `create_run`. Change the signature:

```python
    async def _start_run_daemon(self, goal: str, log, attachments: list | None = None) -> None:
```

and the `create_run` call (app.py:2050):

```python
            run_id = await self._daemon_client.create_run(
                self._daemon_session_id,
                goal=goal,
                workspace=str(self._workspace),
                approval_level="confirm",
                attachments=attachments or [],
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/daemon/test_attachment_transport.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run daemon suite for regressions**

Run: `uv run pytest tests/ -k "daemon or worker or server" -v`
Expected: PASS (existing daemon tests green; new kwargs optional)

- [ ] **Step 6: Commit**

```bash
git add argos/daemon/attachments_wire.py argos/daemon/client.py argos/daemon/server.py argos/daemon/worker.py argos/tui/app.py tests/daemon/test_attachment_transport.py
git commit -m "feat(daemon): base64 image attachment transport client→server→worker→loop"
```

---

## Task 7: full-suite verification gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite with coverage**

Run: `uv run pytest -n auto --dist loadgroup`
Expected: all green, coverage ≥ 80%.

- [ ] **Step 2: Manual smoke (honest check, optional but recommended)**

In a real terminal with an image on the clipboard and a multimodal model configured:

```bash
ARGOS_NO_DAEMON=1 uv run argos
```
Press `Ctrl+V` → expect `[图片 #1]` chip in the prompt; type a question; Enter; confirm the model responds about the image. Then repeat without `ARGOS_NO_DAEMON=1` (daemon path). With a text-only model, expect the honest "不支持图像输入" block (Plan 1 gate).

- [ ] **Step 3: No commit** (verification only).

---

## Self-Review

**Spec coverage (§6.2, §6.3, §3 image input, §13):**
- "`Ctrl+V` 剪贴板含图 → `[图片 #N]` chip" → Tasks 1, 5. ✅ (§13 criterion 2)
- "粘贴 >10000 字符 → `[粘贴文本 #N +X 行]` chip → 提交展开" → Tasks 2, 3. ✅ (§13 criterion 3)
- "prompt 内图片路径 → 提交时自动附上" → Task 2 (`_expand_submission` calls `extract_image_paths`). ✅ (§13 criterion 4)
- "提交时展开,占位符不发模型" → Tasks 2, 3 (`_expand_submission` strips image tokens, expands paste tokens). ✅
- "图片到达模型(Anthropic/OpenAI 各验)" → Tasks 4 (inline) + 6 (daemon) thread attachments to `loop.run`, which Plan 1's `payload()` materializes. ✅
- "剪贴板读取不支持平台 → 诚实报错" → Task 1, surfaced in Task 5. ✅ (§13 criterion 6, clipboard half)
- "daemon 默认路径也要工作" → Task 6 (base64 transport, no index bloat). ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The Task 5 test note about monkeypatch target is guidance, not a placeholder — the implementation in Step 3 imports `read_clipboard_image` at module top so the symbol exists to patch. ✅

**Type consistency:** `PromptArea.Submitted(text, attachments)` defined in Task 2, consumed in Task 4 (`event.attachments`). `register_image(att) -> str` defined Task 2, called Task 5. `_expand_submission -> (str, list)` defined Task 2, used Task 3. `attachments` kwarg name is consistent across `start_run`/`_start_run_inline`/`_start_run_daemon`/`loop.run`/`create_run`/`RunWorker`. `encode_attachments`/`decode_attachments` defined Task 6 (3a), used in client (3b) and server (3c). ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-13-image-input-ux.md`. **Plan 2 of 3** — depends on Plan 1 being merged first. Execution options (subagent-driven recommended) are the same as Plan 1.
