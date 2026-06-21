"""i18n 漏网中文扫描器(临时工具,提交前删)。

用法: python3 scripts/_i18n_leak_scan.py <file.py> [file.py ...]

报告每个文件里【含中文的字符串字面量】中,既不是 docstring、也不是 t()/_t()/_i18n_t() 的实参、
也不是 log.*() 调用实参的那些 —— 即"可能漏掉本地化的用户可见串"。语义假阳性(匹配模型输出的
中文词表 / CSS 串 / 纯内部断言)需人工判断跳过。
"""
from __future__ import annotations

import ast
import re
import sys

CJK = re.compile(r"[一-鿿]")
LOC_FUNCS = {"t", "_t", "_i18n_t"}
LOG_ATTRS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}


def _docstrings(tree: ast.AST) -> set[int]:
    ds: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ds.add(id(body[0].value))
    return ds


def _localized_or_log(tree: ast.AST) -> set[int]:
    ok: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else None
            attr = fn.attr if isinstance(fn, ast.Attribute) else None
            if name in LOC_FUNCS or attr in LOG_ATTRS:
                for a in list(node.args) + [k.value for k in node.keywords]:
                    for s in ast.walk(a):
                        if isinstance(s, ast.Constant) and isinstance(s.value, str):
                            ok.add(id(s))
    return ok


def scan(path: str) -> list[tuple[int, str]]:
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    skip = _docstrings(tree) | _localized_or_log(tree)
    leaks: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and CJK.search(node.value) and id(node) not in skip):
            leaks.append((node.lineno, node.value[:70].replace("\n", "\\n")))
    return sorted(leaks)


def main() -> int:
    total = 0
    for path in sys.argv[1:]:
        try:
            leaks = scan(path)
        except FileNotFoundError:
            continue
        if leaks:
            print(f"\n### {path}  ({len(leaks)} leaks)")
            for ln, tx in leaks:
                print(f"  {ln}: {tx}")
            total += len(leaks)
    print(f"\n=== TOTAL leaks: {total} ===")
    return total


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
