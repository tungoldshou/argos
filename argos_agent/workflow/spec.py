"""声明式工作流规格(IR)+ 校验。agent 经 propose_workflow({...}) 提议;parse_spec 把原始 dict
校验成不可变 spec —— fail-closed:任何非法字段/引用/枚举即抛 WorkflowSpecError(诚实拒,不起子 agent)。

角色(role)—— 子 agent 的"独立上下文/工具/提示词/上限"封装(任务:单模型也能靠角色拿收益)。
role 可选,不填 → 沿用 tool_scope 派生(向后兼容,旧 spec 不破)。
role 填了 → subagent 套角色预设的工具白名单(派生 read_only)+ system_prompt 前缀注入 +
max_steps 派生。verifier 门与角色独立(coder 缺 verify 走既有 NO_TEST 诚实路径)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# 合法 op 集合
_OPS = {"fan_out", "pipeline", "panel", "loop_until", "synthesize", "best_of_n"}
# 合法 tool_scope 枚举
_SCOPES = {"read", "full"}
# 合法 isolation 枚举
_ISOLATION = {"none", "worktree"}
# 合法 role 枚举(任务:每个角色独立上下文+工具+提示词+上限)
_ROLES = ("explorer", "planner", "coder", "reviewer")
# 单 stage 并发上限
_MAX_CAP = 16
# 单 workflow 最大 stage 数
_MAX_STAGES = 12
# best_of_n 候选数范围(下限 1,上限同 _MAX_CAP,默认 3)
_BEST_OF_N_DEFAULT = 3
_BEST_OF_N_MAX = _MAX_CAP


class WorkflowSpecError(ValueError):
    """spec 校验失败(诚实 fail-closed)。"""


# ── 角色预设(任务:子 agent 角色系统)──────────────────────────────────────
# 4 角色 = 工具白名单 + 系统提示词片段 + 迭代上限 + 是否只读 + 是否强制 verify。
# 单模型配置下全部 4 角色可跑(走 default profile);多模型时 role 可与 by_category 路由联
# 动(本任务只定契约,不接 routing,见 subagent.py 派生路径)。

# 工具白名单 = frozenset 字符串名;None 表示该角色派生 read_only(由 subagent 算)。
# subagent 派生时:角色白名单 ∩ build_child_namespace 默认 ns → 物理剔除其余工具。
# (build_child_namespace 的 read_only=True 已经剔除 write_file/edit_file/run_command/
#  browser_click/browser_type/mcp_call;explorer/planner/reviewer 复用此钩子,coder 不复用。)

# 共享只读工具集(4 角色都准用):纯沙箱只读 + broker-gated 只读(网络/浏览器只看不写)。
_ROLE_READ_TOOLS = frozenset({
    # 纯沙箱(不需 broker)
    "read_file", "search_files", "propose_verify", "update_plan",
})


@dataclass(frozen=True, slots=True)
class _RolePreset:
    """单个角色预设(内部使用,不在公共契约里 export)。"""

    name: str
    tool_allowlist: frozenset
    system_prompt: str
    max_steps: int
    read_only: bool
    requires_verify: bool


ROLE_PRESETS: dict[str, _RolePreset] = {
    "explorer": _RolePreset(
        name="explorer",
        tool_allowlist=_ROLE_READ_TOOLS,
        system_prompt=(
            "你处于 explorer(只读侦察)角色。\n"
            "- 只能读文件、检索、查网络、看浏览器;不准写文件、不准改代码、不准跑会改状态的命令。\n"
            "- 任务是收集情报与定位代码,不产出最终代码改动。\n"
            "- 若需写,告诉调用方让你走 coder 角色(子 agent 沙箱不给你写工具)。"
        ),
        max_steps=12,
        read_only=True,
        requires_verify=False,
    ),
    "planner": _RolePreset(
        name="planner",
        tool_allowlist=_ROLE_READ_TOOLS | frozenset({"propose_workflow"}),
        system_prompt=(
            "你处于 planner(规划)角色。\n"
            "- 只产方案不执行;沙箱工具在 plan mode 会被 dispatcher 拦(plan mode 守卫见 plan_mode.py)。\n"
            "- 你的产出 = 一段可被父 agent 审阅的方案(可用 propose_workflow 提一份工作流草稿)。\n"
            "- 不要假装执行了什么 —— 沙箱是独立子进程,parent 拿不到你的本地状态。"
        ),
        max_steps=8,
        read_only=True,
        requires_verify=False,
    ),
    "coder": _RolePreset(
        name="coder",
        # coder 工具白名单 = 全部准用(显式列,可审计;语义 = "派生 read_only=False 时的全集")。
        # 包含 explorer 全集 + 写工具 + 浏览器写 + mcp_call + propose_workflow(允许子 agent 派生)。
        tool_allowlist=_ROLE_READ_TOOLS | frozenset({
            "write_file", "edit_file", "run_command",
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_screenshot", "mcp_call",
            "web_search", "web_extract", "propose_workflow",
            "lsp_definition", "lsp_references", "lsp_hover",
            "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics",
        }),
        system_prompt=(
            "你处于 coder(编码)角色。\n"
            "- 拥有全部写工具(write_file/edit_file/run_command + 浏览器写 + mcp_call)。\n"
            "- 完成前必须 propose_verify('<测试/编译/lint 命令>') 声明真验证;host 会独立跑。\n"
            "- 没声明 verify → 走 'NO_TEST'(未机检验证)诚实路径,绝不会判 passed —— 不会撒谎。\n"
            "- 防篡改:verify 在隔离 verify_dir 跑,你碰不到执行,改了评判你的测试也救不了假绿。"
        ),
        max_steps=20,
        read_only=False,
        requires_verify=True,
    ),
    "reviewer": _RolePreset(
        name="reviewer",
        tool_allowlist=_ROLE_READ_TOOLS | frozenset({"run_command", "lsp_diagnostics"}),
        system_prompt=(
            "你处于 reviewer(审查)角色。\n"
            "- 工具集 = explorer + run_command + lsp_diagnostics(看 + 跑检查)。\n"
            "- 不准写文件/编辑代码;产出 = 一段审查意见(具体文件:行号 + 问题)。\n"
            "- 走 verify 门:自动接 detect_tampering(测试被改 → unverifiable,不假装通过)。\n"
            "- 跑测试/lint 时用 propose_verify 声明,host 独立跑退出码为准。"
        ),
        max_steps=10,
        read_only=True,
        requires_verify=True,
    ),
}


@dataclass(frozen=True, slots=True)
class AgentTask:
    """单个子 agent 任务描述。"""

    prompt: str
    model: str | None = None
    tool_scope: str = "read"
    isolation: str = "none"
    verify: str | None = None
    schema: dict | None = None
    # 角色预设(任务:每个角色独立上下文/工具/提示词/上限);None = 不填,沿用 tool_scope 派生。
    role: Optional[str] = None
    # 角色自定义字段保留位:若未来角色需 user 自定义 system_prompt 覆盖(目前未用,留接口)。
    role_overrides: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Stage:
    """工作流中的一个执行阶段。"""

    id: str
    op: str
    agent: AgentTask | tuple[AgentTask, ...]
    over: tuple | dict | None = None
    voters: int = 1
    threshold: int = 1
    target: int | None = None
    max_dry_rounds: int = 2
    cap: int = 4
    # best_of_n 专用:同任务并行 N 个候选(N 个独立 worktree + 独立跑),选最好。
    # 仅 op == 'best_of_n' 时生效;其它 op 忽略。其他 op 视 n 为 None。
    n: int | None = None


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    """完整工作流规格,不可变。"""

    name: str
    description: str
    stages: tuple[Stage, ...]


def _parse_agent(raw: dict) -> AgentTask:
    """解析并校验单个 agent 任务描述。"""
    if not isinstance(raw, dict) or "prompt" not in raw:
        raise WorkflowSpecError("agent 缺 prompt")
    scope = raw.get("tool_scope", "read")
    if scope not in _SCOPES:
        raise WorkflowSpecError(f"非法 tool_scope:{scope!r}(只允许 {_SCOPES})")
    iso = raw.get("isolation", "none")
    if iso not in _ISOLATION:
        raise WorkflowSpecError(f"非法 isolation:{iso!r}")
    role = raw.get("role")
    if role is not None:
        if role not in _ROLES:
            raise WorkflowSpecError(f"非法 role:{role!r}(只允许 {_ROLES})")
        # role 是高阶抽象:role 存在时,tool_scope 必须与之派生的 read_only 一致;若用户
        # 同时显式填了与 role 矛盾的 tool_scope(role=explorer + tool_scope=full)—— 拒收,
        # 不让 spec 留下歧义(谁说了算)。role 不填则 tool_scope 默认 "read" 旧路径不变。
        preset = ROLE_PRESETS[role]
        if "tool_scope" in raw:
            scope_implies_readonly = (scope == "read")
            if preset.read_only != scope_implies_readonly:
                raise WorkflowSpecError(
                    f"role={role!r} 与 tool_scope={scope!r} 矛盾"
                    f"(role 派生 read_only={preset.read_only},"
                    f"tool_scope=read 派生 read_only={scope_implies_readonly})"
                )
    return AgentTask(
        prompt=str(raw["prompt"]),
        model=raw.get("model"),
        tool_scope=scope,
        isolation=iso,
        verify=raw.get("verify"),
        schema=raw.get("schema"),
        role=role,
        role_overrides=raw.get("role_overrides", {}) or {},
    )


def parse_spec(raw: dict) -> WorkflowSpec:
    """将原始 dict 解析为 WorkflowSpec,任何非法输入立即抛 WorkflowSpecError。"""
    if not isinstance(raw, dict):
        raise WorkflowSpecError("spec 必须是 dict")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise WorkflowSpecError("spec 缺 name")
    stages_raw = raw.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise WorkflowSpecError("spec 缺非空 stages")
    if len(stages_raw) > _MAX_STAGES:
        raise WorkflowSpecError(f"stages 过多(>{_MAX_STAGES})")
    seen_ids: set[str] = set()
    stages: list[Stage] = []
    for sr in stages_raw:
        if not isinstance(sr, dict):
            raise WorkflowSpecError("stage 必须是 dict")
        sid = str(sr.get("id") or "").strip()
        if not sid:
            raise WorkflowSpecError("stage 缺 id")
        if sid in seen_ids:
            raise WorkflowSpecError(f"重复的 stage id:{sid!r}")
        op = sr.get("op")
        if op not in _OPS:
            raise WorkflowSpecError(f"非法 op:{op!r}(只允许 {_OPS})")
        over_raw = sr.get("over")
        over: tuple | dict | None
        if over_raw is None:
            over = None
        elif isinstance(over_raw, list):
            over = tuple(over_raw)
        elif isinstance(over_raw, dict) and "from" in over_raw:
            ref = over_raw["from"]
            if ref not in seen_ids:
                raise WorkflowSpecError(
                    f"over.from 引用了不存在或非更早的 stage:{ref!r}"
                )
            over = {"from": ref}
        else:
            raise WorkflowSpecError(f"非法 over:{over_raw!r}")
        agent_raw = sr.get("agent")
        if isinstance(agent_raw, list):
            agent: AgentTask | tuple[AgentTask, ...] = tuple(
                _parse_agent(a) for a in agent_raw
            )
        else:
            agent = _parse_agent(agent_raw)
        voters = max(1, int(sr.get("voters", 1)))
        threshold = max(1, int(sr.get("threshold", 1)))
        if op == "panel" and threshold > voters:
            raise WorkflowSpecError(
                f"panel threshold({threshold})不可大于 voters({voters})"
            )
        cap = min(int(sr.get("cap", 4)), _MAX_CAP)
        # best_of_n:取 n(默认 3,夹在 1.._BEST_OF_N_MAX 之间)
        if op == "best_of_n":
            try:
                n = int(sr.get("n", _BEST_OF_N_DEFAULT))
            except (TypeError, ValueError):
                raise WorkflowSpecError(
                    f"stage「{sid}」best_of_n 的 n 非法:{sr.get('n')!r}"
                )
            n = max(1, min(n, _BEST_OF_N_MAX))
            n_val: int | None = n
        else:
            n_val = None
        stages.append(
            Stage(
                id=sid,
                op=op,
                agent=agent,
                over=over,
                voters=voters,
                threshold=threshold,
                target=sr.get("target"),
                max_dry_rounds=int(sr.get("max_dry_rounds", 2)),
                cap=max(1, cap),
                n=n_val,
            )
        )
        seen_ids.add(sid)
    return WorkflowSpec(
        name=name,
        description=str(raw.get("description") or ""),
        stages=tuple(stages),
    )
