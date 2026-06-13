# Auto Memory

> Argos 跨会话记住**用户偏好 / 项目约定 / 失败模式**,自动把 `CLAUDE.md` /
> `AGENTS.md` 装进 LLM 系统提示。
> 灵魂:不该"丰富"agent,而该"挡住重复犯同样错" + "不每次重新教你一遍项目约定"。

## 一句话

写 `CLAUDE.md`、跑 `/remember`、让 agent 撞过的坑自己记下来 — 下次开会话,LLM **自动看到**。

## 4 层记忆

| Tier | 路径 | 寿命 | 谁会用到 |
|---|---|---|---|
| **User** | `~/.argos/memory/user.jsonl` | 永久 + decay | 你(所有项目共享) |
| **Project** | `~/.argos/memory/projects/<hash>.jsonl` | 永久 + decay | 当前 repo |
| **Skill** | `~/.argos/memory/skills/<name>.jsonl` | 永久 | 该 skill 的失败模式 |
| **Session** | `~/.argos/memory/sessions/<sid>.jsonl` | **30 天** | 本 run 临时 |

**project_id = sha1(cwd 绝对路径)[:16]** — 换项目自动隔离。

## 用法

### 1. 写 CLAUDE.md(项目根)

```bash
# 写你的约定
cat > CLAUDE.md <<'EOF'
# 项目约定
- 缩进用 tabs 不是 spaces
- 测试命令是 `uv run pytest -q`
- 不要 commit .env 文件
EOF
```

下次开会话,Argos 自动把 `CLAUDE.md` 装进系统提示的 `<memory_context>` 段。

也支持:
- `AGENTS.md`(跨工具命名)
- `~/.argos/CLAUDE.md`(全局 dev notes,用户私)
- `~/.argos/AGENTS.md`(全局)

**优先级**:子目录 CLAUDE.md 覆盖父目录 → 全局 → 项目。

### 2. `/remember <text>`

```bash
# 默认 user tier
/remember 我喜欢用 tabs 缩进

# 显式 project tier
/remember --project build_cmd: pytest -q
/remember 本项目用 ruff 做 lint
```

回执:`已记住 (user): "我喜欢用 tabs 缩进" (id=mem_xxxx, conf=1.0)`

### 3. `/forget <id|key|text>`

```bash
# 按 id(精确)
/forget mem_a1b2c3d4e5f6

# 按 key(命中所有)
/forget indent_style

# 按文本子串
/forget tabs
```

回执:列出被软删的条目(confidence=0,后台 prune 时物理删)。

### 4. `/memory`(只读视图)

```bash
/memory
```

输出:

```
[User memories] (2)
  - preference: remember.3a4b5c = 我喜欢用 tabs 缩进 (conf=1.00, used 0x)
  - preference: language = 中文回复 (conf=1.00, used 3x)

[Project memories] (1)
  - failure: verify_fail.pytest = pytest -q → FAILED tests/test_x (conf=0.80, used 0x)

[Skill memories] (空)

[Session memories] (空)
```

## 自动沉淀(不需要你动手)

Argos 在以下事件自动写记忆:

| 事件 | 目标 tier | confidence | 写什么 |
|---|---|---|---|
| Escalation(超 max_rounds) | project | 0.9 | reason + 决策 |
| Verify gate failed | project | 0.8 | 失败命令 + stderr hash + 200 字 |
| 同 tool 连续失败 ≥3 次 | skill | 0.7 | tool + 错误模式 |
| Run 成功且 ≥5 步 | project | 0.6 | goal + 关键命令 |
| `/undo` | project | 0.7 | 撤销原因 |
| task_reflection | project | 0.7 | 任务结束时的 LLM 反思摘要 |

**24h dedup**:同一 `(scope, key, value)` 24 小时内不重复写。value 变了(用户偏好改了)= 新事实,照样写。

