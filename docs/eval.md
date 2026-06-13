# Agent 自我评估 (`/eval` & `argos eval`) — 用户文档

> 让 Argos 跑真实的、有数字的、能贴 A/B 报告的 dogfooding 评估。
> 护城河延伸:不是"我有个 graph 界面",是"我有量化数字证明我的 verify 门 + 诚实协议
> 让便宜模型不掉链子"。

## 1. 这是什么

Argos 内置一个**自评估子包** `argos_agent.eval/`,让 Argos 跑一份**任务题库**(`corpus`),
量化 pass rate / time / cost,做 A/B 对比,**dogfooding**(Argos 测 Argos)。

护城河 3 句话:
1. **诚实防线贯穿到底** —— `passed` 标志 = verify_cmd 退出码 0,**不**信 LLM 自我报告
2. **量化数字** —— pass rate / time / cost / steps,JSONL append-only 真相源
3. **A/B 报告** —— side-by-side markdown 报告,谁 pass 谁 cost 低

## 2. 何时用

- **新增工具 / 改 verify 门** 后,跑 `argos eval run bug_fix_001` 验证没回归
- **换 model tier 前**,跑 `argos eval compare bug_fix_001 cheap strong` 看效果差异
- **v0.1.0 之后的护城河守护**:每次 release 前跑全 corpus,看 pass rate 下降没
- **跨平台 / 跨 Python 版本** smoke:同一 corpus,不同环境,跑出数字对比

## 3. 30 秒上手

### 3.1 CLI

```bash
# 1. 看 corpus 任务清单
$ argos eval corpus
corpus version 1 (14 tasks)
  bug_fix (5):
    bug_fix_001_off_by_one            easy
    ...
  refactor (3):
  test_write (3):
  doc (3):

# 2. 跑单个
$ argos eval run bug_fix_001_off_by_one
[eval] task=bug_fix_001_off_by_one category=bug_fix difficulty=easy
[eval] running model=cheap budget=$1.00 600s ...
[eval] passed  cost=$0.0130  duration=120s  steps=8  run_id=abc123def456

# 3. A/B 对比
$ argos eval compare bug_fix_001_off_by_one cheap strong
[eval] A/B: cheap vs strong on bug_fix_001_off_by_one ...
[eval]   cheap       passed  $0.0130  120s
[eval]   strong      passed  $0.0870  95s
[eval] report: ~/.argos/eval/reports/ab-bug_fix_001_off_by_one-2026-06-07.md
[eval] json:   ~/.argos/eval/reports/ab-bug_fix_001_off_by_one-2026-06-07.json

# 4. 看历史
$ argos eval list --limit 20
Run ID    Date          Task                    Tier        Status        Cost    Time
abc123..  2026-06-07    bug_fix_001_off_by_one  cheap       passed        $0.013  120s
def456..  2026-06-07    bug_fix_001_off_by_one  strong      passed        $0.087  95s
```

### 3.2 TUI

```text
/eval                                   # 列最近 20 run + 7d pass rate
/eval run bug_fix_001_off_by_one         # 跑单个(sync,等 ≤ 5 分钟)
/eval compare bug_fix_001:cheap bug_fix_001:strong    # A/B 报告渲到 transcript
```

## 4. corpus 任务题库

### 4.1 14 个种子任务(本期)

| Category | 数量 | 用意 |
|---|---|---|
| bug_fix | 5 | 主战场:agent 能不能修真 bug |
| refactor | 3 | 看不破坏行为的重构能力 |
| test_write | 3 | TDD 场景,verify 门常用路径 |
| doc | 3 | 最容易的类别,流程跑通验证 |

### 4.2 任务结构

`~/.argos/eval/corpus/<task_id>/`
```
├── goal.md          # LLM 拿这一段当 user message
├── verify_cmd       # 单行 shell,退出码 0 = pass
├── setup.sh         # (可选)准备环境
├── category         # "bug_fix" | "refactor" | "test_write" | "doc"
├── difficulty       # "easy" | "medium" | "hard"
├── expected_files   # (可选)glob 列表
└── notes.md         # (可选)维护笔记(首行 = title)
```

`corpus.json` 顶层清单(版本号 + 任务元数据):

```json
{
  "version": 1,
  "tasks": [
    {"id": "bug_fix_001_off_by_one", "category": "bug_fix",
     "difficulty": "easy", "title": "修复 median off-by-one",
     "estimated_minutes": 5}
  ]
}
```

### 4.3 加新任务

