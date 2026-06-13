# Skills curator — 设计规格(spec)

> Road-map entry **#10** "Skills curator (中等,扩 skill 生态)" 的设计规格。
> 估时 2-3 天,中等。**灵魂对齐**"让便宜模型可靠"——不是"我有 60+ skill"的数字游戏,
> 而是 **dogfooding skill 生态本身**:Argo 本身就有 3 个 builtin skill(verify /
> security-review / simplify),本 spec 解决"用户怎么发现/装/测/信任/卸载/被推荐
> 第三方 skill"——和"verify 门 + 诚实协议"一样,把 skill 生态做成**可观察可量化可治理**
> 的闭环,而不是黑盒 marketplace。

## 1. 背景与现状

- **v0.1.0 已发**,1409 测试绿。`#5b` 多 run tabs / `#7` agent eval / `#9` 自动记忆 /
  `verify 硬门禁` / 篡改检测 / smart approval / workflow 编排都已就位,33 个未推送 commit。
- **当前 skill 系统**(3 层,各司其职,本 spec 只扩展,**不**改):
  1. `argos/skills.py`(旧):markdown skill 仓库,**关键字/embedding 召回**——给 LLM
     提示用(7 个 builtin .md + 1 个用户目录 `~/.argos/skills/`)
  2. `argos/skills_runtime/`(新):`AnalysisSkill` 抽象 + 3 个 on-demand
     原语(`/verify` / `/security-review` / `/simplify`),slash 命令触发,事件流跑
  3. `argos/skills_builtin/`(新):3 个 skill 的 SKILL.md 描述文件
- **当前缺口**:
  1. **没有"发现"** —— 用户怎么知道有哪些可用 skill?翻 `skills_builtin/` 目录?
  2. **没有"安装"** —— 想加一个社区 skill(比如 `python-lint-skill`),
     只能 `cp` 到 `~/.argos/skills/`?没 sha256 校验、没 capability 声明、没来源
  3. **没有"评测"** —— 装个 skill 后不知道它**到底干不干**,只信作者 README
  4. **没有"安全"** —— skill 装上就跑?没 `read/write/network` 声明、没审批闸、没 SKILL.md
     复核确认
  5. **没有"推荐"** —— 用户编 Python → 不知道有 `python-lint-skill`;跑失败测试 → 不知道
     有 `test-debugger-skill`;skill 之间无主动触发
- **风险**:
  1. skill 一旦装就能跑所有工具(沿用 `AnalysisSkill.run` 路径),如果作者写了
     `os.system("rm -rf /")`,被 LLM 触发即爆炸——**不**比 MCP 工具调用更安全
  2. 安装来源不可信(没有 sha256 + 来源 URL),index 被劫持 → 装的就是后门
  3. 用户开了"自动跑 skill",新装 skill 自动调用,等于开了个"自动执行第三方代码"开关
- **灵魂**:不跟 LangChain/LlamaIndex 拼"我有 marketplace"(他们也没有),不跟 CC 抄
  "skill 是 markdown" 而不管运行时;而是做"我有 sha256 校验 + capability 声明 +
  smoke test + 审批闸 + 推荐启发式"——这是别人**没治理**所以**没生态**的护城河。

## 2. 目标与非目标

### 2.1 目标(本期)

1. **Curated index**:`~/.argos/skills/index.json` 本地缓存 + 远程源
   `https://raw.githubusercontent.com/tungoldshou/argos-skills-index/main/index.json`
   2. **install / remove / list / refresh** CLI 4 件套(`argos skills {install,remove,list,refresh}`)
   3. **TUI `/skills` slash 命令** —— 列 installed + available,带 capability 徽章
   4. **sha256 校验** —— index 写入前 verify,失败拒
   5. **capability 声明** —— SKILL.md frontmatter 加 `capabilities: [read, write, network]`
      缺则只 read
   6. **user review gate** —— install 后**不**自动激活,要求用户 `cat ~/.argos/skills/<n>/SKILL.md`
      后**手动** `enabled: true`(防"装了就能跑")
   7. **smoke test** —— `argos skills test <name>` 跑该 skill 自带 `tests/smoke.md`
      (若无,跑通用 sandbox 探针:打印 hello)
   8. **推荐引擎(启发式)** —— 基于 session 活动:Python 文件编辑 → 推荐 `python-lint`;
      失败测试 → 推荐 `test-debugger`;安装 ≥2 次 → 推荐 `git-commit-hygiene` 等
   9. **0 新外部依赖**(stdlib only:`urllib.request` + `json` + `hashlib` + `subprocess` +
      `dataclasses`)
   10. **不**触碰 `skills_runtime/`(只读,扩展由它注册/调);**不**改 `skills.py`(skill 召回
       由它独立管);**不**改 `approval.py`(审批逻辑沿用)

