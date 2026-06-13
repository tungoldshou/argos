# Agent eval / 用户项目级 A/B — 设计规格(spec)

> Road-map entry **#7** "Agent eval / 用户项目级 A/B (中等,扩护城河)" 的设计规格。
> 估时 4-5 天,中等。**灵魂对齐**"让便宜模型可靠"——不是炫"我有测试",
> 而是 **dogfooding**(Argos 测 Argos),把"我在硬跑真实任务、有量化数字、敢贴
> A/B 报告"做成护城河,和"我有个 graph 界面"的竞品拉开距离。

## 1. 背景与现状

- **v0.1.0 已发**,1320 测试绿。`#5b` 多 run tabs + `#9` 自动记忆 + `verify 硬门禁` + 篡改
  检测 + smart approval + workflow 编排都已就位,7 个未推送 commit。
- **当前缺口**:
  1. **没有量化"我有多可靠"** —— 1320 个 pytest 是"组件测试",**不是"agent 端到端
     能不能干活"测试**。对外宣传"verify 门"全是原则,没有数字。
  2. **没有 model tier 对比** —— 用户问"我换便宜模型效果掉多少?"没人答得出,
     只能听宣传话术。
  3. **dogfooding 是空话** —— 团队靠"我们用了 7 天没炸"自证,不是真实任务跑出来的
     数字。
- **风险**:护城河全靠"诚实 + verify 门 + 篡改检测"的**承诺**,承诺本身没被
  **自我验证**——"你怎么知道 verify 门真有用?" 答:用 verify 门跑真实任务看 pass 率。
  这就是本期 spec 做的事。
- **灵魂**:不跟 LangChain/LlamaIndex 拼"我工具多",不跟 Devin/Cursor 拼"我有 GUI",
  而是做"我敢给一个**跑出来的** A/B 报告证明我的 verify 门让便宜模型不掉链子"——
  这是别人**没数据**所以**不敢做**的护城河。

## 2. 目标与非目标

### 2.1 目标(本期)

1. **Task corpus**:`~/.argos/eval/corpus/<task_id>/` 每任务一目录,含 `goal.md` / `verify_cmd` /
   `setup.sh`(可选,准备环境)/ `difficulty`(easy/medium/hard);**5 类任务 × 5 个真实样本种子**
   起步(bug fix 5 / refactor 3 / test write 3 / doc 3 / 自检 3),由人维护(非模型生成,D1)
2. **Eval runner**:`EvalRunner.run(task, model_tier, budget)` → 沙箱 worktree + 真 AgentLoop +
   真 verify_cmd + 捕获 pass/fail、time、tokens、cost
3. **A/B 对比**:`EvalRunner.run_pair(task, model_a, model_b)` → 同 goal 跑两遍,生成
   side-by-side 报告 `~/.argos/eval/reports/ab-<task_id>-<date>.md`
4. **JSONL 结果持久化**:`~/.argos/eval/runs/<date>/<run_id>.jsonl` 每行 1 条结果
5. **CLI 子命令**:`argos eval list` / `argos eval run <task_id> [--model <tier>]` /
   `argos eval compare <task_id> <model_a> <model_b>`(可脱 daemon 用,无 GUI)
6. **TUI `/eval` slash 3 件套**:`/eval`(列最近 run + 摘要)/`/eval run <task_id>`(单跑)/
   `/eval compare <a> <b>`(A/B 报告渲到 transcript)
7. **诚实防线**:
   - `passed` 标志位 = `verify_cmd` 退出码 0(绝不"模型说通过了")
   - `cost_usd` = API response 的 `usage` 字段累计(**非估算**)
   - 篡改检测触发 → `passed` 改 `unverifiable`(沿用 verify 门语义)
   - 任何 run 出错(无 verify_cmd / verify 报错 / LLM 限流)→ `failed` + 诚实 error message
8. **worktree 复用**:直接用 `#5b` 的 `WorktreeManager`(git worktree + temp fallback,失败
   兜底标 `isolation_fallback: temp`);**不**重新造轮子
9. **0 新外部依赖**(stdlib only,JSONL + subprocess + 同 daemon 协议)

