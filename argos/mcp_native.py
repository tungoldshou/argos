"""原生 MCP 客户端(stdio,newline-delimited JSON-RPC)—— 不依赖 langchain。

为什么自己写:旧 `mcp_client.py`(已随死栈删)绑死 langchain-mcp-adapters,而活引擎 framework-free。
MCP 的 stdio 传输就是**按行分隔的 JSON-RPC**(不是 LSP 的 Content-Length 框),同步实现很轻。

架构契合:broker `_execute` 是同步 host 侧执行;MCP 的 request/response 也同步(写一行、读一行),
故 `mcp_call` 作为一个 broker action 直接落地,无 async-from-sync 难题。

诚实(灵魂):
  · **默认零预配** —— 没有 `~/.argos/mcp.json` / 没有 servers → `list_tools()` 返空、
    系统提示不注入任何 MCP 段、`mcp_call` 诚实报"未配置 MCP"。绝不预装第三方 server。
  · 单个 server 连接/握手失败 → 标记不可用、其余照常,绝不崩 run。
  · 每次调用包真错误返回可读串(模型据此换路),不假装调用成功。
配置(`~/.argos/mcp.json`):{"servers": {"<name>": {"command": "...", "args": [...], "env": {...}}}}
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".argos" / "mcp.json"
_INIT_TIMEOUT_S = 15.0
_CALL_TIMEOUT_S = 60.0


@dataclass
class McpTool:
    server: str
    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict)


class _StdioServer:
    """一个 stdio MCP server 的持久连接 + 同步 JSON-RPC。线程安全(一把锁串行化请求/响应)。"""

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        self.name = name
        self._cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self.tools: list[McpTool] = []
        self.error: str | None = None

    # ── 连接 + 握手(initialize → initialized → tools/list)──────────────────────
    def connect(self) -> bool:
        cmd = self._cfg.get("command")
        if not cmd:
            self.error = "缺少 command"
            return False
        argv = [cmd, *(self._cfg.get("args") or [])]
        env = {**os.environ, **(self._cfg.get("env") or {})}
        try:
            self._proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env,
            )
        except Exception as e:  # noqa: BLE001
            self.error = f"启动失败:{type(e).__name__}: {e}"
            return False
        try:
            init = self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "argos", "version": "0.1.0"},
            }, timeout=_INIT_TIMEOUT_S)
            if "error" in init:
                self.error = f"initialize 失败:{init['error']}"
                return False
            self._notify("notifications/initialized", {})
            listed = self._rpc("tools/list", {}, timeout=_INIT_TIMEOUT_S)
            tools = (listed.get("result") or {}).get("tools") or []
            self.tools = [
                McpTool(server=self.name, name=t.get("name", ""),
                        description=t.get("description", ""),
                        schema=t.get("inputSchema") or {})
                for t in tools if t.get("name")
            ]
            return True
        except Exception as e:  # noqa: BLE001
            self.error = f"握手异常:{type(e).__name__}: {e}"
            return False

    def call(self, tool: str, arguments: dict[str, Any]) -> str:
        if self._proc is None or self._proc.poll() is not None:
            return f"错误:MCP server {self.name!r} 未连接或已退出。"
        try:
            resp = self._rpc("tools/call", {"name": tool, "arguments": arguments},
                             timeout=_CALL_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            return f"错误:MCP 调用 {self.name}/{tool} 异常:{type(e).__name__}: {e}"
        if "error" in resp:
            return f"错误:MCP {self.name}/{tool} 返回错误:{resp['error']}"
        result = resp.get("result") or {}
        return _flatten_content(result)

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3.0)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None

    # ── 同步 JSON-RPC 帧(newline-delimited)──────────────────────────────────────
    def _rpc(self, method: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        with self._lock:
            self._id += 1
            rid = self._id
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            # 读到匹配 id 的响应(跳过通知/不相关行)。简化:阻塞读行,直到拿到本 id。
            assert self._proc is not None and self._proc.stdout is not None
            import time
            deadline = time.time() + timeout
            while time.time() < deadline:
                line = self._proc.stdout.readline()
                if not line:
                    raise RuntimeError("server stdout 关闭(进程可能已退出)")
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 非 JSON 行(server 噪声)跳过
                if msg.get("id") == rid:
                    return msg
            raise TimeoutError(f"{method} 超时({timeout}s)")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _send(self, obj: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(obj) + "\n")
        self._proc.stdin.flush()


def _flatten_content(result: dict[str, Any]) -> str:
    """MCP tools/call 结果的 content 数组 → 可读文本(取 text 片段;其余类型标注类型)。"""
    content = result.get("content")
    if not isinstance(content, list):
        return json.dumps(result, ensure_ascii=False)
    parts: list[str] = []
    for c in content:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "text":
            parts.append(str(c.get("text", "")))
        else:
            parts.append(f"[{c.get('type', 'unknown')} 内容]")
    out = "\n".join(p for p in parts if p)
    if result.get("isError"):
        return f"[MCP 工具报错] {out}"
    return out or "(MCP 工具返回空)"


class McpManager:
    """进程内 MCP 连接管理器(单例)。懒加载 ~/.argos/mcp.json;连接失败优雅降级。"""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or CONFIG_PATH
        self._servers: dict[str, _StdioServer] = {}
        self._loaded = False
        self._lock = threading.Lock()

    def ensure_loaded(self) -> None:
        """同步连接所有 server(整段在锁内 → 后到的 call()/ensure_loaded 阻塞等连接完成,
        见到 _loaded=True 时 self._servers 已就绪,无半连接竞态)。"""
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            cfg = self._read_config()
            for name, scfg in (cfg.get("servers") or {}).items():
                if not isinstance(scfg, dict) or not (scfg.get("enabled", True)):
                    continue
                srv = _StdioServer(name, scfg)
                srv.connect()   # 失败时 srv.error 记原因、tools 为空(降级,不抛)
                self._servers[name] = srv

    def start_warming(self) -> None:
        """后台线程预热连接 —— 不在 agent 主循环(事件循环线程)上阻塞着连 npx server。
        默认零预配时 ensure_loaded 秒回(无 server),此调用基本免费。"""
        if self._loaded:
            return
        threading.Thread(target=self.ensure_loaded, name="argos-mcp-warm", daemon=True).start()

    def _read_config(self) -> dict[str, Any]:
        try:
            if not self._config_path.exists():
                return {}
            return json.loads(self._config_path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — 畸形 config 诚实退空(等于零 MCP),不崩
            return {}

    def _collect_tools(self) -> list[McpTool]:
        """读当前【已连接】server 的工具(不触发连接,非阻塞)。"""
        out: list[McpTool] = []
        for srv in self._servers.values():
            out.extend(srv.tools)
        return out

    def list_tools(self) -> list[McpTool]:
        """阻塞:确保连接完成后返回全部工具(直接调用 / 测试用)。"""
        self.ensure_loaded()
        return self._collect_tools()

    def tools_summary(self) -> str:
        """给系统提示用的可用 MCP 工具清单 ——【非阻塞】:只读当前已连接的工具,
        预热没完成就先返回已就绪的(或空),绝不在 agent 主循环上阻塞等 npx 起 server。
        无则空串 → 调用方不注入 MCP 段。"""
        tools = self._collect_tools()
        if not tools:
            return ""
        lines = ["【可用 MCP 工具(经 mcp_call(server, tool, arguments) 调用)】"]
        for t in tools:
            desc = (t.description or "").strip().replace("\n", " ")
            if len(desc) > 100:
                desc = desc[:100] + "…"
            lines.append(f"- {t.server}/{t.name}:{desc}")
        return "\n".join(lines)

    def call(self, server: str, tool: str, arguments: dict[str, Any] | None = None) -> str:
        self.ensure_loaded()
        srv = self._servers.get(server)
        if srv is None:
            if not self._servers:
                return "错误:未配置任何 MCP server(~/.argos/mcp.json 不存在或为空)。"
            return f"错误:未知 MCP server {server!r}(可用:{', '.join(self._servers)})。"
        if srv.error and not srv.tools:
            return f"错误:MCP server {server!r} 不可用({srv.error})。"
        return srv.call(tool, arguments or {})

    def close(self) -> None:
        with self._lock:
            for srv in self._servers.values():
                srv.close()
            self._servers.clear()
            self._loaded = False


# ── 进程内单例 ────────────────────────────────────────────────────────────────
_MANAGER: McpManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager() -> McpManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = McpManager()
        return _MANAGER


def shutdown() -> None:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is not None:
            _MANAGER.close()
            _MANAGER = None


import atexit as _atexit

_atexit.register(shutdown)
