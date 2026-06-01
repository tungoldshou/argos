"""Argos agent 服务的打包入口 —— PyInstaller 把这个打成单文件可执行,Tauri 当 sidecar 拉起。

端口可由环境变量 ARGOS_AGENT_PORT 覆盖(Tauri 注入),默认 8848。
"""
import os

import uvicorn

from argos_agent.server import app

if __name__ == "__main__":
    port = int(os.environ.get("ARGOS_AGENT_PORT", "8848"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
