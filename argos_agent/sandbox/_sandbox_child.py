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
                return "错误:broker 通道关闭,默认拒绝。"
            if msg.get("type") == "broker_reply":
                return msg.get("value")
            # 其它消息(理论上不会有)忽略,继续等 reply。


def _build_namespace(
    broker: _BrokerStub,
    allow_workflow: bool = True,
    read_only: bool = False,
) -> dict[str, Any]:
    """子进程内构造工具命名空间。纯沙箱工具直接用 tools.files 的原函数;
    broker-gated 工具用调 broker 的薄包装。
    allow_workflow=False 时去掉 propose_workflow(子 agent 深度护栏)。
    read_only=True 时剔除写工具(tool_scope=read 真正强制只读)。"""
    from argos_agent.tools import build_child_namespace
    return build_child_namespace(broker, allow_workflow=allow_workflow, read_only=read_only)


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
            allow_workflow = msg.get("allow_workflow", True)
            read_only = msg.get("read_only", False)
            executor = LocalPythonExecutor(additional_authorized_imports=imports)
            executor.send_tools(_build_namespace(broker, allow_workflow, read_only))
            _emit({"type": "init_ok"})
        elif op == "exec":
            if executor is None:
                _emit({"type": "exec_result", "stdout": "", "value_repr": "",
                       "exc": "RuntimeError: executor not initialized"})
                continue
            code = msg.get("code", "")
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