### 2.2 非目标(本期不做)

- ❌ **模型自动生成新任务**(corpus 由人维护,本期交付 14 个种子即可)
- ❌ **在线 leaderboard / 公网公开**(本期本地 + 私享即可,公开 v1.1)
- ❌ **沙箱外 network 真跑**(`verify_cmd` 走 ARGOS sandbox 白名单,**不**开放网络)
- ❌ **跨项目复用**(`eval` 跑在 Argos **自己**项目上做 dogfooding,不抽泛到任意项目)
- ❌ **CI 自动跑**(`ARGOS_EVAL_CI=1` 模式留 v1.1;本期只 CLI/TUI 主动)
- ❌ **统计显著性检验**(样本小,t 检验不适用;v1.1 大了再加)
- ❌ **A/B with replay**(`--recorded` 模式留 v1.1;本期真跑)
- ❌ **Eval 报告 web 仪表盘**(本地 markdown + transcript 即可,公开 v1.1)
- ❌ **长跑 + pause/resume**(单 task ≤ 10 分钟,小 budget;超过 → 用户在 TUI 自己
  Esc 打断后 partial 不计,只记 terminal state)

## 3. 架构总览

```
                      ┌─────────────────────────────────────┐
                      │   argos eval list | run | compare   │
                      │   (CLI,__main__.py subcommand)      │
                      │   ───────────────────────────────    │
                      │   /eval · /eval run · /eval compare│
                      │   (TUI slash,tui/app.py)            │
                      └──────────────┬──────────────────────┘
                                     │ EvalTask + model_tier
                                     ▼
                      ┌─────────────────────────────────────┐
                      │        eval/runner.py               │
                      │  EvalRunner.run(task, model, budget)│
                      │   1. WorktreeManager.create()        │
                      │   2. setup.sh (if exists)            │
                      │   3. AgentLoop.run(goal)            │
                      │   4. Verifier.verify(verify_cmd)     │
                      │   5. capture: pass/fail/time/cost    │
                      │   6. WorktreeManager.cleanup()      │
                      │   7. results.append_jsonl(...)      │
                      └──────────────┬──────────────────────┘
                                     │ JSONL append
                                     ▼
                      ┌─────────────────────────────────────┐
                      │  ~/.argos/eval/runs/<date>/<rid>.jsonl │
                      │  ~/.argos/eval/reports/ab-*.md      │
                      └──────────────┬──────────────────────┘
                                     │
              ┌──────────────────────┼─────────────────────┐
              ▼                      ▼                     ▼
    ┌────────────────┐   ┌─────────────────────┐  ┌────────────────┐
    │ eval/corpus/   │   │ eval/reports/       │  │ argos eval     │
    │ <task_id>/     │   │ ab-<id>-<date>.md   │  │ list / compare │
    │  goal.md       │   │  ·  side-by-side    │  │  (读取 JSONL)  │
    │  verify_cmd    │   │  ·  pass/time/cost  │  └────────────────┘
    │  setup.sh      │   │  ·  output diff     │
    │  difficulty    │   │  ·  sample run log  │
    └────────────────┘   └─────────────────────┘
```

**关键不变量**:
- **pass 标志位 = verify_cmd 退出码**(不靠 LLM 自我报告)
- **cost = API 返 usage 字段累计**(不靠模型自报 token;Opus 4.5 也可能撒谎)
- **corpus task 改动 → 新版本号(`corpus_version`)**(JSONL 跑出来带 `corpus_version`,
  跨版本对比诚实标注"v1 → v2 task 变了",不打榜)
- **runner 失败也算数据**(LLM 限流 / verify 报错 / worktree 失败 / setup 失败
  → 落 JSONL 标 `failed` + 详细 error,不打入 passed)

## 4. 任务 corpus 设计

### 4.1 目录结构

