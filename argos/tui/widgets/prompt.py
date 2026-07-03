from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static, TextArea

from argos.i18n import t as _t
from argos.input.attachments import ImageAttachment, extract_image_paths, load_from_path

_PASTE_THRESHOLD = 10000

_EYE        = "#D9A85C"
_INK_DIM    = "#7E869C"
_INK_FAINT  = "#6B7494"
_INK_BRIGHT = "#ECEEF5"
_RAISE_2    = "#23263A"


class PromptArea(TextArea):

    class Submitted(Message):

        def __init__(self, text: str, attachments: list | None = None) -> None:
            self.text = text
            self.attachments: list = list(attachments or [])
            super().__init__()

    DEFAULT_CSS = """
    PromptArea { height: auto; max-height: 8; background: $well; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(
            soft_wrap=True, show_line_numbers=False, tab_behavior="focus", compact=True, **kwargs
        )
        self._paste_store: dict[str, str] = {}
        self._image_store: dict[str, ImageAttachment] = {}
        self._paste_seq: int = 0
        self._image_seq: int = 0
        self._history_idx: int = -1
        self._draft: str = ""

    def _make_paste_token(self, text: str) -> str | None:
        if len(text) <= _PASTE_THRESHOLD:
            return None
        self._paste_seq += 1
        lines = text.count("\n")
        token = _t("tui.prompt.paste_token", n=self._paste_seq, lines=lines)
        self._paste_store[token] = text
        return token

    def register_image(self, att: ImageAttachment) -> str:
        self._image_seq += 1
        token = _t("tui.prompt.image_token", n=self._image_seq)
        self._image_store[token] = att
        return token

    def _expand_submission(self, text: str) -> tuple[str, list[ImageAttachment]]:
        out_text = text
        for token, full in self._paste_store.items():
            out_text = out_text.replace(token, full)
        attachments: list[ImageAttachment] = []
        for token, att in self._image_store.items():
            if token in out_text:
                attachments.append(att)
                out_text = out_text.replace(token, "")
        for path in extract_image_paths(out_text):
            try:
                attachments.append(load_from_path(path))
            except (ValueError, OSError):
                pass
        return out_text.strip(), attachments

    def _get_app_history(self) -> list[str]:
        try:
            return list(self.app._input_history)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return []

    def _navigate_history(self, direction: str, history: list[str]) -> None:
        n = len(history)
        if n == 0:
            return
        if direction == "up":
            if self._history_idx == -1:
                self._draft = self.text
                self._history_idx = n - 1
            elif self._history_idx > 0:
                self._history_idx -= 1
            self._refill(history[self._history_idx])
        else:  # down
            if self._history_idx == -1:
                return
            if self._history_idx < n - 1:
                self._history_idx += 1
                self._refill(history[self._history_idx])
            else:
                self._history_idx = -1
                self._refill(self._draft)
                self._draft = ""

    def _refill(self, text: str) -> None:
        self.load_text(text)
        self.move_cursor(self.document.end)

    def reset_history_nav(self) -> None:
        self._history_idx = -1
        self._draft = ""

    def _menu(self) -> "SlashMenu | None":
        try:
            return self.app.query_one("#slash-menu", SlashMenu)
        except Exception:  # noqa: BLE001
            return None

    async def _on_paste(self, event: events.Paste) -> None:
        event.stop()
        event.prevent_default()
        token = self._make_paste_token(event.text)
        self.insert(token if token is not None else event.text)

    async def _on_key(self, event: events.Key) -> None:
        menu = self._menu()
        menu_active = menu is not None and menu.display and menu.has_matches
        if event.key in ("up", "down"):
            if menu_active:
                event.stop()
                event.prevent_default()
                menu.move(-1 if event.key == "up" else 1)
                return
            history = self._get_app_history()
            if history:
                event.stop()
                event.prevent_default()
                self._navigate_history(event.key, history)
                return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            text = self.text
            if text.endswith("\\"):
                self.load_text(text[:-1] + "\n")
                self.move_cursor(self.document.end)
                return
            if menu_active:
                sel = menu.selected()
                if sel is not None:
                    self.post_message(self.Submitted(f"/{sel}"))
                    self.reset_history_nav()
                    self.clear()
                    return
            stripped = text.strip()
            if stripped:
                expanded, attachments = self._expand_submission(stripped)
                if expanded or attachments:
                    self.post_message(self.Submitted(expanded, attachments))
                    self._paste_store.clear()
                    self._image_store.clear()
                    self.reset_history_nav()
                    self.clear()
            return
        if event.key == "tab":
            if menu_active:
                sel = menu.selected()
                if sel is not None:
                    event.stop()
                    event.prevent_default()
                    self.load_text(f"/{sel} ")
                    self.move_cursor(self.document.end)
                    return
        await super()._on_key(event)


class SlashMenu(Static):

    DEFAULT_CSS = """
    SlashMenu {
        display: none;
        height: auto; max-height: 10;
        margin: 0 2; padding: 0 1;
        background: $raise; border: round $hairline-lit;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self._matches: list[tuple[str, str]] = []
        self._cursor = 0

    @property
    def has_matches(self) -> bool:
        return bool(self._matches)

    def selected(self) -> str | None:
        if not self._matches:
            return None
        return self._matches[self._cursor][0]

    def move(self, delta: int) -> None:
        if not self._matches:
            return
        self._cursor = (self._cursor + delta) % len(self._matches)
        self._render_items()

    def show_matches(self, matches: list[tuple[str, str]]) -> None:
        if matches != self._matches:
            self._cursor = 0
        self._matches = list(matches)
        if not self._matches:
            self.display = False
            return
        self._render_items()
        self.display = True

    def _render_items(self) -> None:
        t = Text()
        for i, (name, desc) in enumerate(self._matches):
            cur = i == self._cursor
            if cur:
                t.append("▸ ", style=Style(color=_EYE, bgcolor=_RAISE_2, bold=True))
                t.append(f"/{name:<16}", style=Style(color=_INK_BRIGHT, bgcolor=_RAISE_2, bold=True))
                t.append(f" {desc}", style=Style(color=_INK_DIM, bgcolor=_RAISE_2))
            else:
                t.append("  ", style=None)
                t.append(f"/{name:<16}", style=_INK_DIM)
                t.append(f" {desc}", style=_INK_DIM)
            t.append("\n")
        t.append(_t("tui.slash_menu.nav_hint"), style=_INK_FAINT)
        self.update(t)

    def hide(self) -> None:
        self.display = False
