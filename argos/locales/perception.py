"""Perception cluster locale — user-facing strings from executor and actions.

key namespace: perception.*
"""
from __future__ import annotations

EN: dict[str, str] = {
    # executor: computer-use capability not enabled
    "perception.executor.disabled": (
        "OS-level computer use is not enabled."
        " To use screenshot/click and other system control features,"
        " set the environment variable ARGOS_COMPUTER_USE=1 and restart argos."
        " Note: this capability controls the global screen/mouse; it cannot be"
        " isolated by the Seatbelt sandbox."
        " Ensure you have granted Accessibility permission to your terminal in System Settings before enabling."
    ),
    # executor: accessibility permission denied
    "perception.executor.access_denied": (
        "The system denied the Accessibility access request."
        " Go to System Settings → Privacy & Security → Accessibility"
        " and add your terminal (Terminal / iTerm / Warp / etc.) to the allow list, then retry."
        " Screenshot does not require this permission."
    ),
    # executor: unknown action kind
    "perception.executor.unknown_kind": (
        "Unknown action kind={kind!r}, rejected."
    ),
    # executor._run: timeout
    "perception.executor.timeout": (
        "Timeout: command {cmd!r} did not complete within {t}s"
    ),
    # executor._run: command not found
    "perception.executor.cmd_not_found": (
        "Command not found: {cmd!r} (check macOS environment)"
    ),
    # executor._screenshot: failure
    "perception.executor.screenshot_failed": (
        "Screenshot failed (exit {rc}): {err}"
    ),
    # executor._screenshot: unknown error fallback
    "perception.executor.unknown_error": "unknown error",
    # executor._screenshot: success
    "perception.executor.screenshot_saved": (
        "Screenshot saved to {path}"
    ),
    # executor._click: failure (single click)
    "perception.executor.click_failed": (
        "Click failed (exit {rc}): {err}"
    ),
    # executor._click: failure (double click)
    "perception.executor.double_click_failed": (
        "Double-click failed (exit {rc}): {err}"
    ),
    # executor._click: success (single click)
    "perception.executor.click_ok": (
        "Click ({lx}, {ly}) succeeded"
    ),
    # executor._click: success (double click)
    "perception.executor.double_click_ok": (
        "Double-click ({lx}, {ly}) succeeded"
    ),
    # executor._type_text: failure
    "perception.executor.type_text_failed": (
        "Type-text failed (exit {rc}): {err}"
    ),
    # executor._type_text: success
    "perception.executor.type_text_ok": (
        "Type-text succeeded: {preview!r}"
    ),
    # executor._key: failure
    "perception.executor.key_failed": (
        "Hotkey failed (exit {rc}): {err}"
    ),
    # executor._key: success
    "perception.executor.key_ok": (
        "Hotkey {combo!r} succeeded"
    ),
    # executor._scroll: failure
    "perception.executor.scroll_failed": (
        "Scroll failed (exit {rc}): {err}"
    ),
    # executor._scroll: success
    "perception.executor.scroll_ok": (
        "Scroll ({lx}, {ly}) dy={dy} succeeded"
    ),
    # executor._open_app: failure
    "perception.executor.open_app_failed": (
        "Open app {app!r} failed (exit {rc}): {err}"
    ),
    # executor._open_app: no-permission fallback
    "perception.executor.open_app_no_permission": (
        "App does not exist or permission denied"
    ),
    # executor._open_app: success
    "perception.executor.open_app_ok": (
        "Launched app {app!r}"
    ),

    # actions: coordinate must be non-negative
    "perception.actions.coord_negative": (
        "ComputerAction.{name} must be >= 0, got {val!r}"
    ),
    # actions: text over max length
    "perception.actions.text_too_long": (
        "ComputerAction.text exceeds the limit of {max_len} characters"
        " (actual {actual} characters)"
    ),
    # actions: app name contains illegal characters
    "perception.actions.app_name_invalid": (
        "ComputerAction.app name {app!r} contains illegal characters"
        " (only A-Za-z0-9 space _ . - are allowed)"
    ),
    # actions: click/double_click requires x and y
    "perception.actions.click_needs_xy": (
        "kind={kind!r} requires x and y coordinates"
    ),
    # actions: type_text/key requires non-empty text
    "perception.actions.text_needs_nonempty": (
        "kind={kind!r} requires non-empty text"
    ),
    # actions: scroll requires x and y
    "perception.actions.scroll_needs_xy": (
        "kind='scroll' requires x and y coordinates"
    ),
    # actions: scroll requires text=str(dy)
    "perception.actions.scroll_needs_text": (
        "kind='scroll' requires text=str(dy) to specify the number of scroll lines"
    ),
    # actions: open_app requires non-empty app name
    "perception.actions.open_app_needs_name": (
        "kind='open_app' requires a non-empty app name"
    ),
}