```
~/.argos/eval/corpus/
├── corpus.json                  # 任务清单(手维护,14 条种子)
└── <task_id>/
    ├── goal.md                  # 任务描述(LLM 拿这一段当 user message)
    ├── verify_cmd               # 单行 shell 命令,退出码 0 = pass
    ├── setup.sh                 # (可选)环境准备;exit 非 0 → 整 task 标 setup_failed
    ├── difficulty               # "easy" | "medium" | "hard"
    ├── category                 # "bug_fix" | "refactor" | "test_write" | "doc" | "self_check"
    ├── expected_files           # (可选)glob 列表,task 完成后应出现的文件(存在性检查)
    └── notes.md                 # (可选)维护者笔记
```

### 4.2 corpus.json 格式

```json
{
  "version": 1,
  "tasks": [
    {
      "id": "bug_fix_001_off_by_one",
      "category": "bug_fix",
      "difficulty": "easy",
      "title": "修复 off-by-one 错误(median 函数)",
      "estimated_minutes": 5
    },
    {
      "id": "refactor_001_extract_helper",
      "category": "refactor",
      "difficulty": "medium",
      "title": "提取 _project_id_for 重复逻辑为 helper",
      "estimated_minutes": 8
    }
  ]
}
```

### 4.3 14 个种子任务(本期交付,3-5 行就够)

| ID | Category | Difficulty | Goal 一句话 |
|---|---|---|---|
| `bug_fix_001_off_by_one` | bug_fix | easy | 修复 `memory/auto.py` `_score` 函数对 `last_used_at` 未来的处理(应截 0 而非负) |
| `bug_fix_002_path_join` | bug_fix | easy | 修 `daemon/worktree.py` `cleanup` 对 temp fallback 路径的 race |
| `bug_fix_003_missing_parent` | bug_fix | medium | 修 `cli/eval.py` 跑 task 时 `expected_files` 不存在时崩的问题 |
| `bug_fix_004_off_by_one_loop` | bug_fix | medium | 修 `core/loop.py` 步数累计 off-by-one(首步应记 1) |
| `bug_fix_005_unverifiable_promote` | bug_fix | hard | 修 `verify_gate` 把 `unverifiable` 误升为 `passed` 的边界 |
| `refactor_001_extract_helper` | refactor | medium | 抽 `commands.py` 中重复的 `_cmd_or_unknown` 逻辑 |
| `refactor_002_dedup_repos` | refactor | medium | 抽 `daemon/server.py` 重复的 `_send_error` 包裹 |
| `refactor_003_split_loop` | refactor | hard | 拆 `core/loop.py` `_drive` (250 行) 为 3 个函数 |
| `test_write_001_verify_bounce` | test_write | easy | 给 `verify_gate.verify` 写 tamper-detected 分支单测 |
| `test_write_002_approval_levels` | test_write | easy | 给 `ApprovalGate` 写 `confirm` 拒绝分支单测 |
| `test_write_003_corpus_loader` | test_write | medium | 给 `eval/corpus.py` `load_corpus` 写缺 `goal.md` 边界单测 |
| `doc_001_module_header` | doc | easy | 给 `memory/auto.py` 顶补缺失的 §概要 行 |
| `doc_002_architecture` | doc | medium | 给 `docs/eval.md` 写一段"何时用 A/B"指南 |
| `doc_003_changelog_format` | doc | easy | 给 `CHANGELOG.md` 写 0.2.0 模板段(虚构,验证格式) |

### 4.4 任务内容设计原则(spec 灵魂)

- **真实**:任务从 Argos 自己的代码里抽(不凭空捏),LLM 真能修/能 refactor 的那种
- **可量化**:`verify_cmd` 必须客观(退出码,不是"看看代码长得好不好看")
- **时间盒**:5-15 分钟内应能完成(LLM 多步,≤ ~30 步 CodeAct)
- **诚实可失败**:弱模型跑不过 → 就是 `failed`,**不**降难度(护城河就靠"难度不退让")

### 4.5 5 类任务权重

| Category | 数量 | 比例 | 用意 |
|---|---|---|---|
| bug_fix | 5 | 36% | 主战场:用户最关心"agent 能不能修 bug" |
| refactor | 3 | 21% | 看模型对"不破坏行为"的理解 |
| test_write | 3 | 21% | TDD 场景,verify 门常用路径 |
| doc | 3 | 22% | 最容易的类别,看是否能跑通整个流程 |
| **合计** | **14** | **100%** | |

