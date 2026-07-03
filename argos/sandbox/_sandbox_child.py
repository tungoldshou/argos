"""Internal documentation."""
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
    """Internal documentation."""

    def request(self, action: str, args: dict[str, Any]) -> Any:
        _emit({"type": "broker_call", "action": action, "args": args})
        while True:
            msg = _read()
            if msg is None:
                return t("core2.sandbox_child.broker_closed")
            if msg.get("type") == "broker_reply":
                return msg.get("value")


def _build_namespace(
    broker: _BrokerStub,
    allow_workflow: bool = True,
    read_only: bool = False,
    tool_allowlist: "list[str] | None" = None,
) -> dict[str, Any]:
    """Internal documentation."""
    from argos.tools import build_child_namespace
    return build_child_namespace(
        broker, allow_workflow=allow_workflow, read_only=read_only,
        tool_allowlist=tool_allowlist,
    )


_DEFAULT_AUTHORIZED_IMPORTS = [
    "json", "re", "string", "textwrap", "unicodedata", "difflib", "html",
    "csv", "io", "struct", "codecs", "base64", "binascii", "pprint",
    "hashlib", "hmac", "secrets", "uuid",
    "math", "cmath", "decimal", "fractions", "statistics", "random", "numbers",
    "collections", "collections.abc", "heapq", "bisect", "array", "queue",
    "enum", "dataclasses", "typing", "copy", "functools", "itertools",
    "operator", "contextlib",
    "datetime", "time", "calendar",
    "urllib.parse",
    "pathlib",
]
_REQUIRED_AUTHORIZED_IMPORTS = ["os", "posixpath", "genericpath", "sys", "pathlib"]

_PREINJECT_MODULES = ["os", "sys", "pathlib", "json", "re", "math",
                      "itertools", "collections", "datetime"]


def _resolve_authorized_imports(authorized: "list[str] | None") -> list[str]:
    """Internal documentation."""
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
            tool_allowlist = msg.get("tool_allowlist")
            executor = LocalPythonExecutor(additional_authorized_imports=imports)
            executor.send_tools(_build_namespace(broker, allow_workflow, read_only, tool_allowlist))
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
            except Exception:  # noqa: BLE001
                exc = traceback.format_exc(limit=8)
            _emit({"type": "exec_result", "stdout": stdout,
                   "value_repr": value_repr, "exc": exc})
        elif op == "close":
            break
        else:
            _emit({"type": "error", "message": f"unknown op {op!r}"})


if __name__ == "__main__":
    main()