### 2.2 非目标(本期不做)

- ❌ **marketplace 平台** —— 没服务端,没付款,没评分后端,没评论——就一个
  `index.json` 文件托管在 GitHub
- ❌ **skill 自动更新** —— 装后**不**自动升;用户手动 `skills refresh && skills install <n>`
  重新装新版
- ❌ **LLM 自动生成 skill** —— skill 由人写,LLM 只能"调用"——和 corpus 一样
  防"我生我测我多聪明"循环
- ❌ **跨设备同步 / 加密备份** —— 本期本地配置,无 iCloud 同步
- ❌ **skill 私有 server(自托管)** —— 暂只 GitHub raw;企业版留 v1.1
- ❌ **skill marketplace 评价 / 投票** —— 暂 trust score = 自动 smoke test 通过率
- ❌ **skill 自带二进制依赖** —— SKILL.md 只能配 markdown + 文本;**不**支持 `binary/`
  目录(简化打包)
- ❌ **热加载 / 运行时安装立即生效** —— install 后需重启 TUI 才生效(避免半状态)
- ❌ **安装同名前置覆盖 builtin** —— `verify` / `security-review` / `simplify` 三个
  builtin 名被**保留**,用户装同名 → 警告 + 不允许(护城河基础组件,不能被社区覆盖)

## 3. 架构总览

```
                ┌──────────────────────────────────────┐
                │   argos skills refresh | list |      │
                │   install <name> | remove <name> |   │
                │   test <name>                        │
                │   (CLI,__main__.py subcommand)       │
                │   ──────────────────────────────     │
                │   /skills · /skills install <n> ·    │
                │   /skills remove <n>                 │
                │   (TUI slash,tui/commands.py)        │
                └──────────────┬───────────────────────┘
                               │ IndexEntry | SkillCard
                               ▼
              ┌────────────────────────────────────────┐
              │       skills_curator/                   │
              │                                        │
              │  index.py ─── 远端 index.json + 缓存    │
              │              + sha256 verify           │
              │  install.py ─ fetch SKILL.md + 校验    │
              │               + 落盘 ~/.argos/skills/  │
              │  remove.py  ─ 删目录 + 取消 enabled     │
              │  smoke.py   ─ 跑 skill 自带 smoke test  │
              │  capabilities.py ─ 解析 + 校验 frontmatter │
              │  recommend.py ─ session 活动启发式      │
              │  cli.py  ── argos skills 子命令         │
              └──────────────┬─────────────────────────┘
                               │
                               ▼
              ┌────────────────────────────────────────┐
              │  ~/.argos/skills/                       │
              │   ├── index.json          (cache)       │
              │   ├── index.json.sha256   (signature)   │
              │   └── <name>/             (installed)   │
              │        ├── SKILL.md       (capabilities │
              │        │                  frontmatter) │
              │        ├── tests/                       │
              │        │   └── smoke.md   (可选)       │
              │        └── reviews/                     │
              │            └── <user>.md (用户手写回顾)│
              └─────────────────────────────────────────┘
```

**关键不变量**:
- **本地 cache = 远端 index.json 的副本,只读,带 .sha256** —— 离线仍能 `skills list`
- **SKILL.md 是 single source of truth** —— index 只放摘要(name/version/author/sha256/description
  /capability),不重复 SKILL.md 内容
- **capability 在 SKILL.md frontmatter 声明** —— index 里的 capability 字段 = 远端
  index 作者手维护(防被 SKILL.md 改的 index 撒谎)
- **install 完默认 `enabled: false`** —— 强制 user review `~/.argos/skills/<n>/SKILL.md` 后
  改 frontmatter `enabled: true`,下次 `recall()` 才召回
- **不重写 skill runtime** —— `skills.py` 继续 markdown 召回(对 LLM 提示);`skills_runtime/`
  继续 `AnalysisSkill` 编排(对 slash 触发);curator 专管**装卸**

## 4. Index 设计

### 4.1 远端 index.json(只读,GitHub 托管)

```json
{
  "version": 1,
  "generated_at": 1717700000.0,
  "skills": [
    {
      "name": "python-lint",
      "version": "0.2.1",
      "author": "tungoldshou",
      "sha256": "a3f5e9c1d2b4...",
      "description": "Python 文件改动后跑 ruff + mypy + 短测试,识别 lint/类型/回归 3 类问题。",
      "skill_md_url": "https://raw.githubusercontent.com/tungoldshou/argos-skills-index/main/python-lint/0.2.1/SKILL.md",
      "compatibility": ">=0.1.0",
      "capabilities": ["read", "execute"],
      "size_bytes": 4210
    },
    {
      "name": "test-debugger",
      "version": "0.1.3",
      ...
    }
  ]
}
```

