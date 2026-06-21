"""config / input / web / browser 用户可见文案 (Wave 2d — MISC lane).

key 命名空间: config.* / input.* / web.* / browser.*
ZH 值 = 重构前的原始串 verbatim (一字不差)。
EN 值 = 语义对等的自然英文；以 "Error:" 开头对应 ZH "错误:" 开头。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── argos/config.py ───────────────────────────────────────────────────────

    # _validate_profile
    "config.profile.missing_field": "profile '{name}' is missing required field '{field}'",
    "config.profile.invalid_protocol": (
        "profile '{name}' has protocol='{protocol}' which is invalid;"
        " must be one of {valid}"
    ),
    "config.profile.non_integer_tokens": (
        "profile '{name}' max_tokens/context_window must be integers: {exc}"
    ),
    "config.profile.non_positive_tokens": (
        "profile '{name}' max_tokens/context_window must be positive integers"
        " (got {mt}/{cw})"
    ),

    # load_config
    "config.load.no_config_file": "No config file at {path}",
    "config.load.json_parse_error": "config.json parse error: {exc}",
    "config.load.active_not_in_models": (
        "active='{active}' is not in models (or models is empty)"
    ),

    # tier_for
    "config.tier_for.not_found": (
        "profile '{name}' does not exist (available: {available})"
    ),
    "config.tier_for.no_config": (
        "No config.json; only the default profile '{default}' is available"
        " (run 'argos setup' first)"
    ),

    # set_active
    "config.set_active.no_config": (
        "No config.json; cannot switch profile (run 'argos setup' first)"
    ),
    "config.set_active.not_found": "profile '{name}' does not exist",

    # ── argos/input/clipboard_image.py ────────────────────────────────────────

    "input.clipboard.need_pngpaste": (
        "Reading clipboard images requires pngpaste:"
        " run `brew install pngpaste`."
    ),
    "input.clipboard.no_image_macos": (
        "No image in clipboard (or read failed)."
    ),
    "input.clipboard.need_xclip": (
        "Reading clipboard images requires xclip:"
        " install it with your package manager (e.g. `apt install xclip`)."
    ),
    "input.clipboard.no_image_linux": (
        "No image in clipboard (or read failed)."
    ),
    "input.clipboard.unsupported_platform": (
        "Clipboard image reading is not supported on platform {platform}."
    ),
    "input.clipboard.bad_format": (
        "Clipboard content is not a supported image format."
    ),

    # ── argos/web.py ──────────────────────────────────────────────────────────

    "web.ddgs_unavailable": (
        "ddgs package is not available for free search;"
        " configure TAVILY_API_KEY to upgrade."
    ),
    "web.search_timeout": (
        "Web search timed out (>{timeout}s,"
        " tried DuckDuckGo/Bing/Brave/Google and other free engines — no response);"
        " retry later, or configure TAVILY_API_KEY to upgrade."
    ),
    "web.search_all_failed": (
        "Web search unavailable (no free engine returned results: {error});"
        " retry later, or configure TAVILY_API_KEY to upgrade."
    ),
    "web.tavily_failed": "Tavily search failed: {exc}",
    "web.ssrf_blocked": "SSRF protection: access to private/reserved address {host!r} denied",
    "web.redirect_limit": "Fetch failed: redirect limit exceeded (>5)",
    "web.fetch_failed": "Fetch failed: {exc}",

    # ── argos/browser.py ──────────────────────────────────────────────────────

    "browser.playwright_not_installed": (
        "Error: browser unavailable (playwright not installed: {exc})."
    ),
    "browser.launch_failed": (
        "Error: browser failed to launch"
        " (chromium may not be installed, or no display is available for headed mode: {exc})."
        " Run `playwright install chromium`;"
        " for headless environments set ARGOS_BROWSER_HEADLESS=1."
    ),
    "browser.thread_crashed": (
        "Error: browser thread crashed: {exc_type}: {exc}"
    ),
    "browser.navigate_ok": (
        "Opened {url} (title: {title!r})."
        " Use browser_snapshot() to inspect the page."
    ),
    "browser.snapshot_truncated": "\n…(body is {total} chars, truncated to {mc})",
    "browser.snapshot_header": "[Page] {title}\n[URL] {url}\n\n{body}",
    "browser.click_ok": "Clicked {selector!r}.",
    "browser.type_ok": "Typed {chars} char(s) into {selector!r}.",
    "browser.screenshot_ok": "Screenshot saved to {path}.",
    "browser.unknown_action": "Error: unknown browser action {op!r}.",
    "browser.action_failed": "Error: browser action {op} failed: {exc_type}: {exc}",
}

ZH: dict[str, str] = {
    # ── argos/config.py ───────────────────────────────────────────────────────

    "config.profile.missing_field": "profile '{name}' 缺必填字段 '{field}'",
    "config.profile.invalid_protocol": (
        "profile '{name}' 的 protocol='{protocol}' 非法,只能是 {valid}"
    ),
    "config.profile.non_integer_tokens": (
        "profile '{name}' 的 max_tokens/context_window 必须是整数:{exc}"
    ),
    "config.profile.non_positive_tokens": (
        "profile '{name}' 的 max_tokens/context_window 必须是正整数(得 {mt}/{cw})"
    ),

    "config.load.no_config_file": "无 {path}",
    "config.load.json_parse_error": "config.json 解析失败:{exc}",
    "config.load.active_not_in_models": (
        "active='{active}' 不在 models 中(或 models 为空)"
    ),

    "config.tier_for.not_found": (
        "profile '{name}' 不存在(可用:{available})"
    ),
    "config.tier_for.no_config": (
        "无 config.json,仅有默认 profile '{default}'(请先 argos setup)"
    ),

    "config.set_active.no_config": "无 config.json,无法切换(请先 argos setup)",
    "config.set_active.not_found": "profile '{name}' 不存在",

    # ── argos/input/clipboard_image.py ────────────────────────────────────────

    "input.clipboard.need_pngpaste": (
        "读取剪贴板图片需要 pngpaste:请运行 `brew install pngpaste`。"
    ),
    "input.clipboard.no_image_macos": "剪贴板里没有图片(或读取失败)。",
    "input.clipboard.need_xclip": (
        "读取剪贴板图片需要 xclip:请用包管理器安装(如 `apt install xclip`)。"
    ),
    "input.clipboard.no_image_linux": "剪贴板里没有图片(或读取失败)。",
    "input.clipboard.unsupported_platform": (
        "当前平台 {platform} 暂不支持读取剪贴板图片。"
    ),
    "input.clipboard.bad_format": "剪贴板内容不是受支持的图片格式。",

    # ── argos/web.py ──────────────────────────────────────────────────────────

    "web.ddgs_unavailable": (
        "ddgs 包不可用,无法免费搜索;可配置 TAVILY_API_KEY 升级。"
    ),
    "web.search_timeout": (
        "联网搜索超时(>{timeout}s,已并发试 DuckDuckGo/Bing/Brave/"
        "Google 等免费引擎均无响应);稍后重试,或配置 TAVILY_API_KEY 升级。"
    ),
    "web.search_all_failed": (
        "联网搜索暂不可用(免费引擎均未返回:{error});"
        "稍后重试,或配置 TAVILY_API_KEY 升级。"
    ),
    "web.tavily_failed": "Tavily 搜索失败:{exc}",
    "web.ssrf_blocked": "SSRF 防护:拒绝访问私网/保留地址 {host!r}",
    "web.redirect_limit": "取页失败:redirect 跳数超限(>5)",
    "web.fetch_failed": "取页失败:{exc}",

    # ── argos/browser.py ──────────────────────────────────────────────────────

    "browser.playwright_not_installed": (
        "错误:浏览器不可用(playwright 未安装:{exc})。"
    ),
    "browser.launch_failed": (
        "错误:浏览器启动失败(可能未安装 chromium,或当前环境无显示器无法开有头窗口:{exc})。"
        "请运行 `playwright install chromium`;无显示器环境可设 ARGOS_BROWSER_HEADLESS=1。"
    ),
    "browser.thread_crashed": "错误:浏览器线程异常:{exc_type}: {exc}",
    "browser.navigate_ok": (
        "已打开 {url}(标题:{title!r})。用 browser_snapshot() 看页面内容。"
    ),
    "browser.snapshot_truncated": "\n…(正文共 {total} 字符,已截断前 {mc})",
    "browser.snapshot_header": "[页面] {title}\n[URL] {url}\n\n{body}",
    "browser.click_ok": "已点击 {selector!r}。",
    "browser.type_ok": "已在 {selector!r} 填入文本({chars} 字符)。",
    "browser.screenshot_ok": "已截图保存到 {path}。",
    "browser.unknown_action": "错误:未知浏览器动作 {op!r}。",
    "browser.action_failed": "错误:浏览器动作 {op} 失败:{exc_type}: {exc}",
}
