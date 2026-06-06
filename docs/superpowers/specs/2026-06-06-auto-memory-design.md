# Auto Memory + CLAUDE.md 自动加载 — 设计规格(spec)

> Road-map entry **#9** "Auto memory + CLAUDE.md 自动加载(中等,提升"懂你")" 的设计规格。
> 设计目标:让 Argos **跨会话记住**用户的偏好、项目的约定、过去的成败,把 `CLAUDE.md` /
> `~/.argos/CLAUDE.md` / `AGENTS.md` 自动装进 LLM 系统提示。灵魂对齐"让便宜模型可靠":
> 召回不该"丰富"agent,而该"挡住重复犯同样错" + "不每次重新教你一遍项目约定"。

## 1. 背景与现状

- **v0.1.0 已发**,1154 测试绿;`ArgosStore` (SQLite) 已存历史任务(`memory` 表:goal /
  verdict / model / fact),`memory.recall()` 按 embedding 余弦召回 top-k。
- **缺**:① 跨会话的用户偏好 / 项目约定 / 失败模式 **零持久化**(下一次会话又问
  "用 tabs 还是 spaces");② `CLAUDE.md` / `AGENTS.md` 这种项目级"现成规则书"
  没被 LLM 看到 — 即便用户写了一大堆,模型还是从零猜;③ 每次 verify 失败、escalation
  的决策,**没沉淀**(下次再撞同一个坑又掉一次)。
- **风险**:便宜模型在结构化任务上"一致性"是主护城河(契约层 + verify 门);
  没记忆 = **每会话都从零交一致性税**,契约层"零冲突可组装"的部分价值被磨平。
- **不动**:`memory.recall()` 的任务历史召回链路(契约 §5) — 那是"任务级"召回,本
  spec 是"用户/项目级"长期记忆,职责正交。

## 2. 目标与非目标

### 2.1 目标(本期)

1. **4 层记忆分层**,不同 scope 不同寿命:project / user / skill / session
2. **CLAUDE.md / AGENTS.md 自动发现 + 合并注入** LLM 系统提示的 `<memory_context>` 段
3. **`/remember` / `/forget` slash 命令**让用户显式管控
4. **隐式自动沉淀**:escalation 决策、verify 失败模式、重复 tool 失败
5. **decay / 容量上限 / 隐私脱敏 / 跨项目隔离** 一次性配齐(防 memory 变垃圾)
6. **TUI `/memory` view** 列出当前所有记忆(read-only,用户能看就能 `/forget`)

### 2.2 非目标(本期不做)

- ❌ 语义检索(embedding-based) — JSONL 关键词 + recency × confidence 够用,且避免再加
  sqlite-vec 列开销
- ❌ 多用户/多设备同步 — 单机 JSONL
- ❌ Memory 写入 hook(让用户脚本拦截写) — v1.1 候选
- ❌ 跨 session 共享"长期"semantic store — 与 `memory.recall` 任务历史正交,本 spec 不动
- ❌ 自动总结(LLM 跑一遍压缩) — 用户已能 `/remember "<已有>"` 合并,v1.1

## 3. 架构总览

```
                    ┌─────────────────────────────┐
                    │   argos start (TUI / CLI)   │
                    └──────────────┬──────────────┘
                                   │ session begin
                                   ▼
                    ┌─────────────────────────────┐
                    │  memory_loader.load()       │
                    │  · 4 tier 读盘 JSONL        │
                    │  · CLAUDE.md auto-walk      │
                    │  · decay + prune            │
                    │  · 排序 recency × conf      │
                    └──────────────┬──────────────┘
                                   │ top-N entries
                                   ▼
                    ┌─────────────────────────────┐
                    │  core.loop._build_system    │
                    │  · 安全段 (HONESTY)         │
                    │  · <memory_context> 段      │  ← 新注入
                    │  · untrusted 段 (围栏)      │
                    └──────────────┬──────────────┘
                                   │  LLM call
                                   ▼
                              (run 期间事件)
                          ▲           ▲           ▲
            escalation   │           │           │  verify fail
            decision ────┘           │           └── pattern
                                    │                │
                                    ▼                ▼
                        ┌────────────────────────────────┐
                        │   memory_store.capture_*()     │
                        │   · auto_capture_on_event()    │
                        │   · append JSONL (4 tier)      │
                        └────────────────────────────────┘
                                   ▲
                                   │ 显式
                                   │
                        /remember "用 tabs 而非 spaces"
                        /forget <key or id>
                        /memory   (TUI 只读视图)
```

