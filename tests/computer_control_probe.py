import asyncio
import pytest

pytestmark = pytest.mark.skip(reason="第 7 步降级路径探针,运行时手动跑")


def test_navigate_then_snapshot():
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
    from argos import playwright_tools
    playwright_tools._reset_for_test()

    async def run():
        await playwright_tools.navigate.ainvoke({"url": "https://example.com"})
        r = await playwright_tools.click.ainvoke({"selector": "a"})
        print(f"\n  click: {r}")
        snap = await playwright_tools.snapshot.ainvoke({})
        print(f"  snapshot after click: {snap}")
        assert snap["url"] != "https://example.com/"
        return True
    assert asyncio.run(run())


def test_navigate_type_snapshot():
    from argos import playwright_tools
    playwright_tools._reset_for_test()

    async def run():
        await playwright_tools.navigate.ainvoke({"url": "https://www.google.com"})
        try:
            r = await playwright_tools.type_text.ainvoke({"selector": "input[name=q]", "text": "Argos agent"})
            print(f"\n  type_text: {r}")
        except Exception as e:
            print(f"\n  google blocked ({e}), trying duckduckgo")
            await playwright_tools.navigate.ainvoke({"url": "https://duckduckgo.com"})
            r = await playwright_tools.type_text.ainvoke({"selector": "input[name=q]", "text": "Argos agent"})
        snap = await playwright_tools.snapshot.ainvoke({})
        print(f"  snapshot after type: {snap}")
        return True
    assert asyncio.run(run())
