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


# smolagents 的 LocalPythonExecutor 按模块真实 __name__ 做 authorized_imports 白名单检查。
# os.path 在 darwin/Linux 上其实是 posixpath 模块 —— 访问 os.path.* 会触发对 "posixpath" 的
# import 授权,白名单只有 "os" 不够(实测 "os.*" / "os.path" 都不命中,只有真模块名 "posixpath"
# 命中),缺它 agent 一调 os.path.expanduser 就 InterpreterError: Forbidden access to module:
# posixpath。这些是纯路径计算、零副作用 —— 真正的写/网络边界由 OS 沙箱(Seatbelt/bwrap)+ broker
# 兜底,放行它们不扩攻击面。genericpath 是 posixpath 的底层依赖,一并放行防边缘函数误伤。
# 无副作用的纯计算/数据/编码 stdlib —— agent 高频需要(算 hash、编码、dataclass、deepcopy…),
# 放行它们到 smolagents AST 层不削弱真边界:网络/进程/动态执行仍被排除(见下),真正的写/网络
# 边界由 OS 沙箱(Seatbelt/bwrap)+ broker 兜底。
# 刻意排除(保持拦截,副作用/越权风险):socket ssl urllib.request http subprocess multiprocessing
#   threading asyncio ctypes pickle marshal shelve importlib shutil sqlite3 —— 这些要走 broker 工具,
#   不在沙箱里裸跑(网络走 web_search/web_extract,进程走 run_command,文件写走 write_file)。
# urllib 只放行 urllib.parse(纯 URL 解析),不放行 urllib.request(网络)。
_DEFAULT_AUTHORIZED_IMPORTS = [
    # 序列化 / 文本 / 编码(纯)
    "json", "re", "string", "textwrap", "unicodedata", "difflib", "html",
    "csv", "io", "struct", "codecs", "base64", "binascii", "pprint",
    # 哈希 / 标识(纯计算,无副作用)
    "hashlib", "hmac", "secrets", "uuid",
    # 数学
    "math", "cmath", "decimal", "fractions", "statistics", "random", "numbers",
    # 数据结构 / 算法 / 函数式
    "collections", "collections.abc", "heapq", "bisect", "array", "queue",
    "enum", "dataclasses", "typing", "copy", "functools", "itertools",
    "operator", "contextlib",
    # 时间
    "datetime", "time", "calendar",
    # URL 解析(纯,不含 request)
    "urllib.parse",
    # 路径(纯)
    "pathlib",
]
_REQUIRED_AUTHORIZED_IMPORTS = ["os", "posixpath", "genericpath", "sys", "pathlib"]

# 预注入到 executor 命名空间的纯 stdlib —— agent 普遍裸用这些不写 import,缺预注入会 NameError。
# 全部经 authorized_imports 白名单审查;无副作用(纯数据/路径计算),真正的写/网络边界由 OS 沙箱
# + broker 兜底,放行不扩攻击面。os/sys/pathlib 也在内(agent 最常裸用)。
_PREINJECT_MODULES = ["os", "sys", "pathlib", "json", "re", "math",
                      "itertools", "collections", "datetime"]


def _resolve_authorized_imports(authorized: "list[str] | None") -> list[str]:
    """合并 host 传入(或默认)白名单与必备 stdlib 项,去重保序。

    membership 测试,顺序无关。posixpath/genericpath 是 os.path 的真实模块名 —— 没有它们
    agent 调 os.path.* 会被 smolagents AST 层拒(Forbidden access to module: posixpath)。
    """
    imports = list(authorized) if authorized else list(_DEFAULT_AUTHORIZED_IMPORTS)
    for need in _REQUIRED_AUTHORIZED_IMPORTS:
        if need not in imports:
            imports.append(need)
    return imports


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
            imports = _resolve_authorized_imports(msg.get("authorized_imports"))
            allow_workflow = msg.get("allow_workflow", True)
            read_only = msg.get("read_only", False)
            tool_allowlist = msg.get("tool_allowlist")   # None=无角色白名单(走 read_only 派生)
            executor = LocalPythonExecutor(additional_authorized_imports=imports)
            executor.send_tools(_build_namespace(broker, allow_workflow, read_only, tool_allowlist))
            # agent 普遍裸用 os/sys/pathlib/json/re/... 不写 import —— 预注入到 executor 命名空间
            # 防 NameError。已过 authorized_imports 白名单审查;真正的写/网络边界由 OS 沙箱 + broker
            # 兜底,放行这些纯 stdlib 不扩攻击面。
            import importlib
            for _name in _PREINJECT_MODULES:
                executor.state[_name] = importlib.import_module(_name)
            _emit({"type": "init_ok"})
        elif op == "exec":
            if executor is None:
                _emit({"type": "exec_result", "stdout": "", "value_repr": "",
                       "exc": "RuntimeError: executor not initialized"})
                continue
            code = msg.get("code", "")
            # 裸 os/sys/pathlib 由 init 的 state 预注入提供;os.path.* 由白名单含 posixpath/
            # genericpath 放行(见 _resolve_authorized_imports)。无需再 prepend import。
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