**关键不变量**:
- 记忆模块**只追加,从不改写历史**(append-only JSONL,与现有 `RunStore` 同模式)
- `<memory_context>` 段注入在 **untrusted 围栏内**(与 skills / 召回同段),防 prompt
  injection 翻到安全段以上(契约 §3 不变量)
- **跨项目隔离**:`project_id = sha1(repo_root)`(无 `.git` 用 cwd 绝对路径),绝不混

## 4. 4 层记忆

### 4.1 层级与寿命

| Tier | Scope | 路径 | 默认上限 | 默认寿命 | 典型内容 |
|---|---|---|---|---|---|
| **Project** | per-repo | `~/.argos/memory/projects/<hash>.jsonl` | 5MB / 1000 条 | 永久 + decay | 项目约定、构建命令、忌讳、verify 失败模式 |
| **User** | per-user | `~/.argos/memory/user.jsonl` | 2MB / 500 条 | 永久 + decay | 个人偏好、语言、风格、常用别名 |
| **Skill** | per-skill | `~/.argos/memory/skills/<name>.jsonl` | 1MB / 200 条 | 永久 | 该 skill 历史上失败的命令、用户的修正 |
| **Session** | per-session | `~/.argos/memory/sessions/<sid>.jsonl` | 1MB / 200 条 | **30 天**自动 rotate | 本次 run 的临时状态、escalation 决策草稿 |

**为什么分 4 层**:
- **Project** 解决"换个项目就忘" — 离职一个项目,记忆跟着 git 走
- **User** 解决"换项目就重教" — 个人偏好跨项目活
- **Skill** 解决"同一个 skill 又踩同一坑" — skill 自身的失败库
- **Session** 解决"上一轮 agent 跑一半的草稿" — 给 30 天续跑窗口

### 4.2 Schema(单条记录)

```json
{
  "id": "mem_a1b2c3d4e5f6",
  "type": "preference" | "convention" | "failure" | "decision" | "fact",
  "scope": "user" | "project" | "skill" | "session",
  "key": "indent_style",
  "value": "tabs",
  "confidence": 0.95,
  "evidence": ["user explicit /remember command"],
  "ts": 1749216000.0,
  "created_at_iso": "2026-06-06T14:00:00Z",
  "last_used_at": 1749216000.0,
  "use_count": 1,
  "skill_name": "verify" | null,
  "project_id": "sha1..." | null,
  "session_id": "uuid..." | null
}
```

**字段语义**:
- `type`:语义分类(检索时分类优先,例 `failure` 优先于 `fact`)
- `scope`:决定读哪个 JSONL 文件
- `key`:检索主键(`indent_style` / `build_cmd` / `forbidden_pattern`)
- `value`:字符串(短文本,长文本走 `fact` 而非 value)
- `confidence`:初始 0.5-1.0(`/remember`=1.0,auto-capture=0.7,escalation=0.9)
- `evidence`:观察来源 list(可读性,不影响逻辑)
- `ts` / `last_used_at` / `use_count`:用于 decay + ranking

### 4.3 4 个 tier 的 dataclass + JSONL I/O

- 4 个 `@dataclass(frozen=True, slots=True)`:`UserMemory` / `ProjectMemory` / `SkillMemory` / `SessionMemory`
  (实际为同一 `MemoryEntry` dataclass,scope 字段区分,类型安全通过 Literal 表达)
