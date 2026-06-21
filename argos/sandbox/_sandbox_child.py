"""沙箱子进程入口 —— 被 sandbox-exec(Seatbelt)包着执行。

协议(host ←→ child,经 stdin/stdout 各一行 JSON):
  host→child: {"op":"init","authorized_imports":[...]}            建执行器
              {"op":"exec","code":"..."}                          跑一段代码
              {"op":"close"}                                       退出
  child→host: {"type":"exec_result","stdout":..,"value_repr":..,"exc":..}
              {"type":"broker_call","action":..,"args":..}         broker-gated 工具发起 RPC(Task 8)
  host→child(对 broker_call 的回应): {"type":"broker_reply","value":..}

smolagents API 实测(v1.26.0):
  · executor(code) 返回 CodeOutput; .output = 末尾表达式值; .logs = stdout 字符串
  · 执行异常时 smolagents 抛 InterpreterError(不返回对象)
  · 状态跨调用存活在 executor.state dict

本文件【在沙箱内】运行 —— 绝不持有 HMAC key、绝不直接做网络/越界写。
broker-gated 工具体只把请求写 stdout,真副作用在 host 侧 broker 执行后把结果 reply 回来。
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from argos.i18n import t


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


class _BrokerStub:
    """沙箱内可见的 broker 代理(契约 §4 broker-call 约定)。
    工具函数体调 _broker.request(...);本 stub 把请求写 stdout,阻塞等 host 的 broker_reply。"""

    def request(self, action: str, args: dict[str, Any]) -> Any:
        _emit({"type": "broker_call", "action": action, "args": args})
        while True:
            msg = _read()
            if msg is None:
                return t("core2.sandbox_child.broker_closed")
            if msg.get("type") == "broker_reply":
                return msg.get("value")
            # 其它消息(理论上不会有)忽略,继续等 reply。


def _build_namespace(
    broker: _BrokerStub,
    allow_workflow: bool = True,
    read_only: bool = False,
    tool_allowlist: "list[str] | None" = None,
) -> dict[str, Any]:
    """子进程内构造工具命名空间。纯沙箱工具直接用 tools.files 的原函数;
    broker-gated 工具用调 broker 的薄包装。
    allow_workflow=False 时去掉 propose_workflow(子 agent 深度护栏)。
    tool_allowlist 非 None 时为角色白名单(权威):命名空间 = 可用 ∩ 白名单(覆盖 read_only 派生);
    read_only=True(且无白名单)时剔除写工具(旧 tool_scope=read 路径强制只读)。"""
    from argos.tools import build_child_namespace
    return build_child_namespace(
        broker, allow_workflow=allow_workflow, read_only=read_only,
        tool_allowlist=tool_allowlist,
    )


def main() -> None:
    executor = None
    broker = _BrokerStub()
    while True:
        msg = _read()
        if msg is None:
            break
        op = msg.get("op")
        if op == "init":
            from smolagents.local_python_executor import LocalPythonExecutor
            imports = msg.get("authorized_imports") or ["json", "re", "pathlib", "math",
                                                         "itertools", "collections", "datetime"]
            # T7:os/sys/pathlib 必须在白名单 —— prepend 的 `import os, sys, pathlib`(line ~106)
            # 走 authorized_imports 检查,缺一会 InterpreterError。host 自定义列表场景也得有。
            # 用 set 去重 + 保序追加,顺序无关紧要(白名单是 membership 测试)。
            for _need in ("os", "sys", "pathlib"):
                if _need not in imports:
                    imports = list(imports) + [_need]
            allow_workflow = msg.get("allow_workflow", True)
            read_only = msg.get("read_only", False)
            tool_allowlist = msg.get("tool_allowlist")   # None=无角色白名单(走 read_only 派生)
            executor = LocalPythonExecutor(additional_authorized_imports=imports)
            executor.send_tools(_build_namespace(broker, allow_workflow, read_only, tool_allowlist))
            # T7:agent 普遍用 os.path / sys.exit / pathlib 不写 import 会 NameError;
            # 预注入 stdlib 到 executor 命名空间(已经过 authorized_imports 白名单审查,
            # 这些 stdlib 放行对攻击面无可见扩张 —— 不会让 agent 联网 / 写非 workspace 路径)。
            import os as _os_t7
            import sys as _sys_t7
            import pathlib as _pathlib_t7
            executor.state["os"] = _os_t7
            executor.state["sys"] = _sys_t7
            executor.state["pathlib"] = _pathlib_t7
            _emit({"type": "init_ok"})
        elif op == "exec":
            if executor is None:
                _emit({"type": "exec_result", "stdout": "", "value_repr": "",
                       "exc": "RuntimeError: executor not initialized"})
                continue
            code = msg.get("code", "")
            # T7:agent 用 os.path / sys.exit / pathlib 不写 import 会 NameError。
            # pre-inject 到 state["os"] 不够:smolagents 拦 getattr(os, "path") 走 module 拒绝
            # (posixpath 不在白名单);改 prepend 三个 import 到 code 头,等价于"用就用别想太多"。
            # 已有同名绑定的不会冲突(import 即 rebind)。
            code = "import os as __argos_os_t7, sys as __argos_sys_t7, pathlib as __argos_pathlib_t7\n" + code
            stdout = ""
            value_repr = ""
            exc = ""
            try:
                from smolagents.local_python_executor import InterpreterError
                result = executor(code)
                # smolagents v1.26.0: result.logs = stdout, result.output = last expr value
                stdout = result.logs or ""
                if result.output is not None:
                    value_repr = repr(result.output)
            except Exception:  # noqa: BLE001 —— 沙箱内任何异常都作为数据回 host
                exc = traceback.format_exc(limit=8)
            _emit({"type": "exec_result", "stdout": stdout,
                   "value_repr": value_repr, "exc": exc})
        elif op == "close":
            break
        else:
            _emit({"type": "error", "message": f"unknown op {op!r}"})


if __name__ == "__main__":
    main()