> 自我检查(self_check)类别本期**不**做(防"用 Argos 测 Argos 的元循环"心智负担);v1.1
> 加 3-5 个"Argos 跑 /security-review 自己的输出"任务。

## 5. Eval runner 设计

### 5.1 数据结构

```python
# argos/eval/runner.py
@dataclass(frozen=True, slots=True)
class EvalTask:
    id: str
    category: str            # "bug_fix" | "refactor" | "test_write" | "doc"
    difficulty: str          # "easy" | "medium" | "hard"
    title: str
    goal: str                # 来自 goal.md
    verify_cmd: str          # 来自 verify_cmd 文件
    setup_cmd: str | None    # 来自 setup.sh(可选)
    expected_files: tuple[str, ...]
    working_dir: Path        # 实际跑的工作目录(setup.sh 后)

@dataclass(frozen=True, slots=True)
class EvalResult:
    task_id: str
    run_id: str              # 12 hex(沿用 daemon)
    model_tier: str          # config profile name
    started_at: float
    finished_at: float
    duration_s: float
    pass_status: str         # "passed" | "failed" | "unverifiable" | "setup_failed" | "error"
    verify_cmd: str
    verify_detail: str
    tampered: tuple[str, ...]
    tokens_in: int
    tokens_out: int
    cost_usd: float | None
    steps: int               # CodeAct 步数
    worktree_path: str
    isolation_fallback: str | None  # "temp" | None
    error: str | None        # 任何阶段崩的 detail
    corpus_version: int
```

### 5.2 核心 API

```python
# argos/eval/runner.py
class EvalRunner:
    def __init__(self, *, worktree: WorktreeManager, base_dir: Path,
                 budget_s: int = 600, budget_cost_usd: float = 1.0):
        self._worktree = worktree
        self._base = base_dir
        self._budget_s = budget_s
        self._budget_cost_usd = budget_cost_usd

    def load_task(self, task_id: str) -> EvalTask: ...
    def run(self, task: EvalTask, *, model_tier: str) -> EvalResult: ...
    def run_pair(self, task: EvalTask, *, model_a: str, model_b: str) -> tuple[EvalResult, EvalResult]: ...
    def list_runs(self, *, date: str | None = None, limit: int = 50) -> list[EvalResult]: ...
    def load_run(self, run_id: str) -> EvalResult: ...
```

### 5.3 run() 流程

```
1. _resolve_model_client(model_tier)         # 走 config.profile
2. worktree = WorktreeManager.create(workspace, run_id)
3. ctx = RunContext(workspace=worktree, verify_dir=worktree, project_mode=True)
4. setup_exit = subprocess.run(setup.sh)     # 失败 → result.pass_status="setup_failed",return
5. loop = build_loop_factory(workspace=worktree, model_override=model_tier)
6. result = loop.run(goal)                    # 同步等到 terminal state
7. verdict = Verifier.verify(verify_cmd)      # 真跑 verify,退出码 0 = pass
8. result.pass_status = verdict.status        # passed/failed/unverifiable
9. result.cost = sum(loop.cost_updates)       # 累计,不是估算
10. WorktreeManager.cleanup(run_id)
11. self._append_jsonl(result)
12. return result
```

### 5.4 失败模式

| 失败 | 行为 | result.pass_status |
|---|---|---|
| 找不到 `goal.md` | raise FileNotFoundError | — |
| `setup.sh` 退出非 0 | abort | `setup_failed` |
| `WorktreeManager.create` 抛 | abort | `error` |
| LLM 限流 / 模型不可用 | loop 自然 fail,捕获异常 | `error` |
| `Verifier.verify` 抛 | loop 自然 fail | `error` |
| Budget 超时(> 600s) | cancel loop | `failed` + error="budget_exceeded" |
| 篡改检测触发 | verdict=unverifiable | `unverifiable` |
| 任何未捕获异常 | abort + cleanup worktree | `error` + 异常 message |

### 5.5 A/B 对比