- 单一 `_read_jsonl(path) -> list[MemoryEntry]` + `_append_jsonl(path, entry)`
- 并发:`threading.Lock` 包裹写(同 `memory` 现模式),不与 SQLite 争

## 5. CLAUDE.md / AGENTS.md 自动加载

### 5.1 发现的优先级(从高到低合并)

1. **项目根 CLAUDE.md** — 从 cwd 向上走,直到文件系统根,找 `CLAUDE.md` 全部
   收集,**子目录覆盖父目录**(与 Claude Code 一致)
2. **项目根 AGENTS.md** — 同上(若用户用 AGENTS.md 命名约定,兼容)
3. **~/.argos/CLAUDE.md** — 全局 dev notes(用户私,gitignore)
4. **~/.argos/AGENTS.md** — 全局 dev notes(同上)

### 5.2 合并规则

- **顺序**:全局 → 项目根(由远及近,子目录覆盖父目录同 key)
- **截断**:每文件硬上限 20,000 字符(>20k 截断 + 标 `<truncated>` 标记)
- **总上限**:合并后 ≤ 30,000 字符(超出走 LLM 摘要 — 但本期不做 LLM 摘要,直接截最低优先级)
- **空态**:全无 → 不注入 `<memory_context>` 段(同 `format_untrusted` 空态语义)
- **失败**:读盘 IOError / 权限拒绝 → 静默跳过,**不阻塞 run**

### 5.3 注入位置

```python
# core/loop.py _build_system (新增 memory_context 段,在 HONESTY 之后、untrusted 之前)
safe = (
    HONESTY_SYSTEM
    + _env_context(self._workspace)
    + _memory_context_block(self._workspace, project_id)  # ← 新增
    + self._tool_signatures_block()
)
```

- **位置在 untrusted 围栏内**(防 CLAUDE.md 攻击面被升级到安全段)
- **但不是 untrusted** — 它来自用户/项目,**可信度高于** skills/recall(更"内部")
- **围栏标签**:`<memory_context>...</memory_context>`(给 LLM 显式信号:这是规则书,
  不可与上文 HONESTY 冲突时取 HONESTY;这是"工程约定",不是"安全边界")

### 5.4 隐私

- **不读**:`.env` / `.env.*` / `secrets.toml` / `*.pem` / `*.key` / `secrets/` — 与
  `/security-review` 同款(D4 user-controlled 秘密存储)
- **不写入 memory**:任何含 secret 模式的字符串(API key 格式 `sk-ant-*` / `sk-*` /
  `Bearer *` / 长 base64)被自动 redact 为 `<redacted>` 再决定是否存
- **opt-out**:`ARGOS_NO_MEMORY=1` / `ARGOS_NO_CLAUDE_MD=1` 关 env var(用户态兜底)

## 6. 显式 /remember / /forget

### 6.1 /remember `<text>`

- **解析**:`/remember 用 tabs 而非 spaces` → `key="user.remember.0"`(自动生成),
  `value="用 tabs 而非 spaces"`,`type="preference"`,`scope="user"`,
  `confidence=1.0`,`evidence=["user explicit /remember command"]`
- **目标 tier**:由文本自动判断(检测关键词 "项目"/"build"/"test" 命中 → project;
  默认 user)
- **手动指定**:`/remember --project build_cmd: pytest -q`(显式 scope + key:value 格式)
- **回执**:`已记住(user): "用 tabs 而非 spaces"(id=mem_a1b2)`

### 6.2 /forget `<id | key | text>`

- **id 精确**:`/forget mem_a1b2c3` → 标记 `confidence=0`(软删,下次 prune 物理删)
- **key 模糊**:`/forget indent_style` → 命中所有 scope 里 `key == "indent_style"` 的
  条目,逐一软删
- **text 模糊**:`/forget tabs` → 在 value 里子串匹配,top-5 让用户选
- **回执**:列出将要软删的条目 + 数量

