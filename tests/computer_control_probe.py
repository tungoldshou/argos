"""第 7 步降级路径探针 —— 真 venv 多步任务,运行时手动跑(不连 CI)。

跑法:`.venv/bin/python -m pytest tests/computer_control_probe.py -v -s --no-header`。
报告每个多步任务 ok/fail;3 任务中 2 个 click/type 任务都成功 → 不降级;
任一 click/type 任务失败 → 改 `playwright_tools.ENABLED_WRITE_TOOLS = False` + 删
`all_tools()` 里的 _click_gated / _type_text_gated,只留 navigate+snapshot。
"""
import asyncio
import pytest

# CI 跳过 —— 运行时手动跑
pytestmark = pytest.mark.skip(reason="第 7 步降级路径探针,运行时手动跑")


def test_navigate_then_snapshot():
    """任务 1:只读 —— navigate example.com + snapshot,必绿。"""
    from argos import playwright_tools
    playwright_tools._reset_for_test()

    async def run():
        r1 = await playwright_tools.navigate.ainvoke({"url": "https://example.com"})
        r2 = await playwright_tools.snapshot.ainvoke({})
        print(f"\n  navigate: {r1}")
        print(f"  snapshot: {r2}")
        assert r1["loaded"]
        assert r2["title"] == "Example Domain"
        return True
    assert asyncio.run(run())


def test_navigate_click_snapshot():
    """任务 2:写 —— navigate example.com + click 链接 + snapshot,验 click 稳定。"""
    from argos import playwright_tools
    playwright_tools._reset_for_test()

    async def run():
        await playwright_tools.navigate.ainvoke({"url": "https://example.com"})
        # example.com 有个 "More information..." 链接
        r = await playwright_tools.click.ainvoke({"selector": "a"})
        print(f"\n  click: {r}")
        snap = await playwright_tools.snapshot.ainvoke({})
        print(f"  snapshot after click: {snap}")
        assert snap["url"] != "https://example.com/"  # 真切到别处
        return True
    assert asyncio.run(run())


def test_navigate_type_snapshot():
    """任务 3:写 —— navigate 搜索页 + type_text 搜索框 + snapshot,验 type_text 稳定。"""
    from argos import playwright_tools
    playwright_tools._reset_for_test()

    async def run():
        # 用一个简单的 input 页面;example.com 没有 input,用 about:blank demo
        await playwright_tools.navigate.ainvoke({"url": "https://www.google.com"})
        try:
            r = await playwright_tools.type_text.ainvoke({"selector": "input[name=q]", "text": "Argos agent"})
            print(f"\n  type_text: {r}")
        except Exception as e:
            # google 可能有反爬,试 duckduckgo
            print(f"\n  google blocked ({e}), trying duckduckgo")
            await playwright_tools.navigate.ainvoke({"url": "https://duckduckgo.com"})
            r = await playwright_tools.type_text.ainvoke({"selector": "input[name=q]", "text": "Argos agent"})
        snap = await playwright_tools.snapshot.ainvoke({})
        print(f"  snapshot after type: {snap}")
        return True
    assert asyncio.run(run())