**secret 安全**:写入前先经 `_redact_secrets()`(`sk-ant-*` / `sk-*` / `Bearer *` / 长 base64 / `.pem` / 私钥 9 条 regex),redact 后为空则不写。

## 系统提示是怎么注入的

`_build_system()` 在 `_env_context` 之后、untrusted 段之前插入:

```xml
<memory_context>
[global: CLAUDE.md]
(global rules from ~/.argos/CLAUDE.md)

[project: CLAUDE.md]
(project rules from /path/to/CLAUDE.md)

[Recalled memories]
  - failure: verify_fail.pytest = ... (conf=0.80, used 3x)
  - preference: indent = tabs (conf=1.00, used 5x)
</memory_context>
```

- 段在 **untrusted 围栏内**(HONESTY 永远最高,违反记忆就报错)
- 每文件 ≤ 20k 字符(超截)
- 合计 ≤ 30k 字符(超出截全局段)
- `ARGOS_NO_MEMORY=1` 完全跳过

## 衰减与清理

| 机制 | 何时 | 行为 |
|---|---|---|
| **Decay** | `decay_pass()`(后台) | `confidence -= 0.01 * days_since_last_used` |
| **Use-count 回血** | `touch(entry)`(被注入时调) | `confidence += 0.02`, `use_count += 1` |
| **Prune** | `prune()`(后台) | 物理删 `confidence==0` |
| **Cap 强制** | 写入前 `_enforce_cap()` | 超 cap 按 `last_used_at` 升序删最旧 |
| **Session 30 天** | `purge_old_sessions()` | 整文件删(默认 30 天) |

confidence < 0.3 的条目不参与 ranking,但物理条目仍在(`/forget` 才能删)。

## 容量 cap(可被 `ARGOS_MEMORY_CAP_MB` 覆盖)

| Tier | 默认 cap |
|---|---|
| Project | 5 MB |
| User | 2 MB |
| Skill | 1 MB |
| Session | 1 MB |

## 关闭

- 一次性:`ARGOS_NO_MEMORY=1` 跳过系统提示注入
- 全关:删 `~/.argos/memory/`

## 召回机制

主路径为 sqlite-vec 向量语义检索(需 embedding 端点);不可用时降级 FTS5 三元组字面匹配,回执标注降级。

## 不做

- 跨机 / iCloud 同步
- Memory 写入 hook(让用户脚本拦截写)
- 自动总结(LLM 跑一遍压缩)

## 夜间整合(Dream)

Dream 在每天 03:00 由 conductor 触发(cron 任务),需用户确认后执行 `consolidate()`:合并重复 reflection、对低置信度条目施加 decay、归档过期条目(永不硬删除)。Dream 同时触发 learning 模块的技能 A/B 晋升流程。

详见 [docs/superpowers/specs/2026-06-13-dream-consolidation-design.md](superpowers/specs/2026-06-13-dream-consolidation-design.md)。

## 故障排查

**CLAUDE.md 没被看到?**
- 路径不对 — `cd <项目根>` 启动 argos
- 太大 — 单文件 > 20k 字符会被截
- `ARGOS_NO_MEMORY=1` — 检查 `echo $ARGOS_NO_MEMORY`

**/memory 看不到东西?**
- 启动后写过才能记起;CLAUDE.md 不算"记忆",是"文档注入"
- decay 过了 0.3 阈值就不入 ranking,但物理条目还在 `/forget` 还能找到

**误把 secret 写进去了?**
- 自动 redact 应该已经处理;不放心就 `cat ~/.argos/memory/user.jsonl | grep -i "sk-"` 检查
- `/forget <id>` 软删 + 后台 prune

## 相关文件

- `argos/memory/auto.py` — 实现
- `argos/core/loop.py` — `_build_system` 注入
- `argos/tui/app.py` — `_dispatch_slash` 接 /remember / /forget / /memory
- `docs/superpowers/specs/2026-06-06-auto-memory-design.md` — 设计规格
- `docs/superpowers/plans/2026-06-06-auto-memory.md` — 实施计划