### 6.3 /memory(只读视图)

- 列出 4 tier 各 N 条最新
- TUI 渲染为可滚动 list,无编辑(编辑走 `/forget`)
- 不进 `COMMAND_HELP` 主菜单(避免与 `/help` 等并列时太长) — **藏在 `/memory` 单独
  命令**(Claude Code 同款,记忆管理是 meta 操作)

## 7. 隐式自动沉淀

### 7.1 触发点

| 事件 | 沉淀内容 | 目标 tier | 初始 confidence |
|---|---|---|---|
| **Escalation 决策** | 用户对 escalation 的回复 + reason | project | 0.9 |
| **Verify gate failed** | 失败命令 + 失败输出 hash(前 200 字符) | project | 0.8 |
| **同 tool 连续失败 ≥3 次/session** | 失败 tool + 错误模式 | skill(project) | 0.7 |
| **Run 成功且 ≥5 步** | 任务 goal + 用到的关键命令 | project | 0.6 |
| **User 主动 `/undo`** | 撤销原因(若有) | project | 0.7 |

### 7.2 去重

- 同一 `(scope, key, value)` 24h 内重复 → 跳过(避免 spam)
- 同一 `(scope, key)` 但 value 不同 → **不跳**,保留最新(用户的偏好变了 = 新事实)

### 7.3 失败证据去重(避免 secret 泄露)

- 错误输出先经 `redact_secrets()`(复用 `skills_builtin.security_review` 已有 9 regex)
- 任何 `sk-*` / `Bearer *` / 长 base64 模式 → `<redacted>` 后再决定存不存

## 8. 检索 / 排序

### 8.1 ranking

```
score(entry) = recency_factor * confidence
  recency_factor = exp(-0.01 * days_since_last_used)  # 1 天 → 0.99,30 天 → 0.74
```

- 检索时按 `score` 降序,**取 top N**(默认 50 / 4 tier,合计 200 条)
- 同 scope 内:**type 优先级** `failure > decision > convention > preference > fact`
  (失败最该被记住,普通事实最后)

### 8.2 检索时机

- **session 开始**:`AgentLoop.__init__` 时一次性 load,缓存在 `self._memory_view`
- **不每次 _build_system 重读** — 一次 session 一次 load,IO 友好
- **显式 `/forget` 后**:清缓存 + 重新 load

## 9. Decay / Pruning / 容量

### 9.1 自动 decay

- **每次 `load()` 时**:`confidence -= 0.01 * days_since_last_used`(无 last_used → 用 ts)
- **下界**:`confidence < 0.3` → 不参与 ranking(但物理条目仍存,用户 `/forget` 才删)
- **use_count 加分**:每次被注入系统提示后,`use_count += 1`,**confidence 回升 0.02**
  (被用 = 仍有效 = 别衰减太快)

### 9.2 物理 prune

- **手动**:`/forget` 软删(confidence=0)→ 后台 1 次 prune 物理删(下次 load 时)
- **容量 cap**:写入前检查文件大小 → 超 5MB/2MB/1MB cap → 按 `last_used_at` 升序
  删最旧(直到 < cap)
- **session tier**:30 天未访问的 session 文件 → 整体 delete
  (有 `last_used_at` 机制:每次 run start 触碰)

### 9.3 cap 默认值

| Tier | 容量 cap | 条数 cap |
|---|---|---|
| Project | 5MB | 1000 |
| User | 2MB | 500 |
| Skill | 1MB | 200 |
| Session | 1MB | 200 |

(可被 `ARGOS_MEMORY_CAP_MB` 覆盖,默认不变)

## 10. 错误处理与降级

