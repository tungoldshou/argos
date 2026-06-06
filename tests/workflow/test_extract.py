from argos_agent.core.loop import extract_workflow_spec


def test_extract_dict_literal_arg():
    text = '''好的,我来编排。
```python
propose_workflow({
    "name": "audit", "description": "审计",
    "stages": [{"id": "r", "op": "fan_out", "over": ["a.py", "b.py"],
                "agent": {"prompt": "看 {item}"}}],
})
```'''
    raw = extract_workflow_spec(text)
    assert raw is not None
    assert raw["name"] == "audit"
    assert raw["stages"][0]["over"] == ["a.py", "b.py"]


def test_no_call_returns_none():
    assert extract_workflow_spec("没有调用工作流的普通文本") is None


def test_non_literal_arg_returns_none():
    assert extract_workflow_spec("propose_workflow(some_var)") is None