```python
def run_pair(self, task, *, model_a, model_b) -> tuple[EvalResult, EvalResult]:
    """同 task,两个 model_tier 各跑一遍;用同 task_id 不同 run_id(trace 关联)。"""
    ra = self.run(task, model_tier=model_a)
    rb = self.run(task, model_tier=model_b)
    return ra, rb
```

**关键不变量**:
- **同 task_id、可能不同 model_tier**;run_id 不同;报告通过 `task_id + date` 关联
- **A/B 用相同 worktree 起点**(task_id 一致,git worktree 重新 add);**不**共享 state
- **报告带 `corpus_version`**(任务若跨版本升级,标注"task 改了")

## 6. 持久化设计

### 6.1 JSONL 格式

每行一条 JSON,字段 = `EvalResult` 的 asdict 序列化:

```json
{"task_id":"bug_fix_001","run_id":"abc123def456","model_tier":"cheap",
 "started_at":1717700000.0,"finished_at":1717700120.0,"duration_s":120.0,
 "pass_status":"passed","verify_cmd":"python -m pytest tests/ -q",
 "verify_detail":"5 passed in 0.5s","tampered":[],
 "tokens_in":12400,"tokens_out":3100,"cost_usd":0.013,"steps":12,
 "worktree_path":"/Users/zc/.argos/eval/worktrees/abc123","isolation_fallback":null,
 "error":null,"corpus_version":1}
```

### 6.2 路径

```
~/.argos/eval/
├── corpus/
│   ├── corpus.json
│   └── <task_id>/
│       ├── goal.md
│       ├── verify_cmd
│       ├── setup.sh
│       └── difficulty
├── runs/
│   └── <YYYY-MM-DD>/
│       └── <run_id>.jsonl           # 1 个 run 1 文件
├── reports/
│   └── ab-<task_id>-<YYYY-MM-DD>.md
└── worktrees/                       # 与 #5b 隔离,不复用
    └── <run_id>/
```

### 6.3 为什么每 run 一 JSONL 文件(而非一行一 run 全局)

- 沿用 `daemon/store.py` 模式(`#5a` / `#5b`)
- 锁粒度细:append + read 不互锁全局
- 跑一半的 run 写文件,不污染别的
- 错行易排查(哪个 run_id 坏)

### 6.4 与 `#5b` daemon JSONL 区别

- `#5b` `~/.argos/daemon/runs/<rid>.jsonl` 存**事件流**(EventBus 序列化)
- `#7` `~/.argos/eval/runs/<date>/<rid>.jsonl` 存**单条结果 EvalResult**(`#7` 每 run
  1 文件,1 行)
- **不**合并(语义不同,daemon 是事件真相,eval 是评估结果聚合)

## 7. CLI 子命令

### 7.1 `argos eval list`

```bash
$ argos eval list
Run ID    Date          Task                    Tier        Status        Cost    Time
abc123..  2026-06-07    bug_fix_001_off_by_one  cheap       passed        $0.013  120s
def456..  2026-06-07    bug_fix_001_off_by_one  strong      passed        $0.087  95s
ghi789..  2026-06-07    refactor_001_extract    cheap       failed        $0.041  200s
```

### 7.2 `argos eval run <task_id> [--model <tier>]`

```bash
$ argos eval run bug_fix_001 --model cheap
[eval] task=bug_fix_001 model=cheap worktree=~/.argos/eval/worktrees/abc123
[eval] setup.sh ... OK
[eval] agent loop running ...
[eval] verdict=passed detail="5 passed in 0.5s"
[eval] result: abc123 passed  $0.013  120s
[eval] cleanup worktree
```

### 7.3 `argos eval compare <task_id> <model_a> <model_b>`

```bash
$ argos eval compare bug_fix_001 cheap strong
[eval] running cheap ...
[eval] running strong ...
[eval] report: ~/.argos/eval/reports/ab-bug_fix_001-2026-06-07.md
[eval]   cheap  passed  $0.013  120s
[eval]   strong passed  $0.087  95s
[eval]   diff:  strong cheaper-by-7x? (cheap=passed at 1/6 cost)  → cheap wins
```

### 7.4 `argos eval corpus`