```bash
mkdir -p ~/.argos/eval/corpus/my_new_task
cat > ~/.argos/eval/corpus/my_new_task/goal.md <<EOF
Fix the off-by-one in memory/auto.py _score (负 last_used_at 应截 0)
EOF
echo 'python3 -m pytest tests/test_memory_decay.py -q' > ~/.argos/eval/corpus/my_new_task/verify_cmd
echo 'bug_fix' > ~/.argos/eval/corpus/my_new_task/category
echo 'medium' > ~/.argos/eval/corpus/my_new_task/difficulty
# 同步加到 corpus.json
```

`verify_cmd` 设计原则:
- **客观** —— 退出码 0 = pass,不是"代码长得好不好看"
- **快** —— ≤ 30s 跑完
- **白名单** —— `Verifier.verify` 走 ALLOWED_CMDS(定义于 `argos_agent/tools/__init__.py`,由 `core/verify_gate.py` 导入)

## 5. 报告解读

### 5.1 Markdown 报告

`~/.argos/eval/reports/ab-<task_id>-<date>.md`:

```markdown
# A/B Eval Report: bug_fix_001_off_by_one

| Field | A (model=cheap) | B (model=strong) |
|---|---|---|
| pass_status | passed | passed |
| duration_s | 120.0 | 95.0 |
| tokens_in | 1000 | 5000 |
| tokens_out | 500 | 2000 |
| cost_usd | $0.0130 | $0.0870 |
| steps | 8 | 12 |

**Pass winner**: `tie`
**Cost winner**: `a`   ← cost_usd 小的胜

## Goal
[goal text]

## A verify_cmd output
[stdout/stderr]
```

### 5.2 JSON 报告(机读)

`~/.argos/eval/reports/ab-<task_id>-<date>.json`:

```json
{
  "task_id": "...",
  "corpus_version": 1,
  "a": { ...EvalResult... },
  "b": { ...EvalResult... },
  "winner_pass": "tie" | "a" | "b",
  "winner_cost": "a" | "b" | "tie" | "unknown"
}
```

## 6. 诚实防线(关键)

| 失败 | 行为 | `pass_status` |
|---|---|---|
| setup.sh 退出非 0 | abort | `setup_failed` |
| LLM / 限流 / IO 异常 | abort | `error` |
| verify_cmd 未配置(None) | 诚实完成,标注未测试 | `unverifiable`(NO_TEST) |
| verify_cmd 退出 0 | pass | `passed` |
| verify_cmd 退出非 0 | fail | `failed` |
| 篡改检测触发 | 不可信 | `unverifiable` |

**绝不允许**:
- LLM 自我报告 token / cost(必须 API 返 `usage`)
- 跳过 verify 标 passed(无 verify_cmd → `unverifiable`)
- 重试 N 次后取最好一次算 passed(失败就是失败)

## 7. 数据目录

```
~/.argos/eval/
├── corpus/                          # 14 任务(用户可改)
│   ├── corpus.json
│   └── bug_fix_001_off_by_one/
│       ├── goal.md
│       └── verify_cmd
├── runs/                            # JSONL append-only
│   └── 2026-06-07/
│       └── abc123def456.jsonl       # 每 run 1 文件,1 行
├── reports/                         # A/B 报告(md + json)
│   ├── ab-bug_fix_001-2026-06-07.md
│   └── ab-bug_fix_001-2026-06-07.json
└── worktrees/                       # 临时 worktree(终态 cleanup)
```

## 8. CLI 参考

```
argos eval list [--limit N]                       # 列最近 run + 摘要
argos eval run <task_id> [--model T] [--budget $] [--budget-s S] [--keep-worktree]
argos eval compare <task_id> <model_a> <model_b> [...] # A/B
argos eval corpus                                 # 列 corpus 任务
```

## 9. 故障排查

| 问题 | 检查 |
|---|---|
| `eval` 命令 unknown | `python -c "import argos_agent.eval"` 确认包可导入 |
| `LoopFactory required` | CLI `argos eval run` 默认使用 fake 桩(无需真实 LLM key);如需真实模型运行,请使用 TUI `/eval run` 或在代码中传入 `loop_factory` |
| 报告不写盘 | `~/.argos/eval/reports/` 权限;或 `keep_worktree` flag 留下的 worktree |
| 任务找不到 | `argos eval corpus` 看清单;task id 区分大小写 |

## 10. 不做(本期)

- ❌ 在线 leaderboard(本地 + 私享)
- ❌ 跨项目 eval(本期只 dogfooding Argos 自己)
- ❌ 沙箱外网络 eval(verify_cmd 走 ARGOS sandbox 白名单)
- ❌ CI 自动 fail-on-drop(计划中,尚未实现)
- ❌ Eval 自动答题(LLM 不生任务,人维护 corpus 防"我测我多聪明"循环)
- ❌ 统计显著性检验(样本小,t 检验不适用)
