# Argos TUI v3 设计系统定稿 ·「黑曜石之眼」(Obsidian Eye)

> 编译自:总设计师裁决(最高权威) + 黑曜石设计书(视觉底盘) + 瞭望塔(右栏仪表) + 百眼(眼睛母题)。
> 2026-06-11。本文是**唯一施工真相源**;与任何素材冲突时,以本文为准(本文已吸收裁决 delta)。
> 这是一份可直接施工的设计系统:每个表面的渲染样例精确到字符与 token 名;凡"决定"皆为决定,无"可以考虑"。

---

## 0. 目录

1. 设计哲学
2. Design Tokens 全表 + theme.py 完整新值
3. 字形词典(裁决 §1 原样收录 + 处决名单 + VS15 铁律)
4. 十个表面施工 spec
5. 全屏 mockup ×3(100×30)
6. 动效 spec
7. 窄屏降级(<90 / <80)
8. 新接线需求(app.py / StatusBar 状态机 / 记忆召回行)
9. 施工分解表(6-9 包,文件不相交)
10. 不可破契约附录(11 条 + 三陷阱)

---

## 1. 设计哲学

「黑曜石之眼」= **B 黑曜石视觉系统打底 + C 百眼母题做签名 + A 瞭望塔仪表纪律做右栏**。

1. **看守者不喧哗,但只用一只眼说话。** 全屏 chrome 几近隐形(三层背景亮度差分层,不靠竖线),
   唯一持续亮着的符号是一只眼 `◉`——它的姿态即 agent 状态,瞳色即 verdict 真相。装饰预算全花在韵律与真相上。
2. **三层纵深 = 三层注意力。** 黑曜石井底/流面/浮起三个深度面,眼睛沿光走不沿线走;主流亮、右栏暗一档,靠色差分栏。
3. **单强调系统,克制到吝啬,但金橙分家。** chrome 注意力用暖金 `$eye`;真相不确定用更橙更饱和的 `$unverif`;
   危险态(YOLO)脱离金系走红。金是 chrome,橙是 verdict,语义分区即视觉分区,**永不同行相邻**。
4. **文字层级即设计。** 4 级墨色亮度阶梯做出 Editorial 纵深,禁止默认色,每个文本片段显式归层。
5. **诚实是唯一不可省的像素。** DEMO 标识、四态 verdict、self-verified 第四态、无法验证三重冗余——永远满亮,绝不被"美观"稀释。
6. **眼睛是状态机,不是贴纸。** 七姿态眼承载 plan/act/verify/report/审批/空态/弱通过的全部语义;拿掉眼,信息就缺失。
   这是 v2 没有的"不可错认的身份":别的 TUI 用 emoji 装点,Argos 用一只可验证真相的眼。

---

## 2. Design Tokens 全表

### 2.1 执行规则(铁律)

- **禁止默认色。** 每个文本片段必须显式归入下表某个 token。渲染层若出现未着色文本 = bug。
- **金橙分家。** `$eye*` 金系只给 chrome/注意力;`$unverif*` 橙系只给"真相不确定"。两者**永不同行相邻出现**。
- **三色语义 + 青只在真相与数据处出现。** 绿/红/橙平时绝不出现,出现即真相到了;青 `$cyan` 仅给缓存(冷=省钱)。
- **字重两档。** `bold`(强调/标题/当前态)与 `normal`。italic 唯一保留给 self-verified 注解行(B 的"语义性斜体"唯一保留地)。

### 2.2 背景层级(三层纵深 + 两个边界 + 两档发丝)

| Token | hex | 用途规则 |
|---|---|---|
| `$abyss` | `#0B0C10` | 井底:终端最外背景、StatusBar 下沉地基感 |
| `$well` | `#0E0F15` | 第一深度:TopBar / **右栏底**(比流面暗→分栏) / 输入区底 |
| `$stream` | `#13141B` | 流面(主):Transcript 散文背景、默认底 |
| `$raise` | `#1B1D29` | 浮起:代码块 / diff / 审批卡背景(比流面亮一档=浮起感) |
| `$raise-2` | `#23263A` | 二级浮起:审批卡选中项、slash 选中行高亮 |
| `$hairline` | `#23252E` | 发丝分隔线(几乎不可见,只在留白不够时出现) |
| `$hairline-lit` | `#2E3142` | 点亮发丝线:活动块左缘、focus 边界、diff 左缘 |

### 2.3 墨色(文字 5 阶亮度阶梯——纵深引擎)

| Token | hex | 字重 | 用途规则 |
|---|---|---|---|
| `$ink-bright` | `#ECEEF5` | bold | 最高层:assistant 强调名词、verdict 正文、当前阶段名、命令焦点、成本数字 |
| `$ink` | `#C8CCDA` | normal | 散文正文(默认阅读层) |
| `$ink-dim` | `#7E869C` | normal | 次要:用户输入回显、元信息、阶段标签、工具名、step 号 |
| `$ink-faint` | `#525A73` | normal | 最弱:键提示、占位符、空态 `◌`、计数、注解第二行、faint 系统行 |
| `$ink-ghost` | `#3A4055` | normal | 幽灵:折叠提示 `… +N 行`、未激活树枝、示意分隔 |

### 2.4 金系(chrome 强调,三档亮度——裁决①保留)

| Token | hex | 用途规则 |
|---|---|---|
| `$eye-soft` | `#A8854A` | 弱强调:非活动徽标、border-title、次级标记、idle 暗金之眼 |
| `$eye` | `#D9A85C` | 主强调:logo 之眼、当前阶段字形、`›`/`▸` 光标、focus 标题、活动块左缘、inline code |
| `$eye-glow` | `#F0C078` | 高亮强调:呼吸光峰值、块光标背景、选中项前缀、splash 之眼峰值 |

### 2.5 语义色(诚实铁律——继承 Tokyo-Night 基因,裁决②③)