```bash
$ argos eval corpus
corpus version 1 (14 tasks)
  bug_fix (5):
    bug_fix_001_off_by_one            easy
    bug_fix_002_path_join             easy
    ...
  refactor (3):
    refactor_001_extract_helper       medium
    ...
  test_write (3):
  doc (3):
```

## 8. TUI 集成

### 8.1 `/eval` 命令

无参时:列最近 20 条 run + 摘要(pass rate per model_tier per category)。

```
/eval
Eval runs (recent 20)
  Date          Task                    Tier      Status    Cost    Time
  2026-06-07    bug_fix_001             cheap     passed    $0.013  120s
  2026-06-07    bug_fix_001             strong    passed    $0.087  95s
  2026-06-07    refactor_001            cheap     failed    $0.041  200s

Pass rate (last 7 days):
  cheap   bug_fix: 3/4 (75%)  refactor: 1/2 (50%)  test_write: 2/2 (100%)
  strong  bug_fix: 4/4 (100%) refactor: 2/2 (100%) test_write: 2/2 (100%)
```

### 8.2 `/eval run <task_id>`

转后台跑(`/runs` 接管显示进度)还是 sync 跑?
- **本期 v1**:`sync` 跑(用户要等,但 eval 通常 ≤ 5 分钟,acceptable)
- 跑完 → transcript 落 `EvalResult` 一行;同结果写 JSONL
- 进度:Transcript 落 `eval started` / `step 3/30` / `verdict=passed` / `done`

### 8.3 `/eval compare <a> <b>`

`<a>` / `<b>` 是 run_id 或 `task_id+model` 组合(如 `bug_fix_001:cheap`)。
- 找到两个 EvalResult
- 渲 markdown 报告(与 CLI 一样)→ transcript 落大段报告(最多 200 行,过长截断 + 提示
  走 `cat ~/.argos/eval/reports/ab-*.md`)

### 8.4 与 `/runs` 不冲突

- `/runs` 控 daemon run(`#5a` / `#5b`),**写** `~/.argos/daemon/runs/`
- `/eval` 控 eval run(`#7`),**写** `~/.argos/eval/runs/`
- **不**复用 registry / worker(eval 是 sync + 短跑,daemon 是 async + 长跑)

## 9. 诚实防线(关键)

### 9.1 pass_status 推导图

```
            ┌─ setup.sh failed?  → setup_failed
            │
            ├─ LLM/crash?        → error
            │
run_pair() ─┤
            ├─ verify 退出 0     → passed
            │
            ├─ verify 退出非 0   → failed
            │
            ├─ verify 超时       → failed
            │
            └─ 篡改检测触发      → unverifiable
```

**绝不允许**:
- ❌ "LLM 说完成" → 标 passed(必须 verify_cmd 退出 0)
- ❌ 跳过 verify_cmd 标 passed(无 verify_cmd → unverifiable)
- ❌ LLM 自我报告 token 数(必须 API 返的 `usage` 字段)
- ❌ 重试 3 次后取"最好一次"算 passed(失败就是失败)

### 9.2 成本诚实

```python
# 在 loop 的 cost_update 事件 listener 里累加
def _on_cost(ev):
    self._cost_usd += ev.cost_usd or 0.0
    self._tokens_in += ev.tokens_in
    self._tokens_out += ev.tokens_out
```

- `cost_usd is None` → `result.cost_usd = None`(沿用 daemon D9 语义,UI 显 "$N/A")
- 重复成本累加 = 跑两个 eval 时各 task 独立,不汇总

### 9.3 篡改可见(沿用 verify 门 + runtime 篡改检测)

- `project_mode` 跑 task → `runtime.guard_project_tests` 在 setup 后、agent 动手前快照
- `Verifier.verify` 调 `runtime.detect_tampering()` → 触发 → `unverifiable`
- 报告里 `tampered` 字段非空 → 用户能看见

### 9.4 跑过 → 不复跑

- 同 `(task_id, model_tier, corpus_version)` 已 `passed` 7 天内 → 跳过 + transcript 显
  "最近 7 天内已 pass,skip"(D5 regression 基础)