| 失败 | 行为 |
|---|---|
| JSONL 文件损坏 / 单行坏 | 跳过该行,正常返回其余(spec §5.2 同款"一行坏数据不毁整个") |
| 文件不存在 | 返空列表(诚实空态),不创建空文件 |
| IOError(权限/磁盘满) | 静默 log + 返空,**不阻塞 run**(记忆是 nice-to-have,不是 run 的依赖) |
| `ARGOS_NO_MEMORY=1` | 全模块 `__all__` 返 `None`,`_build_system` 不注入段 |
| 容量 cap 触发 prune 失败 | 重试 3 次,失败静默(下次写再试) |
| 跨项目 ID 计算失败 | 退回 `cwd` 绝对路径 hash(不会更安全但至少稳) |

## 11. 决策记录(D1-D20)

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | 记忆存储格式 | SQLite / JSONL / leveldb | **JSONL** | 与 `RunStore` 同模式;无新 dep;append-only 简单 |
| D2 | 4 tier 还是 1 tier | 4 / 1 / 2 | **4** | scope/寿命/容量三维度不同,合并会扯皮 |
| D3 | CLAUDE.md 注入位置 | 安全段 / untrusted / 独立段 | **独立 `<memory_context>` 段,在 untrusted 内** | 用户规则 vs LLM 安全,HONESTY 永远最高 |
| D4 | 是否自动记住 | 全开 / 仅 explicit / 半开 | **半开** | escalation/verify fail/重复 fail 自动;其他 explicit |
| D5 | 跨项目隔离粒度 | repo / 用户 / 全局 | **repo(sha1(repo_root))** | 用户换项目不该被前项目污染 |
| D6 | decay rate | 0.01/day / 0.05/day / 不 decay | **0.01/day,被用 +0.02** | 慢 decay + 使用复活,既不"快速失忆"也不"永不遗忘" |
| D7 | secret redaction 范围 | 全 redact / 模式匹配 / 不做 | **模式匹配(同 security-review 9 regex)** | 复用,边界一致 |
| D8 | `/forget` 是软删还是硬删 | 软删 / 硬删 / 都做 | **软删 + 后台 prune** | undo 友好,容量 cap 兜底 |
| D9 | 写入是否进 commit message | 是 / 否 | **否** | memory 是用户私,不该污染 git |
| D10 | LLM 摘要后注入 | 是 / 否 | **否(本期)** | 多一步 LLM 调用,价值/成本比低,v1.1 |
| D11 | session tier 默认寿命 | 7/30/90 天 | **30 天** | 平衡"能续跑"与"不堆积" |
| D12 | capacity cap 单位 | MB / 条数 / 二者 | **二者取先到** | 双重护栏,免 JSONL 爆炸 |
| D13 | 检索走 embedding | 走 / 不走 | **不走(关键词 + recency)** | 与 `memory.recall` 职责正交;省 IO;4 tier 小数据量关键词足够 |
| D14 | 同一 key 重复值 | 跳过 / 合并 / 保留最新 | **跳过(< 24h)** | 24h 后值变则更新,防 spam |
| D15 | opt-out 机制 | 无 / env var / config | **env var (`ARGOS_NO_MEMORY=1`)** | dev 兜底,无需改 config 树 |
| D16 | TUI `/memory` 是否默认在 COMMAND_HELP | 是 / 否 | **否(单独命令)** | 18→19 但 5 个一字命令里数得过来,体验更整洁 |
| D17 | 失败模式写入时存多少 | 全存 / hash / 200 字 | **截断 200 字符 + hash 标记** | 不存日志海,但可追 |
| D18 | 是否支持 `AGENTS.md` | 否 / 是 | **是** | 跨工具约定,不绑 Claude Code 命名 |
| D19 | 用户多台机共享 | 不做 / cloud sync / 配 iCloud | **不做(本期)** | v1.1,本期单机 JSONL |
| D20 | 写入并发 | 无锁 / thread lock / fcntl | **threading.Lock** | 与 `memory` 现模式一致,跨平台 |

## 12. 测试 / 验收 / 护城河对齐

### 12.1 测试文件(6 个)

