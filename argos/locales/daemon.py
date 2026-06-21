"""argosd CLI 用户可见文案 —— stop / status / restart 子命令输出。

key 命名空间:daemon.*。
ZH 值 = 原始中文串(逐字照搬,保证既有测试 assert 仍通过)。
EN 值 = 对应的自然英文翻译。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # serve / assembly warnings
    "daemon.serve.warn_no_key": (
        "[daemon] warning: cannot assemble AgentLoop ({e}); daemon started in no-key mode, create_run will reject."
    ),
    "daemon.serve.warn_assembly_error": (
        "[daemon] warning: assembly error ({e}); daemon started in no-key mode."
    ),
    # stop subcommand
    "daemon.stop.not_running": "daemon not running",
    "daemon.stop.stale_pid_cleaned": "daemon not running (stale pid file removed)",
    "daemon.stop.socket_no_pid": (
        "daemon socket exists at {socket_path} but no pid file; cannot stop gracefully."
    ),
    "daemon.stop.sigterm_sent": "[daemon] SIGTERM sent → pid={pid}",
    "daemon.stop.process_gone": "daemon not running (process no longer exists)",
    "daemon.stop.no_permission": "[daemon] no permission to send SIGTERM: {e}",
    "daemon.stop.stopped": "[daemon] stopped",
    "daemon.stop.timeout_warning": (
        "[daemon] warning: daemon did not exit within {timeout}s"
        " (socket still at {socket_path})"
    ),
    # status subcommand
    "daemon.status.not_running": "daemon not running",
    "daemon.status.stale_pid_note": "  (stale pid file: {pid_path}, pid={pid})",
    "daemon.status.running": "daemon running",
    "daemon.status.pid_line": "  pid       : {pid}",
    "daemon.status.pid_file_line": "  pid file  : {pid_path}",
    "daemon.status.socket_line": "  socket    : {socket_path} ({connectivity})",
    "daemon.status.socket_connectable": "connectable",
    "daemon.status.socket_not_connectable": "not connectable",
    "daemon.status.uptime_line": "  uptime    : {uptime}",
    "daemon.status.version_line": "  version   : {version_info}",
    # restart subcommand
    "daemon.restart.restarting": "[daemon] restarting…",
    "daemon.restart.restarted": "[daemon] restarted (running in background)",
}

ZH: dict[str, str] = {
    # serve / assembly warnings
    "daemon.serve.warn_no_key": (
        "[daemon] 警告:无法装配 AgentLoop({e});daemon 以无 key 模式启动,create_run 将拒绝。"
    ),
    "daemon.serve.warn_assembly_error": (
        "[daemon] 警告:装配异常({e});daemon 以无 key 模式启动。"
    ),
    # stop subcommand
    "daemon.stop.not_running": "daemon 未运行",
    "daemon.stop.stale_pid_cleaned": "daemon 未运行 (残留 pid 文件已清理)",
    "daemon.stop.socket_no_pid": (
        "daemon socket 存在于 {socket_path} 但无 pid 文件;无法优雅停止。"
    ),
    "daemon.stop.sigterm_sent": "[daemon] SIGTERM 已发送 → pid={pid}",
    "daemon.stop.process_gone": "daemon 未运行 (进程已不存在)",
    "daemon.stop.no_permission": "[daemon] 无权发送 SIGTERM: {e}",
    "daemon.stop.stopped": "[daemon] 已停止",
    "daemon.stop.timeout_warning": (
        "[daemon] 警告:daemon 在 {timeout}s 内未完全退出(socket 仍在 {socket_path})"
    ),
    # status subcommand
    "daemon.status.not_running": "daemon 未运行",
    "daemon.status.stale_pid_note": "  (残留 pid 文件: {pid_path}, pid={pid})",
    "daemon.status.running": "daemon 运行中",
    "daemon.status.pid_line": "  pid       : {pid}",
    "daemon.status.pid_file_line": "  pid 文件  : {pid_path}",
    "daemon.status.socket_line": "  socket    : {socket_path} ({connectivity})",
    "daemon.status.socket_connectable": "可连接",
    "daemon.status.socket_not_connectable": "不可连接",
    "daemon.status.uptime_line": "  uptime    : {uptime}",
    "daemon.status.version_line": "  version   : {version_info}",
    # restart subcommand
    "daemon.restart.restarting": "[daemon] 正在重新启动…",
    "daemon.restart.restarted": "[daemon] 已重新启动(后台运行)",
}
