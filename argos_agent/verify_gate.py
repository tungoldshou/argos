"""verify 硬门禁 middleware —— Argos 的核心护城河。

让"完成"绕不过验证:当 agent 给出最终答案(不再调工具)时,如果这次任务带了
可机检的验证命令(verify_cmd),就【强制】跑一遍。退出码非 0 → 把真实报错喂回模型
并【重新让它生成】,逼它继续修;退出码 0 → 放行。达 max_rounds 仍不过 → 诚实升级,
让模型如实向用户报告"卡住了、试过什么、需人工指路",绝不允许谎称完成。

实现用 `wrap_model_call`(LangChain 官方 retry 同款 hook):它包住模型调用、能在一个
step 内多次重新调用 handler,从而真正让 loop 继续 —— 而 after_model 只能追加消息、
不保证重新触发模型(实测会让 loop 提前停)。
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from . import runtime
from .tools import ALLOWED_CMDS, _vd, _ws


def _run_verify(cmd: str) -> tuple[bool, str]:
    """跑验证命令,返回 (是否通过, 细节)。退出码是 ground truth。

    安全关键:验证在 VERIFY_DIR(agent 写不到)里跑,而非 workspace —— 防止 agent
    篡改评判它的测试来作弊(实测漏洞)。同时把 WORKSPACE 放进 PYTHONPATH,使验证脚本
    能 import agent 在 workspace 里写的解。这样 agent 改得了"被测的解",改不了"测试本身"。
    """
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return False, f"验证命令解析失败:{e}"
    if not parts or Path(parts[0]).name not in ALLOWED_CMDS:
        return False, f"验证命令不在白名单:{cmd}"
    workspace, verify_dir = _ws(), _vd()
    verify_dir.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    import os
    env = dict(os.environ)
    # workspace 优先在 path 上,验证脚本 import 到的是 agent 写的解。
    # 沙盒模式:cwd=verify_dir(隔离,agent 改不到测试)。
    # 项目模式:verify_dir==workspace==用户项目,在项目里跑用户自己的测试(篡改可见见 runtime)。
    env["PYTHONPATH"] = str(workspace) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        r = subprocess.run(
            parts, cwd=verify_dir, capture_output=True, text=True, timeout=60, env=env
        )
    except Exception as e:
        return False, f"验证执行失败:{e}"
    detail = f"[exit_code={r.returncode}]\n{(r.stdout or '')[-1500:]}\n{(r.stderr or '')[-1500:]}".strip()
    return r.returncode == 0, detail


def _is_final_answer(msg) -> bool:
    """模型这次输出是否是"最终答案"(AIMessage 且没有要调的工具)。"""
    return isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None)


class VerifyGateMiddleware(AgentMiddleware):
    """完成必须过验证,否则喂回失败强制重新生成;反复不过则诚实升级。"""

    BOUNCE_TAG = "[Argos 验证门]"
    ESCALATION_TAG = "[Argos 升级·需人工]"
    UNVERIFIABLE_TAG = "[Argos 验证门·无法验证]"

    def __init__(self, verify_cmd: str | None, max_rounds: int = 3):
        super().__init__()
        self.verify_cmd = verify_cmd
        self.max_rounds = max_rounds
        # 对外暴露的状态(server/UI 据此区分"真完成"vs"卡住升级")。
        self.escalated = False
        self.attempts = 0
        self.last_failure = ""
        # 实例级累计(跨整个 run 的所有 wrap_model_call,不是每次 call 重置)——
        # 之前的 bug 正是把它做成局部变量,每个 step 归零,导致永远到不了升级条件、死循环。
        self._fail_count = 0
        # 篡改硬门:agent 改动了受保护测试 → 验证结果不可信,判 unverifiable(区别于 failed)。
        self.unverifiable = False
        self.tampered: list[str] = []

    def wrap_model_call(self, request, handler):  # type: ignore[override]
        if not self.verify_cmd:
            return handler(request)

        response = handler(request)
        result = list(response.result)
        last = result[-1] if result else None

        # 不是最终答案(还要调工具)→ 不验证,放行让它去调工具(下一个 step 再来)。
        if not _is_final_answer(last):
            return response

        # 是最终答案 → 核实"完成"是不是真的。
        ok, detail = _run_verify(self.verify_cmd)

        # 防作弊硬门(优先于退出码):若 agent 在本 run 内改动了受保护的测试文件,
        # 哪怕退出码为 0,这个"通过"也不可信 —— 判 unverifiable 并诚实升级,绝不蒙混。
        # 沙盒模式 guarded 为空 → detect_tampering 返回 [],此处自然无操作。
        tampered = runtime.detect_tampering()
        if tampered:
            self.unverifiable = True
            self.tampered = tampered
            self.attempts = self._fail_count
            honest = AIMessage(content=(
                f"{self.UNVERIFIABLE_TAG} 我检测到验证依赖的测试文件被改动了:"
                f"{', '.join(tampered)}。所以这次的'通过'不可信 —— 我【无法确认】任务真的完成,"
                f"也不会假装成功。请你检查/恢复这些文件后再让我重做。"
            ))
            response.result = result[:-1] + [honest]
            return response

        if ok:
            return response  # 验证真过 → 这次完成是真的

        self.last_failure = detail
        self._fail_count += 1

        # 累计失败达上限 → 诚实升级,终止(把最终答案换成诚实的"卡住"声明,不再 retry)。
        if self._fail_count > self.max_rounds:
            self.escalated = True
            self.attempts = self._fail_count - 1
            honest = AIMessage(content=(
                f"{self.ESCALATION_TAG} 我已尝试 {self.max_rounds} 轮,仍无法通过验证命令 "
                f"`{self.verify_cmd}`。最后一次失败:\n{detail}\n"
                f"我没有搞定这个任务,需要你介入指路 —— 我不会假装它已完成。"
            ))
            response.result = result[:-1] + [honest]
            return response

        # 还有轮数 → 当场把真实失败喂回模型重新生成一次(在本 wrap 内即时重试)。
        bounce = HumanMessage(content=(
            f"{self.BOUNCE_TAG} 你声称完成,但验证命令 `{self.verify_cmd}` 没通过。"
            f"这是真实结果,你无法绕过它:\n{detail}\n"
            f"请用工具定位并修复,改完再说完成。"
        ))
        new_request = request.override(messages=[*request.messages, last, bounce])
        return handler(new_request)
