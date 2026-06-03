"""`argos` 命令入口。

MVP 接线阶段(Phase 5):默认起 ArgosApp。Phase 3 真 AgentLoop 落地后,在此组装
store/bus/sandbox/broker/model/verifier 并经 loop_factory 注入真 loop;现在默认 FakeLoop
让 TUI 可独立运行/演示("一份事件三用"的 UI 出口已就位)。
"""
from __future__ import annotations

import sys

from argos_agent.tui.app import ArgosApp
from argos_agent.tui.fakeloop import FailingFakeLoop


def main() -> None:
    argv = sys.argv[1:]
    if "--demo-fail" in argv:
        ArgosApp(loop_factory=lambda: FailingFakeLoop()).run()
    else:
        # 默认 FakeLoop(在 ArgosApp 内部默认);Phase 3 注入真 loop_factory。
        ArgosApp().run()


if __name__ == "__main__":
    main()
