# argos_agent/tui/theme.py
"""「黑曜石之眼」设计系统 — 完整 token 体系（v3）。

背景三层纵深 + 墨色五阶阶梯 + 金系三档(chrome 强调) + 诚实语义色(铁律)。
注册名保持 'argos-night' 不变——避免用户配置破损(spec §2.8 契约)。

色彩铁律：
- 禁止硬编码 hex 于其他文件；CSS 一律用 $token 名。
- 金橙分家：$eye* 金系只给 chrome/注意力；$unverif 橙系只给"真相不确定"。
- E4 防火墙：$pass-weak 弱通过绝不等于 $pass 强通过。
- $text-muted 向后兼容映射到 $ink-dim，供未迁移旧 CSS 引用。
"""
from __future__ import annotations

from textual.theme import Theme

ARGOS_NIGHT = Theme(
    name="argos-night",           # 注册名不变——契约
    dark=True,
    # ── Textual 内置语义槽(映射到黑曜石底盘)──
    primary="#D9A85C",            # $eye:chrome 唯一强调
    secondary="#7AA2F7",          # $plan:plan mode 蓝
    accent="#D9A85C",             # = primary($eye)
    foreground="#C8CCDA",         # $ink:散文阅读层
    background="#0B0C10",         # $abyss:井底
    surface="#0E0F15",            # $well:第一深度(右栏/输入底)
    panel="#1B1D29",              # $raise:浮起面(代码/diff/审批底)
    success="#9ECE6A",            # $pass:verdict passed
    warning="#FF9E64",            # $unverif:裁决①更橙更饱和
    error="#F7768E",              # $fail:verdict failed
    boost="#23263A",              # $raise-2:二级浮起
    variables={
        # ── 背景层级(三层纵深 + 两个边界 + 两档发丝)──
        "abyss":        "#0B0C10",   # 井底:终端最外背景、StatusBar 地基
        "well":         "#0E0F15",   # 第一深度:TopBar/右栏底/输入区底
        "stream":       "#13141B",   # 流面(主):Transcript 散文背景
        "raise":        "#1B1D29",   # 浮起:代码块/diff/审批卡背景
        "raise-2":      "#23263A",   # 二级浮起:审批卡选中/slash 高亮
        "hairline":     "#23252E",   # 发丝分隔线(几乎不可见)
        "hairline-lit": "#2E3142",   # 点亮发丝:活动块左缘/focus 边界

        # ── 墨色 5 阶亮度阶梯(纵深引擎)──
        "ink-bright": "#ECEEF5",   # bold:assistant 强调/verdict/当前阶段
        "ink":        "#C8CCDA",   # normal:散文正文(默认阅读层)
        "ink-dim":    "#7E869C",   # normal:次要/元信息/工具名/step 号
        "ink-faint":  "#525A73",   # normal:键提示/占位符/空态/计数
        "ink-ghost":  "#3A4055",   # normal:折叠提示/未激活树枝

        # ── 金系 3 档(chrome 强调)──
        "eye-soft": "#A8854A",     # 弱强调:非活动徽标/次级标记/idle 暗金眼
        "eye":      "#D9A85C",     # 主强调:logo 之眼/当前阶段/›▸/focus
        "eye-glow": "#F0C078",     # 高亮:呼吸光峰值/块光标背景/选中前缀

        # ── 语义色(诚实铁律)──
        "pass":         "#9ECE6A",  # verdict passed(强);唯一的绿
        "pass-weak":    "#73A857",  # self-verified 弱通过(E4);去饱和绿
        "fail":         "#F7768E",  # verdict failed;唯一的红
        "unverif":      "#FF9E64",  # verdict unverifiable;橙(永远三重冗余)
        "unverif-deep": "#9A6E2E",  # unverifiable 块左缘(暗一档)
        "cyan":         "#7DCFFF",  # 缓存命中 sparkline(冷色=省钱)

        # ── 模式徽标 ──
        "plan": "#7AA2F7",          # plan mode 蓝(plan ≠ act)

        # ── 块光标(输入块光标:深字 + 暖金底)──
        "block-cursor-foreground": "#0B0C10",   # $abyss 深字
        "block-cursor-background": "#F0C078",   # $eye-glow 暖金底

        # ── 滚动条 / focus(贴黑曜石)──
        "scrollbar":       "#1B1D29",   # = $raise
        "scrollbar-hover": "#23263A",   # = $raise-2

        # ── 边框辅助 ──
        "border": "#2E3142",            # = $hairline-lit

        # ── 向后兼容兜底(旧 CSS 仍引用 $text-muted)──
        # 映射到 $ink-dim；新 CSS 一律用新语义名，逐表迁移
        "text-muted": "#7E869C",        # = $ink-dim
    },
)