| Token | hex | 语义 | 不可混淆约束 |
|---|---|---|---|
| `$pass` | `#9ECE6A` | verdict passed(强)、diff `+`、done、LIVE | 唯一的绿,必须是用户级强通过 |
| `$pass-weak` | `#73A857` | **self-verified 弱通过(第四态)** | 去饱和绿(裁决③),配 `◍` 格纹瞳 + italic 注解,与 `$pass` 双轴不可混淆 |
| `$fail` | `#F7768E` | verdict failed、diff `-`、error、YOLO 危险态(裁决②) | 唯一的红 |
| `$unverif` | `#FF9E64` | verdict unverifiable、escalation、审批 medium 风险 | 橙(裁决①,从 #E0A24E 改 #FF9E64,更橙更饱和);**永远三重冗余**:色 + `◔` glyph + "无法验证"文字 |
| `$unverif-deep` | `#9A6E2E` | unverifiable 块左缘(暗一档) | 防止橙竖条喧宾夺主 |
| `$cyan` | `#7DCFFF` | 缓存命中 sparkline + 读数(冷色=省钱,A 的数据冷轴) | 仅给缓存,语义"冷=省",一眼区分暖金的"花钱" |

### 2.6 模式徽标色(裁决②:YOLO/DEMO/plan 脱离金系)

| 徽标 | token | hex | 语义 |
|---|---|---|---|
| YOLO | `$fail` | `#F7768E` | 危险态(不是注意力态),走红 |
| DEMO | `$unverif` | `#FF9E64` | 琥珀橙诚实标识 |
| plan mode | `$plan` | `#7AA2F7` | 蓝(plan ≠ act) |
| LIVE | `$pass` | `#9ECE6A` | 绿(仅有 key 时) |
| 未配 key | `$unverif` | `#FF9E64` | 橙(诚实未就绪) |

### 2.7 光标

| Token | fg | bg | 用途 |
|---|---|---|---|
| block-cursor | `$abyss #0B0C10` | `$eye-glow #F0C078` | 输入块光标 |

### 2.8 theme.py 完整新值

`theme.py` 从 27 行扩为完整 token 体系(背景4层 + 墨5阶 + 发丝2档 + 金3档 + 语义4+1 + 青1 + 徽标/光标),
**主题注册名保持 `"argos-night"`**(避免用户配置破损;名字不是设计)。`variables={}` dict 全文如下,供 `Theme()` 构造:

```python
from textual.theme import Theme

ARGOS_NIGHT = Theme(
    name="argos-night",          # 注册名不变——契约
    dark=True,
    # ── Textual 内置语义槽(映射到黑曜石底盘)──
    primary="#D9A85C",           # $eye:唯一 chrome 强调
    secondary="#7AA2F7",         # $plan:plan mode 蓝
    accent="#D9A85C",            # = primary
    foreground="#C8CCDA",        # $ink:散文阅读层
    background="#0B0C10",        # $abyss:井底
    surface="#0E0F15",           # $well:第一深度(右栏/输入底)
    panel="#1B1D29",             # $raise:浮起面(代码/diff/审批底)
    success="#9ECE6A",           # $pass
    warning="#FF9E64",           # $unverif(裁决①更橙)
    error="#F7768E",             # $fail
    boost="#23263A",             # $raise-2
    variables={
        # ── 背景层级(三层纵深 + 边界)──
        "abyss": "#0B0C10",
        "well": "#0E0F15",
        "stream": "#13141B",
        "raise": "#1B1D29",
        "raise-2": "#23263A",
        "hairline": "#23252E",
        "hairline-lit": "#2E3142",
        # ── 墨色 5 阶 ──
        "ink-bright": "#ECEEF5",
        "ink": "#C8CCDA",
        "ink-dim": "#7E869C",
        "ink-faint": "#525A73",
        "ink-ghost": "#3A4055",
        # ── 金系 3 档(chrome 强调)──
        "eye-soft": "#A8854A",
        "eye": "#D9A85C",
        "eye-glow": "#F0C078",
        # ── 语义色(诚实铁律)──
        "pass": "#9ECE6A",
        "pass-weak": "#73A857",
        "fail": "#F7768E",
        "unverif": "#FF9E64",
        "unverif-deep": "#9A6E2E",
        "cyan": "#7DCFFF",
        # ── 模式徽标 ──
        "plan": "#7AA2F7",
        # ── 块光标 ──
        "block-cursor-foreground": "#0B0C10",
        "block-cursor-background": "#F0C078",
        # ── 滚动条 / focus(贴黑曜石)──
        "scrollbar": "#1B1D29",
        "scrollbar-hover": "#23263A",
        "border": "#2E3142",
    },
)
```

> 旧 token 名向后兼容映射(CSS 仍引用 `$accent/$success/$warning/$error/$panel/$surface/$background/$foreground/$text-muted`):
> 上表的 Textual 内置槽已覆盖前八个;`$text-muted` → 在 variables 追加 `"text-muted": "#7E869C"`(= `$ink-dim`)。
> **所有新 CSS 一律用新语义名 `$ink-*/$eye*/$pass/$fail/$unverif/$cyan/$stream/$raise/$hairline*`;旧名仅为未迁移 CSS 的兜底,逐表迁移。**

---

## 3. 字形词典(裁决 §1 原样收录)

### 3.1 眼睛状态机(全 EAW=N,静态字形,绝不做动画帧)

| 姿态 | glyph | 码点 | 语义 |
|---|---|---|---|
| 未睁/空态/未配置 | `◌` | U+25CC | 「该有只眼但还没睁开」= **统一空态**(C 钦点) |
| 半阖/等待用户 | `◓` | U+25D3 | 审批挂起/等决策(上半黑=眼睑半垂) |
| 扫视/plan | `◔` | U+25D4 | 计划阶段 |
| 注视/act | `◉` | U+25C9 | 执行中(瞳孔全开,**品牌主 glyph**) |
| 聚焦/verify | `❂` | U+2742 | 验证中(虹膜聚焦成镜头) |
| 阅毕/report·完成 | `◕` | U+25D5 | 收尾 |
| 格纹瞳/self-verified | `◍` | U+25CD | **弱通过专用**(格纹=不纯正),C 的最优雅遗产 |

> **注意 `◔` 一符二用**:既是 plan 阶段眼,又是 unverifiable verdict 前缀。语境分明(阶段轨 vs verdict 行),不冲突。

### 3.2 保留(事实安全,与 Textual 边框同级)

- 八分块(水位/工具条):`▏▎▍▌▋▊▉█`(U+258F..U+2588)、空槽 `░`(U+2591)
- sparkline(缓存/成本历史):`▁▂▃▄▅▆▇`(U+2581..U+2587)、满 `█`
- 树线:`│ ├ └ ─`(U+2502/251C/2514/2500)、半虚线回合分隔 `╌`(U+254C)
- 运行控制徽标(TabStrip):`⏵ ⏸ ⏹`(U+23F5/U+23F8/U+23F9,全 N)
- 引导:`›`(U+203A 用户前缀)、`▸`(U+25B8 选中光标)、`↑ ↓`(U+2191/2193)、`↘`(U+2198 省下)、`⤷`(U+2937 注解引出)、`↯`(U+21AF 压缩)、`…`(U+2026 折叠)
- braille spinner 帧:`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`(U+2800 块,全 N,v2 已验证)

### 3.3 被处决的字形(EAW=A,任何对齐场景禁用)

`◎ ⊙ ● ○ ◐ ◑ ☉ ◇ ◆ ◈ ▶ • ·`(中点 `·` 禁用,字段分隔改空格或 ` · ` 时**两侧带空格**才安全);
`✓` 允许但**仅限行尾非对齐位**。

**v2 emoji 全部处决:** 🟢⏳🟡⚪❌🔴🧾⚙ → 替换为 `⏵⏸⏹`(运行控制)+ 眼系 + `⚙`→文字"动作"或眼系计数。

> 字段分隔符决定:全系统用 ` · `(空格 + U+00B7 + 空格),两侧空格保证 `·` 不参与紧贴对齐;紧贴位一律用单空格。

### 3.4 ⚠︎ VS15 铁律(全代码库,含既有代码)

警告符**必须写作 `⚠︎`**(U+26A0 + U+FE0E variation-selector-15,强制文本字形)。
裸 `⚠` 在部分终端渲染成宽 emoji 破坏对齐 = bug。本铁律适用于全代码库既有与新增代码。
本设计内"风险/警告"语义统一用 `⚠︎`;审批卡标题前缀用半阖眼 `◓`(见 §4.7),`⚠︎` 仅用于 secret 命中/坏配置等真警告行。

---

## 4. 十个表面的施工 spec

> 渲染样例中 `‹$token›` 为着色注释,**非渲染内容**。所有 glyph 已确认等宽安全(EAW=N)。
> 每个表面给出:(a) 渲染样例;(b) DEFAULT_CSS 新值全文;(c) 保持不变的公开 API 签名;(d) 要更新的测试文件与断言点。

---

### 4.1 TopBar(高 1,底 `$well`)

近乎隐形。品牌符从 `✳` 换为**状态同步的眼**:idle 时 `◌` 暗金,run 时随阶段。

**(a) 渲染样例**

idle:
```
 ◌ Argos v0.3 · MiniMax-M3                                       · idle    ● LIVE
‹◌ $eye-soft 暗金 · Argos $ink-bright bold · v0.3·model $ink-dim · idle $eye-soft · ●LIVE→改用 $pass(见注)›
```
run 中(act 阶段):
```
 ◉ Argos v0.3 · MiniMax-M3                                       · act     LIVE
‹◉ $eye(act 注视眼) · 阶段标签 $eye-soft · LIVE $pass›
```
plan mode:
```
 ◔ Argos v0.3 · MiniMax-M3                              plan      LIVE
‹◔ $eye · plan 徽标 $plan 蓝 · 去方括号(Editorial)›
```

- 品牌眼随状态:idle `◌`$eye-soft / plan `◔`$eye / act `◉`$eye / verify `❂`$eye / report·done `◕`$eye。
- `Argos`= `$ink-bright bold`;`v0.3 · {model}`= `$ink-dim`。
- 徽标(去方括号,色相区分态):`plan`= `$plan` / `YOLO`= `$fail`(裁决②危险红)/ `DEMO 脚本演示`= `$unverif` / `未配 key`= `$unverif` / `LIVE`= `$pass`。
- **`● LIVE` 的 `●` 被处决**(EAW=A);改为纯文字 `LIVE`(着 `$pass`),无前缀点。

**(b) DEFAULT_CSS**
```css
TopBar { height: 1; background: $well; padding: 0 2; }
```

**(c) 不变 API** `__init__(*, version, model_label)`、`set_state(*, model_label, plan_mode, yolo, demo, has_key)`、`badges() -> list[str]`、`render_text: str`。
新增内部状态接收当前 phase(经既有 `set_state` 扩参或新增 `set_phase(phase)`——**新增 setter 不动既有签名**)。

**(d) 测试** `tests/test_topbar.py`(或 tests/tui/):断言 `badges()` 文本(`plan`/`YOLO`/`DEMO 脚本演示`/`未配 key`/`LIVE`);
断言 `has_key=False` 时 `render_text` **不含 "LIVE"**(契约6);更新 logo 字符断言 `✳`→ 眼系(随 phase)。

---

### 4.2 StartupSplash(睁眼仪式,content-align center middle)

**禁止 ASCII 巨眼**(裁决判死)。ARGOS 块字 logo 保留 + 精修;下方一行状态眼随启动自检推进。

**(a) 渲染样例**(有 key,启动完成)
```


              ▄▀█ █▀█ █▀▀ █▀█ █▀   ‹$ink-bright,末笔点睛 $eye›
              █▀█ █▀▄ █▄█ █▄█ ▄█

                    ◉                ‹$eye-glow 居中状态眼,呼吸›

       终端超级智能体 · v0.3 · MiniMax-M3 · LIVE   ‹模型段 $ink-dim · LIVE $pass›
       输入目标开始 · / 命令 · Esc 打断 · ^C 退出   ‹$ink-faint›


```

- **睁眼仪式**:状态眼随启动自检推进 `◌ → ◔ → ◓ → ◉`(空 → 扫视 → 半阖 → 注视),约 0.6s 走完,**仅一次,非循环**(见 §6.3)。
- **无 key 永远停在 `◌`** + 文案 `未配 key · /setup`(`$unverif`),**绝不出现 LIVE**(契约6,"不见真相眼不睁")。
- DEMO:眼停在 `◓`(半阖)+ `DEMO 脚本演示`(`$unverif`)。
- plan mode:logo 整体切 `$eye-soft`,文案首加 `plan · `。
- 有 key 终态:`◉` `$eye` + `LIVE` `$pass`。之眼呼吸(见 §6.2);logo 本身静止。

**(b) DEFAULT_CSS**
```css
StartupSplash { content-align: center middle; height: auto; padding: 1 0; background: $stream; color: $ink-bright; }
StartupSplash.-plan-mode { color: $eye-soft; }
```

**(c) 不变 API** `__init__(*, model_label, tier, live, has_key)`、`set_plan_mode(active)`、`set_bad_config(reason)`、`renderable_text: str`、reactive `plan_mode`。
新增内部:`advance_eye(stage)` 推进睁眼仪式帧(纯新增,不动既有签名)。

**(d) 测试** `tests/test_splash.py`:断言 `has_key=False` → `renderable_text` 含 "未配 key" 且**不含 "LIVE"**(契约6);
断言 DEMO 态含 "DEMO 脚本演示";更新 logo 末态眼字符断言为 `◉`/`◌`/`◓`;断言无 ASCII 巨眼(不含旧 `█████╗` 之外的眼形 box)。

---

### 4.3 Transcript(用户行 / 流式 / 系统行)

#### 用户行(UserMessage,markup=False 防崩——契约5)

**(a)**
```
 › 帮我把 auth.py 的密码校验改成 bcrypt   ‹› $eye-soft · 正文 $ink-dim›
```
回合间:上方一条 `╌` dashed `$hairline` + 上下各 1 空行,呼吸感。

#### assistant 流式(Markdown,$ink 阅读层)

**(a)**
```
 我会先读取现有实现,确认当前用的是 SHA-256,再替换为 bcrypt 并加盐。  ‹$ink›
 关键改动在 `verify_password` 与 `hash_password` 两处。  ‹inline code $eye›
```
- 散文正文 `$ink`;`**强调**`→ `$ink-bright bold`;`` `inline code` ``→ `$eye`(金调代码感);段落下边距 1 行。

#### 系统行(SystemLine,四类着色 + 新增 faint 类)

**(a)**
```
 ◌ 记忆召回 2 条   ‹$ink-faint,system 类——run 开始时(新接线 §8.3)›
 ◌ 已压缩 -38% · 12→5 条   ‹$ink-faint,system 类——CompactedEvent(新接线 §8.1)›
 ◌ 已修剪 3 条   ‹$ink-faint,system 类——PrunedEvent(新接线 §8.1)›
 ⚠︎ 连续 3 次 verify 失败,需要你介入   ‹$unverif,escalation 类 · ⚠︎ VS15›
 ◕ run 完成 · 18.4s   ‹$pass,done 类 · ◕ 阅毕眼›
 ◉ 模型连接中断:read timeout   ‹$fail,error 类 · ◉ 红瞳=眼睛看到错误›
```

- done 行前缀 `◕`(阅毕眼,`$pass`);error 行前缀 `◉`(红瞳,`$fail`);escalation 行前缀 `⚠︎`(`$unverif`);system/faint 行前缀 `◌`(`$ink-faint`)。

**(b) DEFAULT_CSS**
```css
UserMessage { color: $ink-dim; padding: 0 2; }
AssistantMessage { background: transparent; margin: 0 0 1 0; padding: 0 2; }
SystemLine { padding: 0 2; }
SystemLine.sys-error { color: $fail; }
SystemLine.sys-escalation { color: $unverif; }
SystemLine.sys-done { color: $pass; }
SystemLine.sys-system { color: $ink-faint; }
Transcript { background: $stream; }
```

**(c) 不变 API** `user_line(text)`、`append_token(text)`、`finalize_response()`、`append_line(text, *, kind)`(kind ∈ system/error/escalation/done)、`mount_block(widget)`、`show_thinking(label)`、`clear()`、`rendered_text: str`。
**契约4**:`finalize_response` 开新气泡;`append_token` 剥 ``` 围栏;不自动拽回用户滚动位置。

**(d) 测试** `tests/test_transcript.py`:行为契约断言(剥围栏/finalize 开气泡/不抢滚动)**不动语义**;
视觉断言更新系统行前缀(`◕`/`◉`/`⚠︎`/`◌`)与回合分隔字符 `╌`;断言 UserMessage `_render_markup is False`(契约5)。

---

### 4.4 CodeActionBlock(扁平,底 `$raise` 浮起,⏺ 标头保留)

无四面框,靠 `$raise` 比 `$stream` 亮一档"浮起",顶行 `⏺` 标头(N 安全,v2 测试已断言保留)+ 阶段眼锚定。

**(a) 渲染样例**
```
 ⏺ python · step 3 ‹⏺ $eye · 标签 $ink-dim›
   x = tool.read("auth.py")              ‹Syntax,monokai 偏暗调›
   pw = bcrypt.hashpw(raw, bcrypt.gensalt())
   … +14 行 ‹$ink-ghost 折叠提示›
   └ ◕ 执行完成 · 0.4s ‹└ $ink-faint · ◕ $pass · 时间 $ink-dim›
```

- 标头 `⏺`(U+23FA,保留——契约,v2 测试已断言);后随 `python · step N`(`$ink-dim`)。
- 结果行 `└` 引出:ok=True → `└ ◕ 执行完成`(`◕` 阅毕眼 `$pass`);ok=False → `└ ◉ FileNotFoundError`(`◉` 红瞳 `$fail`,整行 `$fail`)。
- 折叠:>8 行显前 6 + `… +N 行`(`$ink-ghost`)。底色 `$raise`,无任何框线。

**(b) DEFAULT_CSS**
```css
CodeActionBlock { height: auto; margin: 0 0 1 0; background: $raise; padding: 0 2; }
CodeActionBlock #code { padding: 0 0 0 2; }
CodeActionBlock #code-fold { color: $ink-ghost; padding: 0 0 0 2; }
CodeActionBlock #result { color: $ink-faint; padding: 0 0 0 2; }
CodeActionBlock.ok-false #result { color: $fail; }
```

**(c) 不变 API** `__init__(*, code, step)`、`set_result(*, stdout, value_repr, exc, ok)`、reactive `ok`。

**(d) 测试** `tests/test_code_action_block.py`:断言标头含 `⏺`(契约保留);更新结果行前缀断言 `◕`/`◉`;断言 ok=False 时 `.ok-false` 类挂上且 `#result` 红;折叠 `… +N 行` 文案不变。

---

### 4.5 DiffView(仅左缘一线)

**(a) 渲染样例**
```
 │ Edit · auth.py  +3 −1 ‹border-title:Edit $ink-bright · path $eye · +$pass −$fail›
 │   @@ -10,3 +10,4 @@        ‹$ink-dim›
 │ − pw = sha256(raw).hexdigest()   ‹整行 $fail 去饱和一档,− 号同色›
 │ + pw = bcrypt.hashpw(raw, salt)  ‹整行 $pass 去饱和一档,+ 号同色›
```

- `border-left: tall $hairline-lit`(一条点亮发丝竖线),**无上下右框**。
- border-title 走在竖线顶端:`Edit · {path}`(`Edit` `$ink-bright`,path `$eye`);border-subtitle `+{a} −{r}`(`$pass`/`$fail`)。
- diff 正文 `+`/`−` 整行着 `$pass`/`$fail` 但**去饱和一档**(diff 是历史不是裁决,不与 verdict 抢夺目度)。

**(b) DEFAULT_CSS**
```css
DiffView { border-left: tall $hairline-lit; border-title-color: $ink-bright;
           background: $raise; padding: 0 1; margin: 0 0 1 0; height: auto; }
```
> 从 v2 的 `border: round $panel` 改为仅左缘 `border-left: tall`。Syntax theme 仍 monokai,lexer "diff"。

**(c) 不变 API** `__init__(*, path, added, removed, unified)`;公开属性 `path/added/removed/unified`。
`border_title = "Edit · {path}"`(去 `⏺` 前缀——diff 标题不再用录制圆,改纯文字 + 左缘竖线);`border_subtitle = "+{added} −{removed}"`。

**(d) 测试** `tests/test_diff_view.py`:断言 border_title 含 path、border_subtitle 含 `+N −M`;diff +/− 行着色类;
更新边框断言(从 round 改 tall left)——若测试断言旧 `border: round`,改为断言 `border-left`。

---

### 4.6 VerdictBadge(四态!诚实核心,四重冗余)

四态视觉**必须互不可错认**。CSS 类名 `verdict-passed/verdict-failed/verdict-unverifiable` **不许改**(契约7),新增 `verdict-self`。

**(a) 渲染样例**(四态)
```
 ◉ verify passed · pytest -x · 1 次尝试 → 12 passed   ‹◉+正文 $pass · passed bold›
```
```
 ◉ verify FAILED · pytest -x → 2 failed               ‹◉+正文 $fail · FAILED bold 大写›
   ⤷ 重试 3 次后仍 failed · test_login.py assert mismatch  ‹$ink-faint 注解(失败时)›
```
```
 ◔ 无法验证 · verify_cmd 未注册(trivial 命令被拒)    ‹◔+正文 $unverif 橙(三重冗余:◔+橙+"无法验证")›
```
```
 ◍ 自验证通过(较弱) · 系统自造测试 → 3 checks ok      ‹◍ $pass-weak 去饱和绿›
   ⤷ 非用户级 verify,未晋级技能                       ‹$ink-faint italic 注解第二行›
```
tampered 归入 unverifiable:
```
 ◔ 无法验证 · 受保护文件被改 auth.py → tamper detected ‹◔ $unverif›
```

**四态区分矩阵(为什么不可混淆):**

| 态 | 前缀眼 | 字色 | 字重/style | 附加 |
|---|---|---|---|---|
| passed | `◉` 注视实瞳 | `$pass` 满绿 | bold | 小写 `passed` · `N 次尝试` |
| failed | `◉` 注视实瞳 | `$fail` 红 | bold | **大写 FAILED** · 失败追加 `⤷ 重试 N 次 · detail` |
| unverifiable | `◔` 扫视半瞳 | `$unverif` 橙 | normal | 中文"无法验证" · 三重冗余(◔+橙+文字) |
| **self-verified** | `◍` **格纹瞳(非实瞳!)** | `$pass-weak` 去饱和绿 | **italic 注解** | 强制第二行 `⤷ 非用户级 verify,未晋级` |

> 四态对 verdict 对象映射:`status=="passed" and not self_verified` → passed(`◉`绿);`status=="passed" and self_verified` → self-verified(`◍`去饱和绿);`status=="failed"` → failed(`◉`红);`status=="unverifiable"`(含 tampered)→ unverifiable(`◔`橙)。
> self-verified 四重区分:① 前缀 `◉`→`◍`(格纹瞳);② 色满绿→去饱和绿;③ 唯一 italic 注解;④ 强制 `⤷ 较弱` 第二行。任一用户都不会读成强通过(契约10)。
> **新机会点③**:verdict 正文展示 `verify_cmd → detail`,passed 显 `N 次尝试`,failed 追加 `⤷ 重试 N 次 · detail`(从 `Verdict.detail/verify_cmd/attempts` 取——见 §8 数据)。

**(b) DEFAULT_CSS**
```css
VerdictBadge { padding: 0 2; margin: 0 0 1 0; height: auto; }
VerdictBadge.verdict-passed       { color: $pass; text-style: bold; }
VerdictBadge.verdict-failed       { color: $fail; text-style: bold; }
VerdictBadge.verdict-unverifiable { color: $unverif; }
VerdictBadge.verdict-self         { color: $pass-weak; }
```

**(c) 不变 API** `show(verdict: Verdict)`、reactive `status`、`render_text: str`。CSS 三类名不变(契约7)+ 新增 `verdict-self`。

**(d) 测试** `tests/test_verdict_badge.py`:断言四态前缀眼字符(`◉`/`◉`/`◔`/`◍`);断言 self-verified 挂 `verdict-self` 类 + `render_text` 含"较弱"与"未晋级"(契约10);
断言 passed `render_text` 含 verify_cmd 与"N 次尝试";failed 含 detail 与"重试";unverifiable 文本含"无法验证"(三重冗余文字证据)。

---

### 4.7 InlineChoice 审批卡(唯一允许"厚"的表面)

挂进流内,FIFO 幂等,底 `$raise` 浮起 + 风险色厚左缘。`padding: 1 2`(比普通块松)。标题 `◓` 半阖眼。

**(a) 渲染样例**(risk=medium)
```

  ◓ 审批请求 · medium ‹◓+标题 $unverif bold› — soft rule: ask git push ‹$ink-dim›
                                                          ‹↑ border-left thick $unverif›
  git push origin main                       ‹$ink-bright,命令是焦点›
  run_command · {remote: origin, branch: main}   ‹$ink-faint 元信息›

  ▸ 1  本次允许       ‹▸ $eye · label $ink-bright bold(选中)›
    2  本会话允许      ‹$ink-dim›
    3  总是允许        ‹$ink-dim›
    4  拒绝            ‹$ink-dim›

  ↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 拒绝   ‹$ink-faint›

```

- 标题前缀 `◓`(半阖眼=等你决定,`$unverif` medium / `$fail` high)。
- 风险色左缘:`low`→`thick $hairline-lit`;`medium`→`thick $unverif`;`high`→`thick $fail`。
- secret 命中:标题副标追加 `· ⚠︎ 命中密钥模式 AWS_KEY`(`$fail`,⚠︎ VS15)。
- mount 时 `app.bell()`(契约,提示音)。
- 决策后**自毁为一行**:`◕ 审批 run_command → once`(`◕` 阅毕眼,`$ink-faint`),焦点还 PromptArea(裁决:C 的状态叙事安全字形版)。
- refine(计划场景):就地展开一行 Input(`border: round $hairline-lit`)。

**(b) DEFAULT_CSS**
```css
InlineChoice { height: auto; margin: 0 0 1 0; padding: 1 2; background: $raise; border-left: thick $unverif; }
InlineChoice.risk-low  { border-left: thick $hairline-lit; }
InlineChoice.risk-high { border-left: thick $fail; }
InlineChoice #ic-title { text-style: bold; color: $unverif; }
InlineChoice.risk-high #ic-title { color: $fail; }
InlineChoice #ic-body { color: $ink-bright; }
InlineChoice #ic-hint { color: $ink-faint; }
InlineChoice #ic-input { display: none; }
InlineChoice.-input-mode #ic-input { display: block; }
```

**(c) 不变 API** `__init__(*, title, body, options, on_decide, escape_value, needs_input, input_placeholder, risk)`;模块级 `format_approval_title(*, risk, trigger)`。
**契约2/3 + 陷阱3**:键盘 ↑↓/Enter/数字1-9/Esc;FIFO 单活动;`_finish` 不双发;`gate.respond` 先于 `_choice_done`;回调内 async 必须 `run_worker` 包住。

**(d) 测试** `tests/test_inline_choice.py`:行为契约断言(幂等/FIFO/Esc=escape_value/数字直选/bell)**不动语义**;
视觉断言更新标题前缀 `◓`、自毁结果行前缀 `◕`、`⚠︎` secret 副标;断言 risk-high 左缘 `$fail`、title `$fail`。

---

### 4.8 ActivityPanel(width 34,四列网格,四桶,sparkline,compaction 行)

底 `$well`(比 `$stream` 暗一档分栏,**不画竖线**)。宽 **32→34**(裁决:容纳 A 的四列对齐网格)。
section 用 `border-top` 发丝线 + border-title;空态一律 `◌` + 最弱墨,绝不预填假数据。智能切 4 视图(idle/plan/act/verify)+ 常驻 footer。

**右栏四列网格(铁律,A 钦点)**:每行读数对齐到 4 隐形列 —— `标签(8) │ 读数(7) │ 条(11) │ 尾注(6)`,合计 32 列 + 2 padding = 34。所有仪表行服从此网格。

**视图标题**:发丝顶线 + border-title `─ act ─`(auto)/ `─ act * ─`(Ctrl+O pinned,`*` 而非 emoji)。

**(a) act 视图样例(含机会点采纳)**
```
─ 进度 ───────────  ‹border-top $hairline · title $eye-soft›
  ◉ act       ⠹ ··  ‹当前阶段 $eye · ⠹ braille spinner $eye›
  ◔ plan    1.2s ◕  ‹完成 $ink-dim · ◕ $pass›

─ 工具 ───────────
  read_file  ×3     ‹名 $ink · 计数 $ink-faint›
  edit_file  ×1

─ 回执(已签名)──
  read_file  auth.py ‹$ink-dim,无 emoji›

─ 上下文 ─────────  ‹常驻 footer 区›
  MiniMax-M3 · 200k     ‹$ink-dim›
  ████████▌░░░░ 34%     ‹墨蓄满:$eye 实块 + 亚格尾 · 空槽 $hairline›
  68.0k / 200k          ‹$ink-faint›
  ├ system 12k · mem 4k ‹四桶明细——机会点② $ink-faint,health 色随占比›
  ├ tools  9k · msgs 43k
  缓存命中 18.2k tok ↘   ‹cache_read——机会点④ $cyan›
  ↯ 已压缩 -22% · 12→4 条 ‹CompactedEvent——机会点① $ink-faint›

─ 成本 ───────────
  ↑12.4k ↓3.1k          ‹$ink-dim›
  $0.013 · 4.2s         ‹$ink-bright bold(钱满亮)›
  cache ▂▃▅▇▅▃ 18.2k    ‹cache sparkline $cyan——机会点④›
```

**视图—区段可见性矩阵(不变)**

| 视图 | 可见区段 |
|---|---|
| idle | 模型 / Run / Skill / MCP / 上轮裁决 + footer |
| plan | 进度 + footer |
| act | 进度 / 工具 / 回执 / Hook / LSP / Skill / Approval + footer |
| verify | 进度 / Approval / 裁决(verify_cmd 全文 + 四阶段耗时表)+ footer |
| footer(常驻) | 上下文(水位+四桶+缓存+压缩行)/ 成本(↑↓+$+cache sparkline) |

- 上下文条 ≥80% → 整条 `$unverif`;≥95% → `$fail` 且数字 bold。
- 空态诚实:`◌ (无)` `$ink-faint`,绝不预填。
- verify 视图「裁决」区段四阶段耗时表(机会点③,C 偷来):`◔ plan 1.2s / ◉ act 6.1s / ❂ verify 0.9s / ◕ report 0.2s`。
- 缓存 sparkline 用 `▁▂▃▄▅▆▇` `$cyan`(机会点④);压缩行 `↯`(机会点①);四桶 `├ ...`(机会点②);记忆召回在 Run 区段显 `◌ 召回 N 条`(机会点⑤)。

**(b) DEFAULT_CSS**
```css
ActivityPanel { width: 34; background: $well; padding: 1 0 0 0; overflow-y: auto; scrollbar-size-vertical: 1; }
ActivityPanel #view-header { color: $eye-soft; text-style: bold; padding: 0 1; margin: 0 0 1 0; }
_Section { height: auto; padding: 0 1; margin: 0 0 1 0;
           border-top: solid $hairline;
           border-title-color: $eye-soft; border-title-style: bold; border-title-align: left; }
```
> 从 v2 的 `width: 32; border-left: solid $panel` 改为 `width: 34; background: $well`(裁决:靠背景色差分栏,无竖线)。
> `overflow-y: auto` **保留**(契约8)。

**(c) 不变 API(陷阱1——全部 12+ 方法签名不许动,app.py 硬编码 id + except:pass 会静默失败)**
`__init__(*, model_label, tier)`、`set_view(view, *, pinned)`、`cycle_view() -> str`、`on_phase(phase, actions)`、`on_plan(todos)`、`on_receipt(action)`、`on_cost(...)`、`on_context(...)`、`on_verdict(verdict)`、`on_hook_fired(ev)`、`on_lsp_server_event(ev)`、`on_lsp_diagnostic_event(ev)`、`on_run_summary(*, active, paused, suspended, history)`、`on_approval_decision(*, action, decision, trigger)`、`reset_run()`、`snapshot_text() -> str`。
**新增**(纯加,不动既有):`on_compacted(before, after, reduction_pct)`、`on_pruned(before, after, removed)`、`on_memory_recall(hits)`、`on_cache(cache_read, history)`(若 `on_cost` 已带 cache_read 则复用,不新增)。

**(d) 测试** `tests/test_activity_panel.py` / `tests/tui/test_activity_panel.py`:`overflow_y == "auto"` 断言不动(契约8);
`snapshot_text()` 断言更新四列网格渲染、四桶 `├ system`、缓存 sparkline、压缩 `↯` 行、空态 `◌ (无)`、宽度 34;
所有既有方法存在性/签名断言**保持**(陷阱1)。

---

### 4.9 StatusBar(状态眼 + 优先级铁律)

dock bottom 高 1,底 `$abyss`(最深地基感)。**最左永远一只状态眼。**

**渲染优先级铁律(裁决,评审3 fatal 的解)**:用户阻塞态永远赢。

```
优先级:用户阻塞(审批挂起) > 告警锁色(failed/unverifiable/escalation/error) > 阶段眼
```

- 审批挂起时左眼 `◓` 金,**不管 verify 是否在跑**(右栏仍显 `❂`);
- 其次告警锁色(`_terminal_glow=True` 时锁红/橙,**阶段色不得覆盖**——陷阱2);
- 再次阶段眼。

**(a) 渲染样例**
普通(act 阶段):
```
 ◉ act · 动作3 · ↑12.4k ↓3.1k · $0.013 · 4.2s · ctx 34%        Esc 打断 · \↵ 换行 · ^C 退出
‹◉ $eye · 数据 $ink-dim · 键提示 $ink-faint›
```
审批挂起(优先级最高,阶段眼让位):
```
 ◓ 审批挂起 · 动作3 · ↑12.4k ↓3.1k · $0.013 · 8.1s · ctx 34%   Esc 打断 · \↵ 换行 · ^C 退出
‹◓ $unverif(用户阻塞赢,即便右栏在 verify)›
```
verify 失败收尾(告警锁色):
```
 ◉ verify · 动作5 · ↑34.0k ↓8.2k · $0.041 · 18.4s · ctx 41%    Esc 打断 · \↵ 换行 · ^C 退出
‹眼 + 整条 $fail bold(_terminal_glow 锁色,阶段色不覆盖——陷阱2)›
```

- 阶段眼随 phase + `$eye`:`◔ plan` / `◉ act` / `❂ verify` / `◕ report` / `◌ idle`(`$ink-faint`)。
- `动作N`= action 计数(`⚙` 处决,改文字"动作");`$0.013`/`ctx 34%`= `$ink-dim`。
- `ctx ≥80%` → 整条 `$unverif bold`;`≥95%` → `$fail bold`。
- 右舷键提示 `$ink-faint`;daemon badges(`⏵/⏸/⏹`)仅 daemon 模式渲染。
- 三处眼同步:StatusBar 左眼 = TopBar 品牌眼 = 右栏视图头眼(同 phase 同色),但 StatusBar 受优先级铁律覆盖。

**(b) DEFAULT_CSS**
```css
StatusBar { dock: bottom; height: 1; background: $abyss; color: $ink-faint; padding: 0 2; }
StatusBar.-plan-mode { color: $plan; }
StatusBar.-ctx-warn { color: $unverif; text-style: bold; }
StatusBar.-ctx-crit { color: $fail; text-style: bold; }
StatusBar.-blocked { color: $unverif; }
StatusBar.-alert { color: $fail; text-style: bold; }
```

**(c) 不变 API** reactives `phase/actions/tokens_in/tokens_out/cost_usd/elapsed_s/plan_mode/ctx_pct`;
`set_phase(phase, actions)`、`set_cost(...)`、`set_plan_mode(active)`、`update_ctx_pressure(pct)`、`set_run_summary(runs)`、`render_text: str`、`render_count_badges(runs)`。
**新增**(纯加):`set_blocked(active)`(审批挂起态)、`set_alert(active)`(告警锁色,_terminal_glow 联动)——优先级状态机见 §8.4。

**(d) 测试** `tests/test_status_bar.py`:断言阶段眼字符映射(`◔◉❂◕◌`);
**新增优先级断言**:`set_blocked(True)` 后 `render_text` 以 `◓` 开头且含"审批挂起",即便 phase=verify;`set_alert(True)` 后整条带 `-alert`;ctx≥80%→`-ctx-warn`、≥95%→`-ctx-crit`。

---

### 4.10 SlashMenu + PromptArea

PromptArea:多行输入,Enter 提交,`\` 续行,↑↓ 委托 SlashMenu,Tab 补全**选中项**。SlashMenu:唯一圆角浮层。

**(a) 渲染样例**
```
 ╭───────────────────────────────────────╮  ‹border round $hairline-lit›
 │ ▸ /run      运行新任务   ‹▸ $eye · 名 $ink-bright bold · desc $ink-dim›
 │   /clear    清空对话      ‹$ink-dim›
 │   /cost     成本统计
 │   /context  上下文明细
 │ ─────────────────────────  ‹$hairline›
 │ ↑↓ 选择 · ↹ 补全 · ↵ 执行 ‹$ink-faint›
 ╰───────────────────────────────────────╯
```
PromptArea 占位:
```
 › 输入目标,或 / 开始命令_   ‹› $eye-soft · 占位 $ink-faint · 光标 $eye-glow 底›
```

- 选中行 `▸` + 名 bold + 底 `$raise-2`(二级浮起高亮);其余无前缀。
- Tab/Enter 补全**选中项**(非首项);Esc 收起。

**(b) DEFAULT_CSS**
```css
PromptArea { height: auto; max-height: 8; background: $well; }
SlashMenu { display: none; height: auto; max-height: 10;
            margin: 0 2; padding: 0 1; background: $raise; border: round $hairline-lit; }
SlashMenu .menu-selected { background: $raise-2; color: $ink-bright; text-style: bold; }
```

**(c) 不变 API** `PromptArea.Submitted(text)`;`SlashMenu.show_matches(matches)` / `hide()` / `selected() -> str | None` / `move(delta)`;PromptArea BINDINGS(Enter 提交/续行,↑↓ 委托,Tab 补全)。

**(d) 测试** `tests/test_prompt_slash.py`:断言 Tab/Enter 补全**选中项**(非首项)行为不变;视觉断言更新选中前缀 `▸`、边框 `round $hairline-lit`、选中行 `$raise-2`。

---

### 4.x TabStrip(运行控制徽标,active 用底色块)

**(a) 渲染样例**
```
 ⏵ my goal $0.013    ⏸ second run $<0.01    ◕ done run $0.041
‹⏵running $pass · ⏸paused $unverif · ⏹stopped $ink-dim · ◕completed $ink-dim · ◌pending $ink-faint›
```
active tab 用底色块(`$raise-2`)**不用 [reverse]**(裁决);无 tab 时 `(no runs)` `$ink-faint`。

状态图标(v2 emoji 全换):`◌ pending` / `⏵ running` / `⏸ paused` / `⏹ suspended` / `◕ completed` / `◉ failed`($fail)/ `⏹ cancelled`。

**(b) DEFAULT_CSS**
```css
TabStrip { height: 1; background: $well; color: $ink-dim; padding: 0 2; }
TabStrip .tab-active { background: $raise-2; color: $ink-bright; text-style: bold; }
```

**(c) 不变 API** `update_tabs(tabs, *, active)`、`set_active(run_id)`、`get_active()`、`get_tabs()`;Message `TabActivated(run_id)`;BINDINGS `ctrl+1..5/ctrl+tab/ctrl+shift+tab`。

**(d) 测试** `tests/test_tab_strip.py`:断言状态字符映射(`◌⏵⏸⏹◕◉`,无 emoji);active 用 `.tab-active` 类(非 `[reverse]`);`get_active`/`TabActivated` 行为不变。

---

## 5. 全屏 mockup ×3(100×30)

> 列宽 100,行高 30。`‹注释›` 标注 token,非渲染内容。主流底 `$stream`(亮)| 右栏底 `$well`(暗)——**靠色差分栏,无竖线**。

### 5.1 状态 (a)——idle 启动后

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ◌ Argos  v0.3 · MiniMax-M3                                                       · idle      LIVE │ ‹TopBar 底$well · ◌$eye-soft 暗金 · idle$eye-soft · LIVE$pass›
│                                                                                                  │ ‹主流$stream | 右栏$well 暗一档›
│                                                                                  ─ 模型 ───────── │ ‹右栏区段 title$eye-soft›
│                              ▄▀█ █▀█ █▀▀ █▀█ █▀                                     MiniMax-M3     │ ‹logo$ink-bright 末笔$eye | $ink-dim›
│                              █▀█ █▀▄ █▄█ █▄█ ▄█                                     LIVE · key ✓   │ ‹LIVE$pass · key✓$pass›
│                                                                                  ─ Run ─────────── │
│                                      ◉                                              活跃 0 · 历史 0 │ ‹◉$eye-glow 状态眼呼吸 · 计数$ink-faint›
│                                                                                    ◌ 召回 0        │ ‹空态$ink-faint(机会点⑤)›
│              终端超级智能体 · v0.3 · MiniMax-M3 · LIVE                            ─ Skills ──────── │ ‹模型段$ink-dim · LIVE$pass›
│              输入目标开始 · / 命令 · Esc 打断 · ^C 退出                              已装 7 · MCP 0   │ ‹$ink-faint›
│                                                                                                  │
│                                                                                  ─ 上轮裁决 ─────── │
│                                                                                    ◌ (无)          │ ‹空态$ink-faint 诚实,绝不预填›
│                                                                                                  │
│                                                                                  ─ 上下文 ───────── │
│                                                                                    MiniMax · 200k  │ ‹$ink-dim›
│                                                                                    ░░░░░░░░░░░░ 0%  │ ‹空槽$hairline›
│                                                                                    0 / 200k        │ ‹$ink-faint›
│                                                                                    ◌ 缓存 (无)      │ ‹空态$ink-faint›
│                                                                                  ─ 成本 ─────────── │
│                                                                                    ↑0 ↓0           │ ‹$ink-dim›
│                                                                                    $0.000 · 0.0s   │ ‹$ink-bright bold›
│                                                                                                  │
│                                                                                                  │
│                                                                                                  │
│                                                                                                  │
│ › 输入目标,或 / 开始命令_                                                                          │ ‹PromptArea 底$well · ›$eye-soft · 占位$ink-faint · 光标$eye-glow›
│ ◌ idle · 动作0 · ↑0 ↓0 · $0.000 · 0.0s · ctx 0%                    Esc 打断 · \↵ 换行 · ^C 退出 │ ‹StatusBar 底$abyss · ◌idle$ink-faint · 键提示$ink-faint›
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 状态 (b)——run 中 + 审批卡到达

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ◉ Argos  v0.3 · MiniMax-M3                                                       · act       LIVE │ ‹◉$eye act 注视眼 · LIVE$pass›
│                                                                                  ─ 进度 ────────── │ ‹右栏 act 视图›
│ ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌             ◉ act     ⠹ ··    │ ‹回合 dashed$hairline | ◉act$eye · spinner$eye›
│ › 帮我把 auth.py 改成 bcrypt 校验                                                ◔ plan   1.2s ◕   │ ‹用户行 ›$eye-soft 正文$ink-dim | 完成$ink-dim ◕$pass›
│ 我先读现有实现,确认在用 SHA-256,再替换为 bcrypt 并加盐。               ─ 工具 ────────── │ ‹散文$ink · inline code$eye›
│ 关键改动在 `verify_password` 与 `hash_password` 两处。                            read_file  ×2    │
│                                                                                   edit_file  ×1    │ ‹$ink/计数$ink-faint›
│ ⏺ python · step 2                                                              ─ 回执 ──────────── │ ‹⏺$eye · 标签$ink-dim›
│   pw = bcrypt.hashpw(raw, bcrypt.gensalt())                                       edit_file auth.py│ ‹Syntax monokai | $ink-dim›
│   └ ◕ 执行完成 · 0.4s                                                          ─ 上下文 ───────── │ ‹└$ink-faint ◕$pass | 墨蓄$eye·空$hairline›
│                                                                                   ████▌░░░░░░░ 34% │
│ │ Edit · auth.py  +3 −1                                                           68.0k / 200k     │ ‹diff 左缘$hairline-lit · path$eye · +$pass−$fail | $ink-faint›
│ │ − pw = sha256(raw).hexdigest()                                                  ├ sys 12k mem 4k │ ‹−行$fail | 四桶$ink-faint›
│ │ + pw = bcrypt.hashpw(raw, salt)                                                 缓存 18.2k ↘     │ ‹+行$pass | cache_read$cyan›
│                                                                                   ↯ 压缩 -22%      │ ‹CompactedEvent$ink-faint›
│   ◓ 审批请求 · medium — soft rule: ask git push                                ─ 成本 ─────────── │ ‹◓+标题$unverif bold | border-left thick$unverif›
│   git push origin main                                                            ↑12.4k ↓3.1k    │ ‹命令$ink-bright | $ink-dim›
│   run_command · {remote: origin, branch: main}                                    $0.013 · 4.2s   │ ‹元信息$ink-faint | $ink-bright bold›
│                                                                                   ▂▃▅▇▅▃ 18.2k     │ ‹cache sparkline$cyan›
│   ▸ 1  本次允许                                                                                   │ ‹▸$eye · label$ink-bright bold›
│     2  本会话允许    3  总是允许    4  拒绝                                                        │ ‹$ink-dim›
│                                                                                                  │
│   ↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 拒绝                                                          │ ‹$ink-faint · mount 时 app.bell()›
│                                                                                                  │
│ › _                                                                                              │ ‹PromptArea 焦点暂让审批卡 · 草稿不丢›
│ ◓ 审批挂起 · 动作3 · ↑12.4k ↓3.1k · $0.013 · 4.2s · ctx 34%       Esc 打断 · \↵ 换行 · ^C 退出 │ ‹◓审批挂起$unverif(优先级铁律:用户阻塞赢)›
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

> 注:StatusBar 左眼是 `◓ 审批挂起`(用户阻塞态赢),即便引擎在跑——右栏「进度」仍显 `◉ act` spinner。这是裁决的优先级铁律落地。

### 5.3 状态 (c)——verify 收尾四态并列

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ◕ Argos  v0.3 · MiniMax-M3                                                       · report    LIVE │ ‹◕$eye report 阅毕眼›
│                                                                                  ─ 裁决 ────────── │ ‹右栏 verify 视图›
│ ⏺ python · step 5                                                                  passed (强)     │ ‹⏺$eye·标签$ink-dim | passed$pass bold›
│   subprocess.run(["pytest","-x"])                                                  pytest -x        │ ‹$ink-dim›
│   └ ◕ 执行完成 · 1.9s                                                              12 passed         │ ‹└$ink-faint ◕$pass | $ink-dim›
│                                                                                  ─ 阶段耗时 ─────── │ ‹四阶段耗时表(机会点③)›
│ ◉ verify passed · pytest -x · 1 次尝试 → 12 passed                                 ◔ plan    1.2s   │ ‹◉+正文$pass · passed bold | $ink-dim›
│                                                                                    ◉ act     6.4s   │
│ ╌ ╌ ╌ 另三态对照(同一 run 不会同现,此处示形)╌ ╌ ╌                                ❂ verify  2.1s   │ ‹示意分隔$ink-ghost›
│                                                                                    ◕ report  0.3s   │
│ ◉ verify FAILED · pytest -x → 2 failed                                         ─ 审批汇总 ──────── │ ‹◉+正文$fail · FAILED bold 大写›
│   ⤷ 重试 3 次后仍 failed · test_login.py assert mismatch                          once 1 · deny 0  │ ‹注解$ink-faint | $ink-dim›
│ ◔ 无法验证 · verify_cmd 未注册(trivial 命令被拒)                              ─ 上下文 ───────── │ ‹◔+正文$unverif 橙(三重冗余)›
│                                                                                   ███████▌░░░░ 41% │ ‹墨蓄$eye›
│ ◍ 自验证通过(较弱) · 系统自造测试 → 3 checks ok                                   82.0k / 200k     │ ‹◍$pass-weak 去饱和绿›
│   ⤷ 非用户级 verify,未晋级技能                                                    缓存 31.4k ↘     │ ‹注解$ink-faint italic | $cyan›
│                                                                                   ↯ 压缩 -18%      │ ‹CompactedEvent$ink-faint›
│ ◕ run 完成 · 18.4s                                                             ─ 成本 ─────────── │ ‹done ◕$pass | title$eye-soft›
│                                                                                   ↑34.0k ↓8.2k    │ ‹$ink-dim›
│                                                                                   $0.041 · 18.4s   │ ‹$ink-bright bold›
│                                                                                   ▂▃▅▇▅▆ 31.4k     │ ‹cache sparkline$cyan›
│                                                                                                  │
│                                                                                                  │
│ › 输入目标,或 / 开始命令_                                                                          │ ‹PromptArea 焦点已还›
│ ◕ report · 动作5 · ↑34.0k ↓8.2k · $0.041 · 18.4s · ctx 41%        Esc 打断 · \↵ 换行 · ^C 退出 │ ‹◕report$eye · 数据$ink-dim›
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

> 注:真实 run 一次只产一个 verdict 态;mockup (c) 四态并列仅为展示"四态视觉如何互不混淆"。
> 行首扫一列即得真相:`◉`绿 passed / `◉`红 FAILED / `◔`橙 无法验证 / `◍`去饱和绿 自验证——形 + 色双轴。

---

## 6. 动效 spec

> 性能铁律:任何动效只改**单个字符或单个颜色属性**,绝不改宽度/换行/布局。CPU 几乎静止。

### 6.1 braille spinner(思考/执行中)

- **帧序列**:`⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏`(10 帧,braille,单格,EAW=N,v2 已验证)。
- **帧率**:8 fps(0.12s/帧,沿用 v2 节奏)。
- **色**:`$eye`;标签 `$ink-dim`;≥1s 追加实时秒数 `$ink-faint`(`⠹ 执行中… 4s`)。只重绘单格 + 秒数,无重排。
- **作用域**:ThinkingIndicator + 右栏 act 进度行(`◉ act  ⠹ ··`)。

**ThinkingIndicator DEFAULT_CSS**
```css
ThinkingIndicator { color: $eye; padding: 0 2; }
```
帧序列断言保持(`tests/test_thinking_indicator.py`),色 token 改 `$eye`。

### 6.2 眼慢眨 + glow 呼吸 + 告警锁色

- **眼慢眨(ThinkingIndicator 工作态 / splash 之眼)**:每 ~4s 一次 `◉→◓→◉`(裁决:两帧均 EAW=N)。慢于人静息呼吸,催眠感;仅 1 字符变化,零重排。
- **glow 呼吸边框(签名特性,保留)**:正弦插值,周期 ~3.2s。色阶 8 步在 `$eye-soft → $eye → $eye-glow → $eye → $eye-soft` 间:
  `#A8854A → #C39A54 → #D9A85C → #E6B468 → #F0C078 → #E6B468 → #D9A85C → #C39A54`。4 fps(250ms/步)。
- **告警锁色(陷阱#2 原文照录)**:`_terminal_glow 告警锁色逻辑原样保留` —— failed/unverifiable/Escalation/Error 置 `_terminal_glow=True` 后,**PhaseChange 的阶段色不得覆盖告警色**。漏判此标志 = 假绿效果 = 诚实红线事故。三态终态锁色:passed→绿锁 / failed→红锁 / unverifiable→橙锁,呼吸停。

### 6.3 睁眼仪式 + 阶段切换

- **睁眼仪式(启动一次性)**:StartupSplash 状态眼挂载瞬间播 `◌ → ◔ → ◓ → ◉` 四帧,每帧 0.12s(总 ~0.5s),**仅一次,非循环**。无 key 止于 `◌`(不睁开,诚实未就绪)。
- **阶段切换无过渡动画**(裁决:终端美德是瞬时):阶段眼(StatusBar / 右栏进度)切换时,旧字形 1 帧 `$ink-faint` → 新字形 `$eye`,250ms 一次性渐亮,无动画循环。
- **右栏视图智能切**:直接 `display` 切换(零重排,性能铁律),不做滑动/淡入;仅视图标题 `act` 字做一次 250ms 渐亮。
- **上下文水位条**:数值变化时尾部亚格(`▏▎▍▌▋▊▉`)一步到位渲染目标分数,**不逐帧动画**(精度来自亚字符,非动画)。
- **审批到达**:`app.bell()` 终端铃 + 卡片 mount(无动画)。

---

## 7. 窄屏降级

沿用既有 `HORIZONTAL_BREAKPOINTS` / `-narrow` 机制。

### 7.1 <90 列:右栏折叠

右栏(ActivityPanel)折叠,主流占满。成本 + ctx 降级进 StatusBar:
```
 ◉ act · 动作3 · $0.013 · ctx 34% · 缓存18k          Esc 打断 · \↵ 换行 · ^C 退出
‹眼$eye · 钱$ink-dim · ctx$ink-dim · 缓存$cyan · 键提示$ink-faint›
```
verdict / 审批 / diff 全部本就在主流,无损。

### 7.2 <80 列:StatusBar 只留 眼 + 阶段 + $成本 + ctx%

键提示裁掉(裁决:评审3 要的明确样例):
```
 ◉ act · $0.013 · ctx 34%
‹眼$eye · 阶段标签随眼 · $成本$ink-dim · ctx$ink-dim · 无键提示›
```
审批挂起时仍服从优先级铁律:`◓ 审批挂起 · $0.013 · ctx 34%`。

splash:<60 列 logo 降为单行 `◉ Argos`(ASCII 块字需 ≥48 列居中,不够则降级)。

---

## 8. 新接线需求

### 8.1 app.py `_apply_event` 新增 CompactedEvent / PrunedEvent 分支(现状无)

`app.py` 的 `_apply_event` 当前**无** `CompactedEvent` / `PrunedEvent` 的 isinstance 分支。新增两个分支(裁决机会点①):

```python
# 在 _apply_event 的 isinstance 链中追加:
elif isinstance(ev, CompactedEvent):
    # 1. 右栏上下文区追加压缩行
    self._activity.on_compacted(ev.before, ev.after, ev.reduction_pct)
    # 2. transcript 系统行(faint,不喧宾)
    await log.append_line(f"◌ 已压缩 -{ev.reduction_pct:.0f}% · {ev.before}→{ev.after} 条", kind="system")
elif isinstance(ev, PrunedEvent):
    self._activity.on_pruned(ev.before, ev.after, ev.removed)
    await log.append_line(f"◌ 已修剪 {ev.removed} 条", kind="system")
```
- `on_compacted` / `on_pruned` 是 ActivityPanel 纯新增方法(§4.8 c),用 `except: pass` 兜底(陷阱1 模式)。
- 右栏渲染:上下文区 `↯ 已压缩 -22% · 12→4 条`(`$ink-faint`)。

### 8.2 缓存 + 四桶接线(机会点②④)

- `CostUpdate.cache_read` 已存在但 ActivityPanel 未渲染 → `on_cost(...)` 内部新增 cache sparkline + `缓存 N tok ↘`(`$cyan`)渲染;若 `on_cost` 签名已含 cache_read 则**复用,不改签名**。
- `ContextBreakdown` 四桶(system/memory/tools/messages)→ `on_context(...)` 内部新增四桶 `├ sys ... · mem ...`(`$ink-faint`,health 色随占比借 `$pass/$unverif/$fail`);若需新数据,加 `on_context_breakdown(breakdown)` 纯新增方法。

### 8.3 记忆召回提示行(机会点⑤)

`loop._drive` 已调 `memory.recall(goal, k=3)` 但 TUI 无提示。run 开始时:
```python
# app.py run 启动路径(召回结果可得处):
hits = len(recalled)   # recalled 来自 loop 已召回的记录
if hits:
    await log.append_line(f"◌ 记忆召回 {hits} 条", kind="system")  # $ink-faint,一行,不喧宾
    self._activity.on_memory_recall(hits)   # 右栏 Run 区段显 ◌ 召回 N 条
```

### 8.4 StatusBar 渲染优先级状态机(裁决铁律)

StatusBar 内部维护优先级状态机(用户阻塞 > 告警锁色 > 阶段),`render()` 按此选左眼与整条色:

```python
def _resolve_render_state(self) -> tuple[str, str]:
    """返回 (左眼 glyph, css 类)。优先级:用户阻塞 > 告警锁色 > 阶段。"""
    if self._blocked:                       # 审批挂起——用户阻塞,永远赢
        return "◓", "-blocked"              # $unverif,即便 phase==verify
    if self._alert:                         # _terminal_glow 告警锁色(陷阱2 联动)
        eye = self._phase_eye()             # 眼仍随阶段,但整条锁红/橙
        return eye, "-alert"
    # 其次阶段眼
    return self._phase_eye(), self._ctx_class()  # ctx 压力类叠加
```
- `set_blocked(active)`:`_handle_approval` mount 审批卡时置 True,决策后置 False。
- `set_alert(active)`:与 `_terminal_glow` 同源(failed/unverifiable/escalation/error 置 True,新 run 或 phase=plan 清)。
- `_phase_eye()`:`{plan:◔, act:◉, verify:❂, report:◕, idle:◌}`。

---

## 9. 施工分解表

> 9 个施工包,**文件不相交**。`theme.py` 是第一包(其他包全依赖 token);`app.py 接线`是最后一包。
> 每包标注:负责文件 · 依赖包 · 要改的测试 · 验收命令 · 规模(S/M/L)。
> 全量基线:重设计前 1976 passed / 4 skipped / 81.34%。覆盖率门禁是全量 suite 的事,子集低是预期。

| # | 包名 | 负责文件 | 依赖 | 要改的测试 | 验收命令 | 规模 |
|---|---|---|---|---|---|---|
| **P1** | **theme.py token 体系** | `argos_agent/tui/theme.py` | 无(根基) | `tests/test_tui_theme.py`(hex 断言更新为黑曜石值 + 新 token 存在性断言) | `uv run pytest tests/test_tui_theme.py -q` | **M** |
| P2 | TopBar + StartupSplash(睁眼仪式) | `argos_agent/tui/widgets/top_bar.py`、`argos_agent/tui/widgets/splash.py` | P1 | `tests/test_top_bar.py`、`tests/test_splash.py`、`tests/test_splash_no_key.py`、`tests/test_splash_permissions_banner.py`:logo 末态眼、`has_key=False` 无 LIVE(契约6)、徽标色 | `uv run pytest tests/test_top_bar.py tests/test_splash.py tests/test_splash_no_key.py tests/test_splash_permissions_banner.py -q` | M |
| P3 | Transcript 三行 + CodeActionBlock + ThinkingIndicator | `argos_agent/tui/widgets/transcript.py`(含 UserMessage/AssistantMessage/SystemLine)、`argos_agent/tui/widgets/code_action.py`、`argos_agent/tui/widgets/thinking.py` | P1 | `tests/test_transcript_widget.py`、`tests/test_thinking_indicator.py`、`tests/test_tui_markup_safety.py`(行为不动):系统行前缀/折叠/⏺保留/spinner 帧 | `uv run pytest tests/test_transcript_widget.py tests/test_thinking_indicator.py tests/test_tui_markup_safety.py -q` | M |
| P4 | DiffView + VerdictBadge(四态) | `argos_agent/tui/widgets/diff_view.py`、`argos_agent/tui/widgets/verdict_badge.py` | P1 | `tests/test_diff_view.py`、`tests/test_verdict_badge.py`:四态前缀眼/verdict-self 类/detail+cmd+attempts/契约7类名 | `uv run pytest tests/test_diff_view.py tests/test_verdict_badge.py -q` | M |
| P5 | InlineChoice 审批卡 | `argos_agent/tui/widgets/inline_choice.py` | P1 | `tests/test_inline_choice.py`(视觉更新:标题◓/自毁◕/⚠︎secret/风险色);`tests/test_tui_approval.py` 行为契约**只读不改** | `uv run pytest tests/test_inline_choice.py tests/test_tui_approval.py -q` | M |
| P6 | ActivityPanel(34列+四列网格+四桶+sparkline+compaction渲染) | `argos_agent/tui/widgets/activity_panel.py` | P1 | `tests/test_activity_panel.py`、`tests/test_tui_activity_panel.py`、`tests/test_smart_panel_views.py`:width34/overflow_y auto(契约8)/四桶+sparkline+◌空态;**全12+方法签名保持**(陷阱1) | `uv run pytest tests/test_activity_panel.py tests/test_tui_activity_panel.py tests/test_smart_panel_views.py -q` | **L** |
| P7 | StatusBar(状态眼+优先级状态机) | `argos_agent/tui/widgets/status_bar.py` | P1 | `tests/test_status_bar.py`:阶段眼映射/set_blocked◓优先/set_alert锁色/ctx-warn | `uv run pytest tests/test_status_bar.py -q` | M |
| P8 | SlashMenu + PromptArea + TabStrip | `argos_agent/tui/widgets/prompt.py`(PromptArea+SlashMenu 同文件)、`argos_agent/tui/widgets/tab_strip.py` | P1 | `tests/test_tui_tab_strip.py`(emoji→⏵⏸⏹/active 底色块);`tests/test_tui_commands.py` 行为**只读不改**;PromptArea/SlashMenu 相关测试用 `grep -rl "SlashMenu\|PromptArea" tests/` 定位 | `uv run pytest tests/test_tui_tab_strip.py tests/test_tui_commands.py -q` | S |
| **P9** | **app.py 接线 + 跨切测试清扫(最后一包)** | `argos_agent/tui/app.py` + 跨切测试文件 | P2–P8 全部 | `tests/test_tui_wiring.py`、`tests/test_tui_smoke.py`、`tests/test_tui_run_integration.py`、**`tests/test_tui_widgets.py`(P3/P4/P7 视觉断言统一在此清扫)**:Compacted/Pruned 新分支、记忆召回行、StatusBar 优先级联动、_terminal_glow 不被阶段覆盖(陷阱2) | `uv run pytest tests/ -q`(全量) | **L** |

**包间纪律:**
- P1 必须先合(token 是全体依赖);P9 必须最后合(接线依赖全部组件)。
- P2–P8 **源文件**不相交,可并行施工(各自只改自己的 widget 文件 + 自有测试)。
- **测试文件所有权铁律**:跨切测试文件(`tests/test_tui_widgets.py`、`tests/test_tui_run_integration.py`、`tests/test_tui_wiring.py`、`tests/test_tui_smoke.py`)横跨多个包,**P2–P8 一律不得修改**,统一归 P9 清扫——避免并行撞车。P2–P8 验收命令里也不要跑这些文件(中间态预期红)。
- 每包完成:`uv run pytest tests/<相关文件> -q` 全绿才算完;视觉快照断言随新设计更新,行为契约断言**不动语义**。
- P9 合并后跑全量 `uv run pytest`,对齐基线 ≥1976 passed,覆盖率 ≥80%(门禁)。
- `tests/test_tui_sync_output.py` 全程保持全绿(契约11,sync_output 在途功能,任何包不得破坏 BSU/ESU finally 安全契约与 probe 缓存)。

---

## 10. 不可破契约附录

### 10.1 行为契约 11 条(从 /tmp/argos-impl-context.md 照录)

1. EventBus frozen dataclass + kind snake_case;全局唯一 EventBus 定义在 `tui/events.py`。
2. `ApprovalGate.respond` 四级决策(deny/once/session/always);`Decision.approved` 语义。
3. InlineChoice:幂等、FIFO 队列、`_finish` 不双发。
4. Transcript:`finalize_response` 开新气泡;`append_token` 剥 ``` 围栏;不自动拽回用户滚动位置。
5. `UserMessage._render_markup is False`(markup 注入安全)。
6. StartupSplash 诚实徽标:`has_key=False` 时绝不出现 "✳ LIVE"(v3 中即"LIVE"字样,见 §4.1/§4.2)。
7. VerdictBadge 三个 CSS 类名不许改:`verdict-passed` / `verdict-failed` / `verdict-unverifiable`(v3 仅新增 `verdict-self`)。
8. `ActivityPanel.styles.overflow_y == "auto"`;`_hook_log maxlen=50`。
9. Kitty 键盘协议默认禁用(`TEXTUAL_DISABLE_KITTY_KEY=1`)。
10. E4 防火墙:`self_verified=True` 的 passed 是「弱通过」,视觉上绝不可与用户级强通过混淆(v3:`◍` 格纹瞳 + 去饱和绿 + italic 注解 + 强制"未晋级"第二行,四重区分)。
11. `tui/sync_output.py` 是在途功能:BSU/ESU finally 安全契约与 probe 缓存行为不得破坏,其测试 `tests/test_tui_sync_output.py` 必须保持全绿。

### 10.2 三个隐性陷阱(从 /tmp/argos-impl-context.md 照录)

1. **ActivityPanel 契约面**:`app.py` 以 `query_one("#activity", ActivityPanel)` 硬编码 id,12+ 个调用方法(`on_phase`/`on_plan`/`on_receipt`/`on_cost`/`on_context`/`on_verdict`/`on_hook_fired`/`on_lsp_*`/`on_run_summary`/`on_approval_decision`/`reset_run`/`set_view`/`cycle_view`)全部被 `except: pass` 包住——改名/改签名会**静默失败**。保持方法签名,只改内部渲染。
2. **`_terminal_glow` 告警锁色**:failed/unverifiable/Escalation/Error 置 `_terminal_glow=True` 后,PhaseChange 的阶段色不得覆盖告警色。漏判此标志 = 假绿效果 = 诚实红线事故。(对应 StatusBar 优先级状态机 §8.4 的 `-alert` 态。)
3. **InlineChoice 时序**:`_handle_approval` 的 `_decide` 回调是同步的;`gate.respond` 必须先于 `_choice_done()`;回调内 async 操作必须 `run_worker` 包住,否则 Textual worker 外 await 死锁。

---

*「黑曜石之眼」设计系统定稿完。一只眼说话(七姿态状态机)· 三层黑曜石纵深 · 金橙分家 · 四态诚实瞳(绿/红/橙/格纹去饱和绿)· 右栏四列仪表网格 · 六机会点 · 全等宽 glyph(⚠︎ VS15 铁律)· 9 施工包文件不相交。让用户扫一列行首即得全部真相——这就是 Argos 该有的样子。*