### 4.2 本地缓存

```
~/.argos/skills/
├── index.json                  # 远端副本 + 生成时间戳
├── index.json.sha256           # 远端 index 原始 sha256(对账)
└── <name>/
    ├── SKILL.md                # 装时下载,frontmatter 含 name/description/capabilities/version
    ├── tests/
    │   └── smoke.md            # (可选)作者自带的 smoke test
    └── reviews/
        └── <username>.md       # (可选)用户手写 review;不进 LLM 提示
```

### 4.3 字段约束

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `name` | str | 是 | `^[a-z][a-z0-9-]{2,32}$`,且**不**与 builtin 三个名冲突 |
| `version` | str | 是 | semver `^\d+\.\d+\.\d+(-[a-z0-9.]+)?$` |
| `author` | str | 是 | `^[a-z0-9-]{2,32}$` |
| `sha256` | str | 是 | 64 hex;装时下载 SKILL.md 后**重新**算,匹配才落 |
| `description` | str | 是 | ≤ 280 字符 |
| `skill_md_url` | str | 是 | `https://` 开头,host ∈ `{raw.githubusercontent.com, gist.githubusercontent.com}` |
| `compatibility` | str | 是 | semver range;arg os 当前版本**不**在范围 → 装时警告 |
| `capabilities` | list[str] | 是 | 元素 ∈ `{read, write, execute, network}` |
| `size_bytes` | int | 是 | 装时校验下载字节数,差距 > 20% 警告(可能 index 撒谎) |

### 4.4 refresh 策略

- **CLI**:`argos skills refresh` → 拉远端 → 校验 sha256(对账,远端 meta 给的)→ 覆盖
  本地 `index.json`
- **7 天缓存**:本地 `index.json` mtime > 7d → TUI `/skills` 头部显 "index stale (last refresh 8d ago),运行 `skills refresh`"
- **离线 fallback**:网络失败 → 用本地 `index.json`(可能 stale)
- **远端 schema 升 version** → `index.json` 顶层 `version: 2` → 本地解析器 unknown field
  不报错,只忽略多余字段

## 5. Install / Remove / Test 流程

### 5.1 `argos skills install <name>`

```
1. argos skills refresh                                    # 自动,除非 --no-refresh
2. index = load_index()                                    # ~/.argos/skills/index.json
3. entry = index.skills[<name>]                             # 不在 → NameError 友好提示
4. if entry.name in {"verify","security-review","simplify"}: raise ProtectedSkillError
5. tmp = download_to_temp(entry.skill_md_url)               # ~100KB 限
6. actual_sha = sha256(tmp.content)
7. if actual_sha != entry.sha256: raise ShaMismatchError
8. if len(tmp.content) != entry.size_bytes * (0.8..1.2): warn("size drift")
9. parse frontmatter → 校验 capabilities ∩ {read, write, execute, network}
10. if "network" in capabilities: ask("该 skill 声明会发网络流量,装? [y/N]")
11. target = ~/.argos/skills/<name>/SKILL.md
12. mkdir -p target.parent
13. write(target, tmp.content)                              # 默认 enabled: false
14. print("[skills] installed to ~/.argos/skills/<name>/")
15. print("[skills] review the SKILL.md before enabling:")
16. print(f"        $ cat {target}")
17. print("[skills] to enable, edit frontmatter: enabled: true")
18. run smoke test if tests/smoke.md exists                 # 单独 step;install 主动
    跑(quick path) → 失败仅警告,不阻止 install
```

### 5.2 `argos skills remove <name>`

```
1. if <name> in {"verify","security-review","simplify"}: raise ProtectedSkillError
2. target = ~/.argos/skills/<name>/
3. if not target.exists(): raise NotInstalledError
4. parse SKILL.md frontmatter → 拿到 sha256(供回执)
5. shutil.rmtree(target)
6. print("[skills] removed ~/.argos/skills/<name>/")
7. 提示:"下次 /skills 不再列出;记忆回执保留 30 天 ~/.argos/skills/.trash/<name>.json"
```

### 5.3 `argos skills test <name>`

