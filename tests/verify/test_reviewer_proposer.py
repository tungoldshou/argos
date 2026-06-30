"""tests/verify/test_reviewer_proposer.py

Tests for the reviewer-role LLM proposer (maker/checker separation, Task 5b.3).

Key properties verified:
  1. For an unverifiable run (no verify_cmd) with ARGOS_SELF_TEST on, the reviewer
     proposer is invoked and proposes a candidate test.
  2. A trivial proposed test is rejected by the canary guard (stays unverifiable,
     NOT promoted to passed).
  3. The reviewer proposer is a distinct call from the maker (uses a separate fake
     reviewer model that records it was called, independent of the coder model).
  4. reviewer_llm_proposer parses a well-formed model response into (cmd, content, path).
  5. reviewer_llm_proposer returns None on a malformed/empty model response.
"""
from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from argos import runtime
from argos.core.types import Verdict
from argos.core.verify_gate import Verifier
from argos.verify.self_test import (
    TestGenerator,
    _parse_reviewer_response,
    reviewer_llm_proposer,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def in_tmp_workspace(tmp_path, monkeypatch):
    """Switch runtime context to tmp_path so verify_gate uses it."""
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")
    token = runtime.use_project(str(tmp_path))
    yield tmp_path
    runtime.reset(token)


class _FakeModelClient:
    """Fake ModelClient that records calls and returns a scripted response."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.call_count = 0
        # Separate from any "maker" model — tracks reviewer-role calls only.
        self.reviewer_system_prompts: list[str] = []

    async def complete(self, messages: list[dict], *, system: str,
                       system_dynamic: str | None = None) -> str:
        self.call_count += 1
        self.reviewer_system_prompts.append(system)
        return self._response


# ── 1. Reviewer proposer is invoked for unverifiable runs ─────────────────────


def test_reviewer_proposer_is_called_for_unverifiable_run(
    in_tmp_workspace, monkeypatch
):
    """When ARGOS_SELF_TEST=1 and no verify_cmd, the reviewer model is called."""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    ws = in_tmp_workspace

    # workspace has a sentinel file the test will assert on
    (ws / "sentinel.py").write_text("VALUE = 99\n")

    test_content = textwrap.dedent("""\
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("sentinel", Path("sentinel.py").resolve())
        m = importlib.util.module_from_spec(spec)  # type: ignore
        spec.loader.exec_module(m)  # type: ignore
        assert m.VALUE == 99
    """)
    # Build the structured response the reviewer model would emit
    fake_response = (
        "CMD: python3 _reviewer_test.py\n"
        "TESTFILE: _reviewer_test.py\n"
        "CONTENT:\n"
        "```python\n"
        f"{test_content}"
        "```\n"
    )

    fake_model = _FakeModelClient(fake_response)
    proposer = reviewer_llm_proposer(fake_model)  # type: ignore[arg-type]
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="check sentinel.VALUE == 99")

    verdict = v.verify(verify_cmd=None, attempts=1)

    # Reviewer was called at least once (proposer invoked the model)
    assert fake_model.call_count >= 1, "reviewer model was never called"
    # The run should have produced a self-verified pass (sentinel exists)
    assert verdict.status == "passed", f"expected passed, got {verdict!r}"
    assert verdict.self_verified is True


# ── 2. Trivial proposed test is rejected by canary, stays unverifiable ────────


def test_trivial_reviewer_test_rejected_by_canary(
    in_tmp_workspace, monkeypatch
):
    """A reviewer-proposed test that passes on an empty workspace is rejected
    by the canary guard — result stays unverifiable, never fake-passed."""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")

    # The reviewer model proposes a trivially-passing command (echo).
    # On an empty workspace it still exits 0 → canary rejects it.
    fake_response = (
        "CMD: echo trivial\n"
        "TESTFILE: _reviewer_test.py\n"
        "CONTENT:\n"
        "```python\n"
        "# always passes — should be rejected by canary\n"
        "```\n"
    )
    fake_model = _FakeModelClient(fake_response)
    proposer = reviewer_llm_proposer(fake_model)  # type: ignore[arg-type]
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="trivial task")

    verdict = v.verify(verify_cmd=None, attempts=1)

    # Reviewer was called (proposer ran)
    assert fake_model.call_count >= 1, "reviewer model was never called"
    # But canary rejected it → unverifiable, NOT passed
    assert verdict.status == "unverifiable", (
        f"trivial test should be rejected by canary, got {verdict!r}"
    )
    assert verdict.self_verified is False


# ── 3. Reviewer is a distinct call from the maker ─────────────────────────────


def test_reviewer_is_distinct_from_maker(in_tmp_workspace, monkeypatch):
    """The reviewer proposer must use a SEPARATE model role.

    We verify this by:
    a) The reviewer model client records it was called (not the coder's client).
    b) The system prompt passed to the reviewer explicitly identifies it as the
       INDEPENDENT REVIEWER role (not a coder prompt).
    """
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")

    # Reviewer response that proposes a valid non-trivial test.
    ws = in_tmp_workspace
    (ws / "output.txt").write_text("hello\n")

    test_content = textwrap.dedent("""\
        from pathlib import Path
        assert Path("output.txt").exists(), "output.txt missing"
        content = Path("output.txt").read_text()
        assert content.strip() == "hello", f"unexpected: {content!r}"
    """)
    fake_response = (
        "CMD: python3 _reviewer_test.py\n"
        "TESTFILE: _reviewer_test.py\n"
        "CONTENT:\n"
        "```python\n"
        f"{test_content}"
        "```\n"
    )
    reviewer_model = _FakeModelClient(fake_response)

    # Build proposer with the reviewer model (distinct from any coder model)
    proposer = reviewer_llm_proposer(reviewer_model)  # type: ignore[arg-type]
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="create output.txt with 'hello'")
    v.verify(verify_cmd=None, attempts=1)

    # The reviewer model was called (not the coder model — the coder model is not
    # injected here at all, proving separation)
    assert reviewer_model.call_count >= 1
    # The system prompt sent to the reviewer must identify the REVIEWER role
    assert any("REVIEWER" in sp or "reviewer" in sp.lower()
               for sp in reviewer_model.reviewer_system_prompts), (
        "reviewer system prompt should identify the independent reviewer role"
    )
    # The system prompt must instruct the reviewer to be independent of the coder
    combined = " ".join(reviewer_model.reviewer_system_prompts)
    assert "NOT the coder" in combined or "INDEPENDENT" in combined, (
        "reviewer system prompt must instruct reviewer to be independent of coder"
    )


# ── 4. Parse well-formed reviewer response ────────────────────────────────────


def test_parse_reviewer_response_well_formed():
    """_parse_reviewer_response correctly extracts (cmd, content, test_path)
    from a well-structured model response."""
    response = (
        "CMD: python3 _reviewer_test.py\n"
        "TESTFILE: _reviewer_test.py\n"
        "CONTENT:\n"
        "```python\n"
        "assert 1 == 1\n"
        "```\n"
    )
    result = _parse_reviewer_response(response)
    assert result is not None
    cmd, content, test_path = result
    assert cmd == "python3 _reviewer_test.py"
    assert "assert 1 == 1" in content
    assert test_path == "_reviewer_test.py"


def test_parse_reviewer_response_missing_cmd():
    """Missing CMD line → None (stays unverifiable)."""
    response = (
        "TESTFILE: t.py\n"
        "CONTENT:\n"
        "```python\nassert True\n```\n"
    )
    assert _parse_reviewer_response(response) is None


def test_parse_reviewer_response_missing_code_block():
    """Missing ```python block → None (stays unverifiable)."""
    response = "CMD: python3 t.py\nTESTFILE: t.py\nCONTENT:\nsome plain text"
    assert _parse_reviewer_response(response) is None


# ── 5. Reviewer model error → stays unverifiable ─────────────────────────────


def test_reviewer_model_error_stays_unverifiable(in_tmp_workspace, monkeypatch):
    """If the reviewer model raises an exception, the result is unverifiable
    (never fake-passed)."""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")

    class _ErrorModel:
        async def complete(self, *args, **kwargs) -> str:
            raise RuntimeError("network error")

    proposer = reviewer_llm_proposer(_ErrorModel())  # type: ignore[arg-type]
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="some goal")
    verdict = v.verify(verify_cmd=None, attempts=1)

    assert verdict.status == "unverifiable"
    assert verdict.self_verified is False


# ── 6. Flag off → reviewer model never called ────────────────────────────────


def test_reviewer_not_called_when_flag_off(in_tmp_workspace, monkeypatch):
    """When ARGOS_SELF_TEST is not set, the reviewer model is never called."""
    monkeypatch.delenv("ARGOS_SELF_TEST", raising=False)

    fake_model = _FakeModelClient("CMD: echo x\nTESTFILE: t.py\nCONTENT:\n```python\n```\n")
    proposer = reviewer_llm_proposer(fake_model)  # type: ignore[arg-type]
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="x")
    v.verify(verify_cmd=None, attempts=1)

    assert fake_model.call_count == 0, "reviewer must not be called when ARGOS_SELF_TEST is off"
