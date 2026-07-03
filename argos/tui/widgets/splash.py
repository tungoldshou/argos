from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from argos.i18n import t

try:
    from argos import __version__ as _VERSION
except Exception:  # noqa: BLE001
    _VERSION = "0.x"

_COL_EYE_GLOW = "#F0C078"
_COL_INK_DIM  = "#7E869C"
_COL_INK_FAINT = "#6B7494"
_COL_PASS     = "#9ECE6A"
_COL_UNVERIF  = "#FF9E64"

_LOGO = (
    "\n"
    "              ▄▀█ █▀█ █▀▀ █▀█ █▀\n"
    "              █▀█ █▀▄ █▄█ █▄█ ▄█\n"
)

_EYE_STAGES: dict[str, str] = {
    "init":  "◌",
    "scan":  "◔",
    "half":  "◓",
    "focus": "◉",
    "open":  "◉",
}

_PLAN_PREFIX = "plan · "


def _eye_for_state(*, live: bool, has_key: bool, _eye_stage: str) -> str:
    if not has_key:
        return "◌"
    return _EYE_STAGES.get(_eye_stage, "◌")


def _compose_text(*, model_label: str, live: bool, plan_mode: bool,
                   has_key: bool = True, eye_stage: str = "init") -> str:
    eye = _eye_for_state(live=live, has_key=has_key, _eye_stage=eye_stage)

    if not has_key:
        badge_markup = f"[{_COL_INK_DIM}]{t('widget.splash_badge_no_key')}[/{_COL_INK_DIM}]"
    else:
        badge_markup = f"[{_COL_PASS}]{t('widget.splash_badge_live')}[/{_COL_PASS}]"

    prefix = _plan_prefix_str(plan_mode)
    return prefix + (
        _LOGO
        + "\n                   ARGOS\n"
        + f"\n                    [{_COL_EYE_GLOW}]{eye}[/{_COL_EYE_GLOW}]\n"
        + f"\n[{_COL_INK_DIM}]{t('widget.splash_subtitle', version=_VERSION)}[/{_COL_INK_DIM}]"
        + badge_markup
        + f"\n[{_COL_INK_FAINT}]{t('widget.splash_hint')}[/{_COL_INK_FAINT}]"
    )


def _plan_prefix_str(plan_mode: bool) -> str:
    return _PLAN_PREFIX if plan_mode else ""


class StartupSplash(Static):
    DEFAULT_CSS = """
    StartupSplash { content-align: center middle; text-align: center; height: auto; padding: 1 0; background: $stream; }
    """
    plan_mode: reactive[bool] = reactive(False)

    def __init__(self, *, model_label: str, tier: str, live: bool,
                 has_key: bool = True) -> None:
        self._model_label = model_label
        self._tier = tier
        self._live = live
        self._has_key = has_key
        self._eye_stage = "init"
        self._text = _compose_text(
            model_label=model_label, live=live, plan_mode=False,
            has_key=has_key, eye_stage=self._eye_stage,
        )
        super().__init__(self._text, markup=True)

    def advance_eye(self, stage: str) -> None:
        if not self._has_key:
            return
        self._eye_stage = stage
        self._refresh()

    def set_plan_mode(self, active: bool) -> None:
        self.plan_mode = bool(active)

    def set_bad_config(self, reason: str, *, source: str | None = None) -> None:
        self._bad_config = reason
        self._bad_config_source = source
        self._refresh()

    def _refresh(self) -> None:  # type: ignore[no-redef]
        text = _compose_text(
            model_label=self._model_label, live=self._live,
            plan_mode=self.plan_mode, has_key=self._has_key,
            eye_stage=self._eye_stage,
        )
        if getattr(self, "_bad_config", None):
            reason = str(self._bad_config)
            source = getattr(self, "_bad_config_source", None)
            if source == "config":
                prefix = t("widget.splash_bad_config_config")
                text += f"\n       ⚠︎ {prefix}" + t("widget.splash_bad_config_error_suffix", reason=reason)
            elif "permissions" in reason:
                prefix = t("widget.splash_bad_config_permissions")
                text += f"\n       ⚠︎ {prefix}" + t("widget.splash_bad_config_suffix", reason=reason)
            elif "LSP" in reason:
                prefix = t("widget.splash_bad_config_lsp")
                text += f"\n       ⚠︎ {prefix}" + t("widget.splash_bad_config_suffix", reason=reason)
            else:
                prefix = t("widget.splash_bad_config_hooks")
                text += f"\n       ⚠︎ {prefix}" + t("widget.splash_bad_config_suffix", reason=reason)
        self._text = text
        self.update(self._text)
        self.set_class(self.plan_mode, "-plan-mode")

    def watch_plan_mode(self, value: bool) -> None:  # noqa: ARG002
        self._refresh()

    @property
    def renderable_text(self) -> str:
        return self._text