```
1. skill = ~/.argos/skills/<name>/
2. if not exists: raise NotInstalledError
3. parse SKILL.md frontmatter
4. if (skill / "tests" / "smoke.md").exists():
      run as bash:  cat smoke.md | argos --demo --project <tmp>
      collect exit_code + last 50 lines
5. else:
      # 通用 sandbox 探针:echo 探针
      write tmp probe = "echo 'arg os smoke probe: PASS'"
      run with `argos --demo --project <tmp> --goal "echo 'PASS'"`
      collect exit_code
6. if exit_code == 0: print(f"[skills] {name}: PASS"); return 0
   else: print(f"[skills] {name}: FAIL (exit={exit_code})"); return 1
```

### 5.4 `argos skills list`

```
1. index = load_index()
2. installed = scan ~/.argos/skills/*.md  (含 builtin 三个)
3. for each in index.skills:
      status = "installed" if ~/.argos/skills/<n>/ exists else "available"
      trust = "builtin" if n in BUILTIN_NAMES else "user"
      if installed: read SKILL.md frontmatter; show enabled flag
4. print table:
   name              version   author        capabilities        status      enabled
   verify            builtin   argos         [read, execute]     installed   ✓
   security-review   builtin   argos         [read]              installed   ✓
   simplify          builtin   argos         [read]              installed   ✓
   python-lint       0.2.1     tungoldshou   [read, execute]     installed   ✗
   test-debugger     0.1.3     community     [read, execute]     available   -
```

### 5.5 enabled flag 流转

| 状态 | 文件位置 | `recall()` 召回? | `/skills` 列表? |
|---|---|---|---|
| 装完默认 | `~/.argos/skills/<n>/SKILL.md` (frontmatter `enabled: false`) | **不** | 显 `(disabled)` 徽章 |
| user review 完 | 同上,改 `enabled: true` | **是** | 显 `(enabled)` 徽章 |
| 装后从未打开 | 同上 | **不** | 显 `(unreviewed)` 徽章 |
| remove 后 | 目录删除 | **不** | **不**出现(进 trash 但不进 list) |

> 强调:**user review 是显式动作**,不是"装后自动 enabled"。这条是 spec 灵魂——
> 和 verify 硬门禁一样,把"我能不能信这个 skill"的选择权**交回给用户**。

## 6. Safety 设计(spec 灵魂)

### 6.1 5 道防线