| 文件 | 覆盖 | 估测测试数 |
|---|---|---|
| `tests/test_memory_tiers.py` | 4 tier dataclass + JSONL 读写 + 损坏行跳过 | 8 |
| `tests/test_memory_ranking.py` | recency × confidence 排序、use_count 回血、type 优先级 | 7 |
| `tests/test_memory_capture.py` | 5 个 auto-capture 触发点 + secret redaction + 24h 去重 | 9 |
| `tests/test_claude_md_walker.py` | 向上 walk / 合并 / 截断 / secret skip / AGENTS.md | 8 |
| `tests/test_memory_commands.py` | `/remember` / `/forget` / `/memory` 解析 + 副作用 | 7 |
| `tests/test_memory_injection.py` | `_build_system` 注入位置 + `<memory_context>` 段 + opt-out | 5 |

合计 +44 测试,覆盖率目标 85%+。

### 12.2 端到端铁证

- 跑真 session → escalation 决策 → reload memory.jsonl 看到 entry → 模拟下次 session
  start → system prompt 含 entry 文本(单元断言)
- 真 Claude.md:写一份 `tmp/CLAUDE.md` "用 tabs 而非 spaces" → `load_project_claude()`
  返该文本 → 注入到 `_build_system` 输出 → 截断 / 合并 / secret 跳过断言

### 12.3 护城河对齐

- **诚实**:`<memory_context>` 段不假装是安全段,**显式标"工程约定非安全边界"**;
  decay 透明(用户 `/memory` 能看到 confidence);secret redaction 在写入前(不事后修补)
- **可及**:`/memory` 一行能看清自己被记住了什么;`/forget` 一秒清掉;opt-out env var
- **确定**:失败模式不被静默,decay 不被"忘了所以删了",所有 4 tier 物理可查

### 12.4 验收清单(发版前)

- [ ] 6 测试文件全绿,新增 ≥ 44 测试
- [ ] 端到端铁证:tmp CLAUDE.md → 进 system prompt
- [ ] secret redaction 9 regex 复用 + 单测断言
- [ ] 容量 cap 触发 prune 单测(写入超 5MB → 文件缩容)
- [ ] decay 30 天 → confidence < 0.3 不入 ranking 单测
- [ ] `/forget` 软删 + 后台 prune 单测
- [ ] `ARGOS_NO_MEMORY=1` 注入全跳过单测
- [ ] 跨项目隔离:project A 的 entry 不出现在 project B 的 system prompt
- [ ] CHANGELOG 增 Unreleased 段
- [ ] 文档:`docs/` 加 `auto-memory.md` 用户文档(简明 + 例子)

## 13. 风险与未来

- **风险 1**:记忆污染 — 用户写错 CLAUDE.md → agent 跟着错。
  缓解:`<memory_context>` 段在 untrusted 内,LLM 仍受 HONESTY 优先约束
- **风险 2**:JSONL 写多机同步不友好。 v1.1 评估 cloud sync
- **风险 3**:decay 系数拍脑袋 0.01/day,实跑后可能太慢/太快 → `/memory` 视图给
  `last_used_at` + `confidence` 两列,用户能感知衰减速度
- **未来 v1.1**:LLM 摘要后注入(超 cap 时)、memory 写入 hook、跨机 sync、session
  续跑优先注入

## 14. 实施任务(对应 plan)

8 任务,1 任务 = 1 commit,完整 TDD:
1. `memory/` 模块骨架 + 4 tier + JSONL persistence
2. Memory loader + recency × confidence 排序
3. CLAUDE.md auto-walk + 合并
4. `/remember` / `/forget` slash 命令
5. Auto-capture 触发点(escalation / verify fail / 重复 tool fail)
6. 系统提示 `<memory_context>` 注入 (`core/loop.py`)
7. Decay / prune / 容量 cap
8. TUI `/memory` 视图命令
9. 文档 + CHANGELOG + 验收

(实际 plan 拆 9 任务,见 `2026-06-06-auto-memory.md`)
