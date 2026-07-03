"""Internal documentation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from argos.i18n import t as _t


ActionKind = Literal[
    "screenshot",
    "click",
    "double_click",
    "type_text",
    "key",
    "scroll",
    "open_app",
]

TEXT_MAX_LEN = 2000
_APP_NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]+$")


@dataclass(frozen=True, slots=True)
class ComputerAction:
    """Internal documentation."""
    kind: ActionKind
    x: int | None = None
    y: int | None = None
    text: str | None = None
    app: str | None = None

    def __post_init__(self) -> None:
        for name, val in (("x", self.x), ("y", self.y)):
            if val is not None and val < 0:
                raise ValueError(_t("perception.actions.coord_negative", name=name, val=val))

        if self.text is not None and len(self.text) > TEXT_MAX_LEN:
            raise ValueError(
                _t("perception.actions.text_too_long",
                   max_len=TEXT_MAX_LEN, actual=len(self.text))
            )

        if self.app is not None and self.app != "" and not _APP_NAME_RE.match(self.app):
            raise ValueError(
                _t("perception.actions.app_name_invalid", app=self.app)
            )

        if self.kind in ("click", "double_click"):
            if self.x is None or self.y is None:
                raise ValueError(
                    _t("perception.actions.click_needs_xy", kind=self.kind)
                )
        elif self.kind in ("type_text", "key"):
            if not self.text:
                raise ValueError(
                    _t("perception.actions.text_needs_nonempty", kind=self.kind)
                )
        elif self.kind == "scroll":
            if self.x is None or self.y is None:
                raise ValueError(_t("perception.actions.scroll_needs_xy"))
            if not self.text:
                raise ValueError(_t("perception.actions.scroll_needs_text"))
        elif self.kind == "open_app":
            if not self.app:
                raise ValueError(_t("perception.actions.open_app_needs_name"))
