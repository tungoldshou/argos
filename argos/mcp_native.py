from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from argos import config
from argos.i18n import t

CONFIG_PATH: Path | None = None
_INIT_TIMEOUT_S = 15.0
_CALL_TIMEOUT_S = 60.0


def resolve_config_path(path: Path | None = None) -> Path:
    return Path(
        path or CONFIG_PATH or (
            Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
            / "mcp.json"
        )
    )


@dataclass
class McpTool:
    server: str
    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict)


class _StdioServer:

    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        self.name = name
        self._cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self.tools: list[McpTool] = []
        self.error: str | None = None
        self._rx: "queue.Queue[str | None]" = queue.Queue()
        self._reader: threading.Thread | None = None

    def connect(self) -> bool:
        cmd = self._cfg.get("command")
        if not cmd:
            self.error = t("mcp.server.missing_command")
            return False
        argv = [cmd, *(self._cfg.get("args") or [])]
        env = {**os.environ, **(self._cfg.get("env") or {})}
        try:
            self._proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env,
            )
        except Exception as e:  # noqa: BLE001
            self.error = t("mcp.server.start_failed", exc_type=type(e).__name__, exc=e)
            return False
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()
        try:
            init = self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "argos", "version": "0.1.0"},
            }, timeout=_INIT_TIMEOUT_S)
            if "error" in init:
                self.error = t("mcp.server.initialize_failed", error=init["error"])
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
            self.error = t("mcp.server.handshake_error", exc_type=type(e).__name__, exc=e)
            return False

    def call(self, tool: str, arguments: dict[str, Any]) -> str:
        if self._proc is None or self._proc.poll() is not None:
            return t("mcp.server.not_connected", name=self.name)
        try:
            resp = self._rpc("tools/call", {"name": tool, "arguments": arguments},
                             timeout=_CALL_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            return t("mcp.server.call_error", name=self.name, tool=tool, exc_type=type(e).__name__, exc=e)
        if "error" in resp:
            return t("mcp.server.call_rpc_error", name=self.name, tool=tool, error=resp["error"])
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

    def _reader_loop(self) -> None:
        stdout = self._proc.stdout if self._proc is not None else None
        if stdout is None:
            self._rx.put(None)
            return
        try:
            for line in stdout:
                self._rx.put(line)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._rx.put(None)

    def _rpc(self, method: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        with self._lock:
            self._id += 1
            rid = self._id
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            deadline = time.time() + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(t("mcp.server.rpc_timeout", method=method, timeout=timeout))
                try:
                    line = self._rx.get(timeout=remaining)
                except queue.Empty:
                    raise TimeoutError(t("mcp.server.rpc_timeout", method=method, timeout=timeout))
                if line is None:
                    raise RuntimeError(t("mcp.server.stdout_closed"))
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == rid:
                    return msg

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _send(self, obj: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(obj) + "\n")
        self._proc.stdin.flush()


def _flatten_content(result: dict[str, Any]) -> str:
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
            parts.append(t("mcp.content.non_text", content_type=c.get("type", "unknown")))
    out = "\n".join(p for p in parts if p)
    if result.get("isError"):
        return t("mcp.content.tool_error", out=out)
    return out or t("mcp.content.empty_result")


class McpManager:

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = resolve_config_path(config_path)
        self._servers: dict[str, _StdioServer] = {}
        self._loaded = False
        self._lock = threading.Lock()

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            cfg = self._read_config()
            for name, scfg in (cfg.get("servers") or {}).items():
                if not isinstance(scfg, dict) or not (scfg.get("enabled", True)):
                    continue
                srv = _StdioServer(name, scfg)
                srv.connect()
                self._servers[name] = srv

    def start_warming(self) -> None:
        if self._loaded:
            return
        threading.Thread(target=self.ensure_loaded, name="argos-mcp-warm", daemon=True).start()

    def _read_config(self) -> dict[str, Any]:
        try:
            if not self._config_path.exists():
                return {}
            return json.loads(self._config_path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            return {}

    def _collect_tools(self) -> list[McpTool]:
        out: list[McpTool] = []
        for srv in self._servers.values():
            out.extend(srv.tools)
        return out

    def list_tools(self) -> list[McpTool]:
        self.ensure_loaded()
        return self._collect_tools()

    def tools_summary(self) -> str:
        tools = self._collect_tools()
        if not tools:
            return ""
        lines = ["<mcp_tools> Available MCP tools (call via mcp_call(server, tool, arguments)):"]
        for t in tools:
            desc = (t.description or "").strip().replace("\n", " ")
            if len(desc) > 100:
                desc = desc[:100] + "…"
            lines.append(f"- {t.server}/{t.name}: {desc}")
        lines.append("</mcp_tools>")
        return "\n".join(lines)

    def call(self, server: str, tool: str, arguments: dict[str, Any] | None = None) -> str:
        self.ensure_loaded()
        srv = self._servers.get(server)
        if srv is None:
            if not self._servers:
                return t("mcp.manager.no_servers", path=self._config_path)
            return t("mcp.manager.unknown_server", server=server, available=", ".join(self._servers))
        if srv.error and not srv.tools:
            return t("mcp.manager.server_unavailable", server=server, error=srv.error)
        return srv.call(tool, arguments or {})

    def close(self) -> None:
        with self._lock:
            for srv in self._servers.values():
                srv.close()
            self._servers.clear()
            self._loaded = False


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