## 10. 错误处理

| 失败 | 行为 |
|---|---|
| `corpus/<id>/goal.md` 不存在 | `eval run` 报 `corpus_error: missing goal.md` |
| `verify_cmd` 不在白名单 | `Verifier.verify` 返 failed(沿用 §6 既有行为) |
| `WorktreeManager.create` 抛 WorktreeError | 整 task 标 `error` + 详细 stderr |
| LLM 限流 429 | loop 自然 fail → `error: rate_limited` |
| Budget 超时(> 600s) | `loop.cancel` + `error: budget_exceeded` |
| JSONL append IO 错误 | 内存返结果,stderr warning(不阻塞主流程) |
| Report 写盘失败 | transcript 显结果,markdown 不写;CLI 警告 |
| 同 task_id 跑两个并发 | 文件名 collision → 第二个加 `.<n>` 后缀 |
| Setup 跑过 600s | `setup_failed: setup_timeout` |
| 模型 profile 不存在 | CLI/TUI 报 `unknown_model_tier: <name>` |

## 11. 测试(6 文件,+ ~40 测试)

| 文件 | 覆盖 | 估测数 |
|---|---|---|
| `tests/test_eval_corpus.py` | `load_task` 解析、缺文件/坏 JSON、corpus.json 读 | 6 |
| `tests/test_eval_runner.py` | `run` 端到端(fake model + 真 verify),capture cost/time/pass | 8 |
| `tests/test_eval_worktree.py` | worktree 创建/cleanup/fallback 走通(`#5b` 已覆盖大部分,加 eval 特化) | 4 |
| `tests/test_eval_results.py` | JSONL 读/写/列表/单 run 加载 | 5 |
| `tests/test_eval_compare.py` | `run_pair` + 报告生成 + side-by-side 字段 | 5 |
| `tests/test_eval_cli.py` | `eval list` / `run` / `compare` / `corpus` 命令 + 输出格式 | 6 |
| `tests/test_eval_tui.py` | TUI `/eval` / `/eval run` / `/eval compare` 命令 | 5 |
| **合计** | | **~39** |

### 11.1 端到端铁证

`tests/test_eval_e2e.py`:
- 起 1 个真 fake model(模拟跑 30 步 + 1 次 verify pass)
- 跑 `bug_fix_001_off_by_one` cheap → result.passed
- 跑同 task strong → result.passed
- 跑 `refactor_001` cheap → result.failed(模拟弱模型改坏 verify)
- `run_pair` 返 2 个 EvalResult
- 报告生成 → 读 markdown 断言 pass_rate + cost_diff 字段在

