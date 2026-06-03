"""`argos` 命令入口。"""
from __future__ import annotations

from argos_agent.tui.app import ArgosApp


def main() -> None:
    ArgosApp().run()


if __name__ == "__main__":
    main()
