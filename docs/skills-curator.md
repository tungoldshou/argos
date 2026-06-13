# Skills curator

> 装 / 卸 / 测 / 推荐 社区 skill 的治理层(spec 2026-06-07-skills-curator)。
> **不**动 `argos/skills.py` / `skills_runtime/` —— 那是 LLM 提示召回 + 3 个
> builtin skill 编排;curator 只管**装卸**,沿用 #10 spec §3 "不重写 skill runtime"。

## 5 道防线(spec §6)

1. **sha256 校验** —— 下载 SKILL.md 后**重算**,与 index 声明不一致 → **拒装**
2. **size drift 检测** —— 下载字节数与 `size_bytes` 偏差 > 20% → 警告
3. **capability 声明** —— SKILL.md frontmatter 必填 `capabilities: list`,缺则拒装
4. **user review gate** —— 装后默认 `enabled: false`,需用户**手动**改 frontmatter
5. **approval gate 集成** —— skill 跑时若声明 `execute` 或 `network` capability,
   走 `ApprovalGate.request`(沿用 #8),smart approval 评估后弹

## 4 个 capability 粗粒度(D11)

| capability | 含义 | 装后默认 enabled | 跑时是否弹审批 |
|---|---|---|---|
| `read` | 读 workspace 文件,不改,无 shell | **自动** enabled(只读是低风险) | 不弹 |
| `execute` | 跑 shell 命令(白名单 sandbox) | 需 user review | 弹 |
| `write` | 改 workspace 文件 | 需 user review | 弹 |
| `network` | 发 http(s) 请求 | 需 user review + 装时再问"装?" | 弹 per-call |

## 常用命令

```bash
# 拉远端 index(默认从 GitHub raw,可 --url 自定义)
argos skills refresh

# 列已装 + index 远端可用 + 推荐
argos skills list

# 装一个 skill(默认 enabled=false,需手动 review SKILL.md)
argos skills install <name>

# 装后跑 smoke test(自带 tests/smoke.md 或通用探针)
argos skills test <name>

# 卸一个 skill(进 .trash 30d 可恢复)
argos skills remove <name>
```

## TUI `/skills`

```
/skills                              # 列 + 推荐
/skills install <name>               # 提示到 host 跑(不 TUI 直装)
/skills remove <name>                # 提示到 host 跑
/skills refresh                      # 提示到 host 跑
/skills test <name>                  # 提示到 host 跑
```

**TUI 不直接 install / remove** —— 副作用稳定面缩到 host CLI(D10)。
落 transcript 一行提示用户到 terminal 跑 `argos skills ...`。

## 推荐 12 规则(D19 起点,无学习)

| 触发 | 推荐 |
|---|---|
| 编辑 ≥3 个 .py | `python-lint` |
| 编辑 tests/ | `test-debugger` |
| verify 失败 ≥1 | `test-debugger` |
| verify 失败 ≥3 | + `simplify` |
| 编辑 ≥2 个 .ts/.tsx | `ts-lint` |
| 编辑 .sql | `sql-query-safety` |
| 跑过 `git commit` | `git-commit-hygiene` |
| 用过 `web_search` | `web-search-recipe` |
| 用过 `/security-review` | `security-review-extended` |
| 项目 ≥5 种后缀 | `simplify` |
| verify ≥2 + edit_file ≥5 | `test-debugger` |
| commands_run + tools_called ≥30 | `simplify` |

R13 (memory preference 接入)留 v1.1,本期不接,避免接错。

## builtin 3 个被保护(D7)

`verify` / `security-review` / `simplify` 三个 **不**能被 install 同名覆盖,
**不**能被 remove 删。它们是 verify 硬门禁 + 3 个自检原语的基础信任根,社区
skill 装不能破坏本地完整性的最低保证。

## 路径

```
~/.argos/skills/
├── index.json                  # 远端 index 副本(atomic write)
├── .trash/
│   └── <name>-<ts>/            # remove 后 30d 可恢复
├── verify/                     # builtin(从 skills_builtin 镜像)
├── security-review/            # builtin
└── simplify/                   # builtin
```

## 不做什么(spec §2.2)

- ❌ **marketplace 平台** —— 无服务端、无付款、无评分后端
- ❌ **skill 自动更新** —— 装后**不**自动升,需用户手动
- ❌ **LLM 自动生成 skill** —— skill 由人写,LLM 只能"调用"
- ❌ **跨设备同步 / 加密备份**
- ❌ **skill 私有 server(自托管)** —— 留 v1.1
- ❌ **skill marketplace 评价 / 投票** —— 留 v1.1
- ❌ **skill 自带二进制依赖** —— SKILL.md 只能配 markdown + 文本
- ❌ **热加载** —— install 后下一次 run 才生效(skills 每次 run 从磁盘重新加载,无需重启 TUI)
- ❌ **TUI 直接 install** —— 落 transcript 提示到 host CLI 跑

## 示例:装 python-lint

```bash
$ argos skills refresh
[skills] fetching https://raw.githubusercontent.com/.../index.json ...
[skills] received 12.3 KB in 1.4s
[skills] index updated: 14 skills

$ argos skills install python-lint
[skills] downloading python-lint SKILL.md (4210 bytes) ...
[skills] sha256 ok
[skills] installed to ~/.argos/skills/python-lint/SKILL.md
[skills] NOTE: installed with enabled=false
[skills] review before enabling:
        $ cat ~/.argos/skills/python-lint/SKILL.md
        $ edit frontmatter: enabled: true
[skills] running smoke test ...
[skills] smoke test: pass: exit=0

$ argos skills list
name                 version   ... capabilities               status     enabled
verify               0.1.0     ... [read, execute]            installed  OK
security-review      0.1.0     ... [read]                     installed  OK
simplify             0.1.0     ... [read]                     installed  OK
python-lint          0.2.1     ... [read, execute]            installed  OFF (unreviewed)
test-debugger        0.1.3     ... [read, execute]            available  -
git-commit-hygiene   0.0.4     ... [read, write]              available  -
```

## 与现有 skill 子系统关系

| 子系统 | 职责 | 本期动? |
|---|---|---|
| `argos/skills.py` | markdown 仓库 + 关键字/embedding 召回(LLM 提示用) | **不**动 |
| `argos/skills_runtime/` | 3 个 builtin skill 编排(/verify 等) | **不**动 |
| `argos/skills_builtin/` | 3 个受保护 builtin (verify/security-review/simplify) + 4 个内置 seed skill 模板 (git-commit-hygiene / py-test-runner / sql-query-safety / web-search-recipe) | **不**动 |
| `argos/skills_curator/` (新) | 装 / 卸 / 测 / 推荐 + 5 道防线 | **新加** |
| `argos/cli/skills.py` (新) | `argos skills` CLI 子命令 | **新加** |
| `tui/commands.py` + `tui/app.py` | `/skills` 替换为 curator 视图 | **扩展** |

## 验证铁证

`tests/test_skills_curator_e2e.py` 8 个端到端测试覆盖:

- 完整 refresh → install → list → remove 链路
- malicious sha 不匹配 → 拒装 + 目录不创建
- builtin 3 个 install/remove → 拒
- session activity → 推荐命中
- size drift → 警告 + 装继续
- network skill 需 env 确认

测试分布:6 个 test_skills_curator_*.py 文件,~88 个测试函数,覆盖 refresh / install / list / remove 全链路 + sha256 校验 + builtin 保护 + 12 条推荐规则 + TUI + CLI。

## v1.1 计划

- `skills publish` CLI(用户把自己写的 skill 提到 index 仓,走 PR)
- `skills rate <name> 1-5`(用户评价 → 调 trust score)
- `skills audit`(列所有已装 + SKILL.md 摘要 + trust score)
- 多源 index(自托管 + 仓)
- 推荐反馈学习(user 接受/拒绝 → 调权)
- 接 memory 的 user preference(`don't recommend security-review-extended`)