## 12. 决策记录(D1-D20)

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | Corpus 维护 | 人工 / LLM 自生成 | **人工(本期 14 个种子)** | 评估"真不可造假"前提;LLM 自生会变成"我问我自己我多聪明" |
| D2 | Result 存储 | JSONL / sqlite | **JSONL(每 run 一文件)** | 沿用 `#5a` / `#5b` 风格;不引新 dep |
| D3 | A/B cost cap | 100% / 50% / 弱模型 ×0.5 | **每 run $1 / 弱模型也按 $1 cap** | 默认公平,默认设预算可控 |
| D4 | Live eval vs replay | 真跑 / 录制回放 | **真跑(本期);replay v1.1** | 录制是"过去多准",不反映"现在多准" |
| D5 | Regression gate | CI fail-on-drop / 仅警告 | **本期仅警告(v1.1 接 CI)** | 改 CI 接是单独工作 |
| D6 | Task difficulty 评分 | 人标 / LLM 估 | **人标(容易/中/难)** | LLM 估又会变"我估我多聪明" |
| D7 | budget 超时后处理 | 强制 cancel / 自然 fail | **cancel + 标 failed** | 防止弱模型"靠时长赢" |
| D8 | 跑过跳过窗口 | 不跳 / 1d / 7d / 30d | **7d 内同 (task, model, corpus_version) 跳过** | 防"我测了 100 次取最好一次" |
| D9 | Worktree 路径 | 复用 `#5b` `~/.argos/worktrees` / eval 独立 | **eval 独立 `~/.argos/eval/worktrees`** | 语义不混;eval 跑过的产物由 eval 管 |
| D10 | cost 字段精度 | int / float / Decimal | **float(USD 8 位有效数字)** | 沿用 `#5b` D9 |
| D11 | Eval 跨平台 | macOS only / 全平台 | **跨平台(macOS 真跑,Linux/Windows 跑 verify 白名单依赖)** | sandbox 已跨平台,跑 eval 无新约束 |
| D12 | verify_cmd 沙箱 | 走 sandbox / host 跑 | **host 跑(Argos 本身当 verify_cmd 跑)** | eval 是 dogfooding,在 eval 任务里再开 sandbox 是套娃 |
| D13 | CLI 默认 model | 提示选 / default = 活动 profile | **用 config.json 活动 profile** | 与 TUI 默认一致 |
| D14 | Report 格式 | md / json / html | **md(本地可读) + json(机读)** | md 给用户,json 给后续自动化 |
| D15 | 跑 A/B 时复用 worktree | 复用 / 独立 | **独立(每 run_id 一 worktree,清理独立)** | 隔离稳态,失败互不影响 |
| D16 | 失败 worktree cleanup | 留 / 立即删 | **立即删(留只在 `error` 标 `keep_worktree: true` 时保留供 inspect)** | 磁盘省;`--keep` flag 给调试用 |
| D17 | TUI /eval 与 /runs 互斥 | 独立 / 互斥 | **独立(eval 是 sync 短跑,不进 daemon registry)** | 语义正交 |
| D18 | 任务引入新文件 | 允许 / 限制 | **允许(refactor 任务可能新建文件)** | `expected_files` 给出建议列表,失败不致命 |
| D19 | Eval 限速 | 无 / daemon 5 并发 / 1 串行 | **本期 1 串行(v1.1 限 3 并发)** | LLM 限流 + 单机内存 + 用户认知 |
| D20 | 报告存哪里 | `~/.argos/eval/reports/` / 项目内 | **同 JSONL 一目录(用户态数据)** | 沿用数据规约原则 |

## 13. 风险与未来

- **风险 1**:corpus 14 个种子太少,统计无意义 → v1.1 扩到 50+,本期诚实标"小样本,看趋势"
- **风险 2**:Argos 跑自己的代码改动会让 corpus 文件被 agent 改 → `expected_files` 是
  建议,非强制;v1.1 加 worktree 后 snapshot 比对
- **风险 3**:不同模型 provider 返的 cost 字段粒度不同(Anthropic / OpenRouter / 自托管) →
  统一走 `usage.input_tokens` + `usage.output_tokens`,USD 由 Argos config 的 `pricing`
  算
- **风险 4**:跑完 `pass` 不代表用户满意(用户期望可能比 verify 更宽) → v1.1 加
  `human_rating` 字段,人工 1-5 打分
- **未来 v1.1**:
  - `eval/leaderboard.html` 本地浏览器打开(看趋势图)
  - `eval record <run_id>` → 录回放(replay mode)
  - `eval ci` 模式(检测 pass rate 下降)
  - corpus 自检任务(`security-review` 自己输出 → 再 `/security-review` 审)
  - 跨项目(`eval` 跑任意用户 repo,而非仅 Argos)

## 14. 实施任务(对应 plan)

10 任务,1 任务 = 1 commit,完整 TDD:
1. corpus schema + 14 个种子任务落盘
2. Eval runner 核心 `run()` (fake model + 真 verify)
3. Worktree 集成(`#5b` WorktreeManager 复用,加 fallback 处理)
4. Result JSONL 持久化 + `list_runs` / `load_run`
5. A/B 对比报告生成器(md + json)
6. `argos eval` CLI 子命令
7. TUI `/eval` slash 命令
8. TUI `/eval run <task_id>` + `/eval compare <a> <b>`
9. CHANGELOG + docs/eval.md + README 段
10. 验收:全量 pytest + e2e 铁证 + 6 个 seed task 真跑一遍

> 实际 plan 拆 9-10 任务,见 `2026-06-07-agent-eval.md`。