1. **sha256 校验** —— 下载 SKILL.md 后**重算**,与 index 声明的 sha256 不一致 → **拒装**
2. **size drift 检测** —— 下载字节数与 `size_bytes` 偏差 > 20% → 警告(可能 index 撒谎)
3. **capability 声明** —— SKILL.md frontmatter 必填 `capabilities: list`,缺则拒装
4. **user review gate** —— 装后默认 `enabled: false`,需用户手动改 frontmatter
5. **approval gate 集成** —— skill 跑时若声明 `execute` 或 `network` capability,
   走 `ApprovalGate.request`(沿用 #8),不弹 modal → 沿用 smart approval evaluator

### 6.2 capability 详细语义

| capability | 含义 | 默认 user review 状态 | 跑时是否弹审批 |
|---|---|---|---|
| `read` | 读 workspace 文件,不改,无 shell | 装后**自动** enabled(只读是低风险) | 不弹 |
| `execute` | 跑 shell 命令(白名单 sandbox) | 装后 `enabled: false`,需 user review | **弹**(沿用 approval gate) |
| `write` | 改 workspace 文件 | 装后 `enabled: false`,需 user review | 弹 |
| `network` | 发 http(s) 请求 | 装后 `enabled: false`,需 user review + 装时再问一次"该 skill 声明会发网络,装?" | 弹(per-call) |

**为什么 read 是默认 enabled**:和 `recall()` 路径一致——skill 描述 + 关键词命中即被
LLM 提示,**不**需要 approve;真正副作用发生在 `execute`/`write`/`network` 上。

### 6.3 builtin 3 个被保护

`verify` / `security-review` / `simplify` 三个 builtin **不**能被 `install` 同名覆盖,
**不**能被 `remove` 删。原因:它们是 verify 硬门禁的核心组件,是 spec 灵魂的"基础
信任根",社区 skill 装不能破坏本地完整性的最低保证。

### 6.4 失败模式

| 失败 | 行为 |
|---|---|
| index 网络 404 | 装报错 `index_unavailable`,建议先 `skills refresh` |
| sha256 不匹配 | 装报错 `sha_mismatch: expected=X actual=Y`,不写盘 |
| size drift > 20% | 装继续 + 警告 "size mismatch (expected 4200, got 5400) — index may be stale" |
| capabilities 字段缺 | 装报错 `capabilities_required: frontmatter 缺 capabilities 字段` |
| capabilities 含未知值 | 装报错 `capability_invalid: foo ∉ {read, write, execute, network}` |
| name 与 builtin 冲突 | 装报错 `protected_skill: <name> is builtin and cannot be overridden` |
| 安装时网络断 | 装报错 `network_error: <url> <reason>`,tmp 文件清理 |
| SKILL.md frontmatter 解析失败 | 装报错 `frontmatter_invalid: <reason>`,不写盘 |
| smoke test 失败 | 装继续 + 警告 "smoke test FAIL (exit=N) — review SKILL.md before enabling" |
| remove builtin | 报错 `protected_skill: <name> is builtin and cannot be removed` |
| remove 不存在 | 报错 `not_installed: <name>` |

## 7. TUI 集成

### 7.1 `/skills` 无参

```
> /skills
─────────────────────────────────────────
Installed skills (4)

  ✓ verify            builtin   [read, execute]   0.1.0
  ✓ security-review   builtin   [read]            0.1.0
  ✓ simplify          builtin   [read]            0.1.0
  ✗ python-lint       user      [read, execute]   0.2.1  (unreviewed)

Available from index (2, last refresh 1d ago)

  ◌ test-debugger     community  0.1.3  [read, execute]   "失败测试后跑"
  ◌ git-commit-hygiene community 0.0.4  [read, write]     "commit 前 lint"

Recommended for this session (1)

  ⭐ test-debugger   — 最近 run 有 2 次 pytest 失败
─────────────────────────────────────────
```

### 7.2 `/skills install <name>`

TUI 模式:不直接装(TUI 是 ephemeral 状态),落 transcript 提示用户**到终端跑**
`argos skills install <name>`,装完 TUI 下次启动 `recall()` 才会看到。

**为什么不 TUI 内直接装**:install 涉及写磁盘 + 跑 smoke test + 弹确认(网络 capability),
TUI 是 LLM 流式输出界面,不是 terminal——把副作用推到 host CLI 更稳。

### 7.3 `/skills remove <name>`

同 install,落 transcript 提示用户到终端跑 `argos skills remove <name>`。

### 7.4 `/skills refresh`

同 install,落 transcript 提示用户到终端跑 `argos skills refresh`。

### 7.5 与现有 `/skills` 命令的兼容性

- 现有 `/skills` 在 `tui/commands.py` 显"列出可用技能"
- **本期替换**为新命令(同时保留 `recall` 的子路径,如果 arg 已存在则不破坏)
- COMMAND_HELP 更新:`"skills": "管理 skill:list / install / remove / refresh (跑 argos skills ...)"`

### 7.6 推荐 1 行嵌入 transcript

`/skills` 输出的 "Recommended" 段**不**自动装;只显"基于你最近的活动,可能想装 X,
跑 `argos skills install x`"——和 verify 门一样,把决定权**交回用户**。

## 8. 推荐引擎(启发式)

### 8.1 触发时机

- **每次 `/skills` 触发**:`recommend.recommend(session_activity)` → top-3
- **不**自动跑推荐(防"我在干活时被打断"——和 verify 门一样,用户主动查询)

### 8.2 session_activity 字段

```python
@dataclass(frozen=True, slots=True)
class SessionActivity:
    files_edited: tuple[str, ...]      # 路径列表,如 ["src/foo.py", "tests/foo_test.py"]
    verify_failures: int               # 本 session verify 失败次数
    commands_run: tuple[str, ...]      # shell 命令列表
    tools_called: tuple[str, ...]      # 工具名列表
    skill_invocations: tuple[str, ...] # 调过的 skill 名
```

### 8.3 启发式规则(13 条)

| 规则 | 条件 | 推荐 |
|---|---|---|
| R1 | files_edited 含 `*.py` 路径 ≥ 3 | `python-lint` |
| R2 | files_edited 含 `tests/test_*.py` ≥ 1 | `test-debugger` |
| R3 | verify_failures ≥ 1 | `test-debugger` |
| R4 | verify_failures ≥ 3 | `simplify` (builtins) + `test-debugger` |
| R5 | files_edited 含 `*.ts` / `*.tsx` ≥ 2 | `ts-lint` |
| R6 | files_edited 含 `*.sql` ≥ 1 | `sql-query-safety` |
| R7 | commands_run 含 `git commit` ≥ 1 | `git-commit-hygiene` |
| R8 | tools_called 含 `web_search` ≥ 1 | `web-search-recipe` |
| R9 | skill_invocations 含 `/security-review` ≥ 1 | `security-review-extended`(v1.1 装) |
| R10 | files_edited ≥ 5 个不同后缀 | `simplify`(提示"项目大了,跑下死代码扫描") |
| R11 | verify_failures ≥ 2 且 tools_called 含 `edit_file` ≥ 5 | `test-debugger` + 提示 "看起来在调试中" |
| R12 | session ≥ 30 步 | `simplify`(提示"长 session,扫一下死代码") |
| R13 | 用户手动 `/remember <preference>` 含 "lint" | 推 `python-lint`(v1.1 接入 memory) |

### 8.4 推荐去重

- 已装 + 已 enabled → 不推荐
- 已装 + 未 enabled → 显 "unreviewed, review SKILL.md to enable"
- 不在 index → 静默忽略(可能 skill 已下架,或作者未注册)

### 8.5 评分

```python
score = sum(weight[rule] for rule in matched_rules)
```
默认 weight 全部 1.0;v1.1 接记忆后,根据 user 接受/拒绝推荐反馈调权。

## 9. 持久化设计

### 9.1 路径规约

```
~/.argos/skills/
├── index.json                  # 远端 index 副本
├── index.json.sha256           # 远端 index 原始 sha256
├── .trash/                     # remove 后 30 天可恢复
│   └── <name>/
│       ├── SKILL.md
│       ├── removed_at: float
│       └── reason: str
├── verify/                     # builtin(SKILL.md 镜像自 skills_builtin/)
│   └── SKILL.md
├── security-review/            # builtin
│   └── SKILL.md
└── simplify/                   # builtin
    └── SKILL.md
```

### 9.2 为什么不用 sqlite / daemondb

- skill 列表是冷数据(用户**不**频繁操作),JSON 文件读全量 1ms 内,无 sqlite 必要
- 沿用 `#5a` / `#7` / `#9` 风格(JSON + 文件树),不引新 dep
- `.trash/` 30 天 prune 在每次 `skills list` 时检查(无后台 scheduler)

## 10. CLI 子命令

### 10.1 `argos skills refresh`

```bash
$ argos skills refresh
[skills] fetching https://raw.githubusercontent.com/tungoldshou/argos-skills-index/main/index.json ...
[skills] received 12.3 KB in 1.4s
[skills] sha256 ok (expected=a3f5e9c1..., actual=a3f5e9c1...)
[skills] index updated: 14 skills (2 new, 0 removed, 1 updated)
```

### 10.2 `argos skills list`

```bash
$ argos skills list
name                version   author         capabilities          status     enabled
verify              0.1.0     argos          [read, execute]       installed  ✓
security-review     0.1.0     argos          [read]                installed  ✓
simplify            0.1.0     argos          [read]                installed  ✓
python-lint         0.2.1     tungoldshou    [read, execute]       installed  ✗ (unreviewed)
test-debugger       0.1.3     community      [read, execute]       available  -
git-commit-hygiene  0.0.4     community      [read, write]         available  -

(last index refresh: 1d ago; 3 available, 1 installed, 1 unreviewed)
```

### 10.3 `argos skills install <name> [--no-refresh]`

```bash
$ argos skills install python-lint
[skills] refresh ... ok
[skills] downloading python-lint SKILL.md (4210 bytes) ...
[skills] sha256 ok
[skills] installed to ~/.argos/skills/python-lint/SKILL.md
[skills] NOTE: installed with enabled=false
[skills] review before enabling:
        $ cat ~/.argos/skills/python-lint/SKILL.md
        $ edit frontmatter: enabled: true
[skills] running smoke test ...
[skills] smoke test: PASS (exit=0)
[skills] to enable, run: argos skills test python-lint  # verify before enabling
```

### 10.4 `argos skills remove <name>`

```bash
$ argos skills remove python-lint
[skills] moved to ~/.argos/skills/.trash/python-lint/ (recoverable 30d)
[skills] to recover: argos skills install --from-trash python-lint
```

### 10.5 `argos skills test <name>`

```bash
$ argos skills test python-lint
[skills] python-lint 0.2.1: smoke test: PASS (exit=0, 1.2s)
```

## 11. 诚实防线(关键)

### 11.1 install 防线

- **download 大小 = 0** → `download_failed`(网络问题)
- **download 后 sha256 与 index 不一致** → `sha_mismatch`(index 撒谎 or MITM)
- **download 大小与 `size_bytes` 偏差 > 20%** → 警告 + 继续(spec §6.4)
- **frontmatter 缺 `name` / `capabilities` / `version`** → `frontmatter_invalid`
- **capabilities 含非白名单值** → `capability_invalid`
- **name 撞 builtin** → `protected_skill`
- **任何上述失败** → 不写盘 / 不部分写(原子写:`tempfile + rename`)

### 11.2 capability 防线

- **未声明 capability** → 装报错(强制 frontmatter 填全)
- **声明 `network`** → install 时**再**问一次 "该 skill 声明会发网络,装?"(二次确认)
- **`network` skill 跑时** → 走 approval gate,per-call 弹
- **`execute` / `write` skill 跑时** → 走 approval gate(沿用 smart approval)

### 11.3 推荐防线

- **推荐** ≠ 自动装
- **不**接 user_accept 推荐做反馈学习(留 v1.1)——本期纯规则
- **不**改写"用户必装"的清单(防推荐系统"诱导"装恶意 skill)

### 11.4 索引来源信任

- **不**接受 index.json 自签发(无 GPG / 签名)
- **接受** GitHub raw URL(MITM 风险由 https 兜底)
- **接受** `<name>-<version>` semver 标签(显式版本,作者可控)
- **不**接 `latest` 标签(防作者 push 错代码后用户被自动升级)

## 12. 错误处理

| 失败 | 行为 |
|---|---|
| 远端 404 | CLI 报错 `index_unavailable: <url>`,TUI 用本地 cache 兜底 |
| 远端 timeout(> 10s) | 同上,本地 cache 兜底 |
| sha256 不匹配 | 装报错,**不**写盘 |
| index 顶层 `version: 2`(本地 v1) | 忽略未知字段,继续(D4 兼容策略) |
| frontmatter 解析失败 | 装报错 `frontmatter_invalid: <reason>`,不写盘 |
| capabilities 字段缺 | 装报错 `capabilities_required` |
| `~/.argos/skills/` 无写权限 | CLI 报错 `permission_denied: <path>`,TUI 静默 + 提示 |
| smoke test 跑超时(> 60s) | 装继续 + 警告 "smoke test TIMEOUT — review SKILL.md" |
| 同名 skill 已装(且 `enabled: true`) | 装报错 `already_installed: <name>`,提示用 `--force` |
| `--force` 装同名前 | **不**覆盖 builtin;非 builtin → 备份到 `.trash/<n>-<ts>/` 后写新 |
| 推荐 skill 不在 index | 静默忽略 |
| 远端 url 非 https | 装报错 `insecure_url: <url> must be https` |
| skill 装后 30 天未启用 | prune 提示 "30d unreviewed, will be auto-removed in 7d" |

## 13. 测试(5 文件,+ ~25 测试)

| 文件 | 覆盖 | 估测数 |
|---|---|---|
| `tests/test_skills_curator_index.py` | index 解析、sha256 校验、cache 读写、7d stale 检测 | 6 |
| `tests/test_skills_curator_install.py` | install 落盘、原子写、capability 校验、size drift、builtin 保护、smoke test | 9 |
| `tests/test_skills_curator_remove.py` | remove + .trash 路径 + 30d 提示 + builtin 保护 | 4 |
| `tests/test_skills_curator_recommend.py` | 13 条规则触发、权重、已装跳过、index miss 忽略 | 4 |
| `tests/test_skills_curator_cli.py` | `skills refresh/list/install/remove/test` 6 子命令 | 6 |
| **合计** | | **~29** |

### 13.1 端到端铁证

`tests/test_skills_curator_e2e.py`:
- mock 远端 index.json(3 个 skill 条目,1 个 sha 不匹配)
- `refresh` → 写 index.json + 校验 sha
- `install python-lint` → 落盘 + 默认 enabled=false + smoke PASS
- `install malicious` (sha 不匹配) → 报错 + 目录不创建
- `install verify` (builtin 撞名) → 报错 protected_skill
- `remove verify` → 报错 protected_skill
- `remove python-lint` → 目录进 .trash
- `recommend` with verify_failures=2 + files=*.py → top-1 = `test-debugger`

## 14. 决策记录(D1-D20)

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | Index 托管 | 我们的 server / GitHub repo / IPFS | **GitHub repo raw** | 0 server 成本,作者可 PR,https 兜底 MITM |
| D2 | Skill 格式 | 单 markdown / markdown + 支持文件 / zip | **单 markdown + 可选 tests/ 子目录** | 简单,沿用现有 `skills.py` 模式 |
| D3 | Trust score 公式 | 社区投票 / 自动 eval / 作者信誉 | **自动 smoke test pass rate(本期 v1),社区投票 v1.1** | 投票易刷,smoke test 客观 |
| D4 | Index schema 兼容 | 严格 / 宽松 | **宽松(未知字段忽略,已知字段类型校验)** | 远端可演进,本地不破 |
| D5 | Marketplace vs direct install | 平台 / 单纯 list | **单纯 list(直接 install GitHub URL)** | CC 也没 marketplace,我们也不需要 |
| D6 | Install 路径冲突 | 覆盖 / 备份 / 拒 | **备份(.trash/)后写新** | 数据不丢,可恢复 |
| D7 | Builtin 名保护 | 软警告 / 硬拒 | **硬拒** | 基础信任根不可破 |
| D8 | Auto-update | 装后自动升 / 用户手动 | **用户手动(显式 `install` 重跑)** | 避免"我装了 v0.2 突然变 v0.5"惊喜 |
| D9 | LLM 跑 skill 路径 | 直接 `recall` / 走 `skills_runtime/` | **走 `recall()`(只读 context)+ `/skills` slash(显式触发)** | 不让 LLM 暗里跑 skill |
| D10 | TUI 内 install | 允许 / 拒绝 | **拒绝(落 transcript 提示到 host)** | 副作用稳定面缩到 host |
| D11 | Capability 4 个值(read/write/execute/network) | 8 个更细 | **4 个(粗粒度更易声明,易 user 理解)** | 4 够用,细粒度走 approval gate 兜底 |
| D12 | Smoke test 必跑? | 必跑 / 可选 | **可选(无 smoke.md → 装时不跑,user 主动 `skills test` 时跑通用探针)** | 0 装门槛 + 主动验证路径 |
| D13 | 离线 install | 允许 / 拒绝 | **拒绝(必须 online,网络装是首次信任建立)** | sha256 必须从 index 拉 |
| D14 | Skill 大小上限 | 1MB / 100KB / 1MB | **100KB(单 markdown + 小 tests/)** | skill 不是模型,不该巨大 |
| D15 | Author 字段 | 自由文本 / 必填 ID | **必填 `^[a-z0-9-]{2,32}$` ID** | 防显示欺骗("Anonymous Official") |
| D16 | 推荐写入 transcript | 是 / 否 | **是(每次 `/skills` 输出 Recommended 段)** | 0 副作用,纯提示 |
| D17 | Review 持久化 | 仅 frontmatter flag / 单独 .reviewed 文件 | **frontmatter flag** | 1 文件改 1 处 |
| D18 | Trash 30d 自动清 | 是 / 否 | **是(每次 `list` 时扫 mtime,过期删)** | 0 scheduler,纯 lazy |
| D19 | 推荐 LLM feedback 学习 | 是 / 否 | **否(v1.1)** | v1 数据少,学了易偏;先 13 规则 |
| D20 | skill 装后 30d 未启用处理 | 静默 / 提示 / 自动删 | **提示("will auto-remove in 7d"),不自动删** | 0 误伤,7d 缓冲 |

## 15. 风险与未来

- **风险 1**:GitHub 仓被封 / 删 → fallback 路径:本地 `index.json` cache 仍能 `list`,装需 online
  兜底 v1.1:支持多源 index(自托管 mirror)
- **风险 2**:smoke test 跑通 ≠ skill 真的"对" —— smoke test 只是 sanity,user 仍要 review
  v1.1:接 corpus-style auto-eval(从 eval/corpus 借)
- **风险 3**:用户开 100 个 skill,recall() 噪声上升 → 推荐 + capability 过滤已能控
  v1.1:`recall` 加 trust score 加权
- **风险 4**:恶意 skill 装上 → 装后默认 disabled + user review + capability gate + approval gate
  4 道兜底;**仍**可能 LLM 提示里被诱导——v1.1 接 prompt injection detector
- **未来 v1.1**:
  - `skills publish` CLI(用户把自己写的 skill 提到 index 仓,走 PR)
  - `skills rate <name> 1-5`(用户评价)
  - `skills audit`(列所有已装 + 显示 SKILL.md 摘要 + trust score)
  - 多源 index(自托管 + 仓)
  - 推荐反馈学习(user 接受/拒绝 → 调权)
  - 接 memory 的 user preference("don't recommend security-review-extended")

## 16. 实施任务(对应 plan)

9 任务,1 任务 = 1 commit,完整 TDD,沿用 `#5b` / `#7` / `#9` 风格:

1. Index schema + 本地 cache + `skills refresh` CLI
2. `skills list` CLI + capability 解析 + builtin 保护
3. `skills install <name>` —— download + sha256 + capability 校验 + 原子写
4. `skills remove <name>` —— .trash 路径 + builtin 保护 + 30d 提示
5. `skills test <name>` —— smoke test runner(自带 + 通用探针)
6. TUI `/skills` slash 命令 + COMMAND_HELP 更新
7. 推荐引擎(13 规则 + SessionActivity dataclass)
8. 样本 skill fixture(`python-lint.md` + `tests/smoke.md`)+ mock index server
9. 文档 + CHANGELOG + 验收铁证

> 实际 plan 拆 9 任务,见 `2026-06-07-skills-curator.md`。