ZH: dict[str, str] = {
    # executor: computer-use capability not enabled
    "perception.executor.disabled": (
        "OS 级 computer use 未启用。"
        "如需使用截图/点击等系统控制能力,请设置环境变量 ARGOS_COMPUTER_USE=1 后重启 argos。"
        "注意:此能力操控全局屏幕/鼠标资源,Seatbelt 沙箱无法隔离;"
        "启用前请确认已在系统设置中授予终端辅助功能权限。"
    ),
    # executor: accessibility permission denied
    "perception.executor.access_denied": (
        "系统拒绝了辅助功能访问请求。"
        "请前往「系统设置 → 隐私与安全性 → 辅助功能」,将终端(Terminal / iTerm / Warp 等)"
        "加入允许列表后重试。截图功能不受此限制。"
    ),
    # executor: unknown action kind
    "perception.executor.unknown_kind": (
        "未知动作 kind={kind!r},拒绝执行。"
    ),
    # executor._run: timeout
    "perception.executor.timeout": (
        "超时:命令 {cmd!r} 在 {t}s 内未完成"
    ),
    # executor._run: command not found
    "perception.executor.cmd_not_found": (
        "命令不存在: {cmd!r}(请检查 macOS 环境)"
    ),
    # executor._screenshot: failure
    "perception.executor.screenshot_failed": (
        "截图失败(exit {rc}): {err}"
    ),
    # executor._screenshot: unknown error fallback
    "perception.executor.unknown_error": "未知错误",
    # executor._screenshot: success
    "perception.executor.screenshot_saved": (
        "截图已保存至 {path}"
    ),
    # executor._click: failure (single click)
    "perception.executor.click_failed": (
        "点击失败(exit {rc}): {err}"
    ),
    # executor._click: failure (double click)
    "perception.executor.double_click_failed": (
        "双击失败(exit {rc}): {err}"
    ),
    # executor._click: success (single click)
    "perception.executor.click_ok": (
        "点击 ({lx}, {ly}) 成功"
    ),
    # executor._click: success (double click)
    "perception.executor.double_click_ok": (
        "双击 ({lx}, {ly}) 成功"
    ),
    # executor._type_text: failure
    "perception.executor.type_text_failed": (
        "键入文本失败(exit {rc}): {err}"
    ),
    # executor._type_text: success
    "perception.executor.type_text_ok": (
        "键入文本成功: {preview!r}"
    ),
    # executor._key: failure
    "perception.executor.key_failed": (
        "快捷键失败(exit {rc}): {err}"
    ),
    # executor._key: success
    "perception.executor.key_ok": (
        "快捷键 {combo!r} 成功"
    ),
    # executor._scroll: failure
    "perception.executor.scroll_failed": (
        "滚动失败(exit {rc}): {err}"
    ),
    # executor._scroll: success
    "perception.executor.scroll_ok": (
        "滚动 ({lx}, {ly}) dy={dy} 成功"
    ),
    # executor._open_app: failure
    "perception.executor.open_app_failed": (
        "打开应用 {app!r} 失败(exit {rc}): {err}"
    ),
    # executor._open_app: no-permission fallback
    "perception.executor.open_app_no_permission": (
        "应用不存在或无权限"
    ),
    # executor._open_app: success
    "perception.executor.open_app_ok": (
        "已启动应用 {app!r}"
    ),

    # actions: coordinate must be non-negative
    "perception.actions.coord_negative": (
        "ComputerAction.{name} 必须 >= 0,得到 {val!r}"
    ),
    # actions: text over max length
    "perception.actions.text_too_long": (
        "ComputerAction.text 超过上限 {max_len} 字符"
        "(实际 {actual} 字符)"
    ),
    # actions: app name contains illegal characters
    "perception.actions.app_name_invalid": (
        "ComputerAction.app 名 {app!r} 含非法字符"
        "(仅允许 A-Za-z0-9 空格 _ . -)"
    ),
    # actions: click/double_click requires x and y
    "perception.actions.click_needs_xy": (
        "kind={kind!r} 需要 x 和 y 坐标"
    ),
    # actions: type_text/key requires non-empty text
    "perception.actions.text_needs_nonempty": (
        "kind={kind!r} 需要非空 text"
    ),
    # actions: scroll requires x and y
    "perception.actions.scroll_needs_xy": (
        "kind='scroll' 需要 x 和 y 坐标"
    ),
    # actions: scroll requires text=str(dy)
    "perception.actions.scroll_needs_text": (
        "kind='scroll' 需要 text=str(dy) 表示滚动行数"
    ),
    # actions: open_app requires non-empty app name
    "perception.actions.open_app_needs_name": (
        "kind='open_app' 需要非空 app 名称"
    ),
}
