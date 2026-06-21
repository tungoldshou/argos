"""语言目录包 —— 每个模块暴露 EN / ZH 两个 dict(key -> 模板串)。

约定:
- key 用点分命名空间,按 cluster 前缀避免撞车:cli.* / setup.* / tui.* / widget.* /
  verdict.* / trust.* / ledger.* / hardconfirm.* / loop.* / sandbox.* / daemon.* / tools.* / common.*。
- ZH 必须与重构前的**原始中文串逐字一致**,这样 `ARGOS_LANG=zh` 下旧测试断言不破。
- EN 是面向英文漏斗用户的默认文案(README/品牌/系统提示词都是英文)。

CATALOG_MODULES:显式登记所有 catalog 子模块名。i18n._catalog 优先用此清单(冻结安全 ——
PyInstaller 打包后 pkgutil 发现不到子模块),再用 pkgutil 兜底。新增 catalog 须把名字加进来。
"""

CATALOG_MODULES: list[str] = [
    "common",   # 跨 cluster 通用词
    "cli",      # __main__ argparse / headless / setup 向导
    "tui_app",  # TUI app shell / commands / prompt / status_bar
    "widgets",  # 诚实 widget(verdict/trust/ledger/hardconfirm/activity/dream/orders/routing)
    "core",     # loop / harness 用户可见消息
    "sandbox",  # broker / executor / linux 沙箱消息
    "daemon",   # argosd stop/status/restart 输出
    "tools",    # tools/* + plan_mode 工具结果串(Wave 2c)
    "permissions",  # trust_dial 模式描述 + approval 审批提示(Wave 2d)
    "misc",     # config 错误 / 剪贴板图片 / web+browser 工具错误(Wave 2d)
]
