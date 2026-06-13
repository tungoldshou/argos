"""self-test 旁路验收(任务:无 verify_cmd 时,用 reviewer + canary 守卫自动造测试)。

铁律(模块顶部 hard rule,绝不松):
  · 自验证结果**绝不**与用户级 passed 混为一谈 —— Verdict.self_verified 字段单独标。
  · 自造测试必须能失败(canary:在空 workspace 跑必非 0)—— 废测试丢弃回退 unverifiable。
  · 写代码 agent 不得为自己造测试(架构保证:Verifier.verify 在 writer 后被调,generator 独立)。
  · 默认关闭(opt-in via ARGOS_SELF_TEST=1 env var);不开时 verifier 行为 100% 与
    之前一致(unverifiable fallback)。

覆盖:
  (a) verify_cmd=None + flag on + proposer 返白名单 + canary 过 → 用自造测试,真跑过 → passed_self
  (b) canary 失败(测试在空 ws 也 exit 0,废测试)→ 丢弃,回退 unverifiable
  (c) 自验证结果带 self_verified=True 单独标记;UI/report/统计可按它区分
  (d) flag off(默认)→ unverifiable,generator 完全不被调
  (e) proposer 返的 cmd 不在白名单 → 丢弃,回退 unverifiable(白名单复检)
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from argos import runtime
from argos.core.types import Verdict
from argos.core.verify_gate import Verifier
from argos.verify.self_test import TestGenerator, TestProposal, _is_whitelisted


# ── 帮手 fixtures ─────────────────────────────────────────


@pytest.fixture
def in_tmp_workspace(tmp_path, monkeypatch):
    """把 runtime context 切到 tmp_path,verify_gate 的 _run_verify 会用这个 ws。"""
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")
    token = runtime.use_project(str(tmp_path))
    yield tmp_path
    runtime.reset(token)


def _make_proposer_with(cmd: str, content: str, test_path: str = "test_argos_selftest.py"):
    """返一个 TestProposer:总返给定的 (cmd, content, test_path)。"""
    def _prop(goal: str, workspace: Path):
        return (cmd, content, test_path)
    return _prop


# ── (a) flag on + canary 过 + 真跑过 → passed_self ─────────


def test_self_test_passes_when_canary_and_real_both_pass(
    in_tmp_workspace, monkeypatch,
):
    """proposer 返一个白名单 pytest 测;canary 在空 ws 上必非 0(测依赖 ws 内文件);
    真 ws 上有 sentinel.py → 测试通过 → Verdict.passed_self。"""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    ws = in_tmp_workspace
    # workspace 里放 sentinel.py(proposer 提示测试会查它)
    (ws / "sentinel.py").write_text("ANSWER = 42\n")

    # 测试内容:断言 sentinel.py 的 ANSWER == 42(在空 ws 上必失败,因为没有 sentinel.py)
    test_content = textwrap.dedent("""
        import sys, importlib.util
        from pathlib import Path
        # 真依赖 ws 内的 sentinel.py;空 ws 上 import 会失败
        spec = importlib.util.spec_from_file_location("sentinel", Path("sentinel.py").resolve())
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        spec.loader.exec_module(mod)  # type: ignore
        assert mod.ANSWER == 42
    """).strip()
    proposer = _make_proposer_with("python3 test_argos_selftest.py", test_content)
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="check sentinel.ANSWER == 42")
    verdict = v.verify(verify_cmd=None, attempts=1)

    # 关键:真过了 + 标 self_verified
    assert verdict.status == "passed", verdict
    assert verdict.self_verified is True, f"自验证应标 self_verified=True,实得 {verdict!r}"
    assert "[self_verified]" in verdict.detail
    # verify_cmd 应被记录(给后续 audit)
    assert verdict.verify_cmd is not None
    assert "test_argos_selftest.py" in verdict.verify_cmd


# ── (b) canary 失败 → 废测试 → 丢弃回退 unverifiable ─────


def test_self_test_discards_noop_test_via_canary(
    in_tmp_workspace, monkeypatch,
):
    """proposer 返一个"在空 ws 也过"的废测试(eg `true` 包装,或 grep 不存在文件返非零也算)
    —— canary 检测到空 ws 仍 exit 0 → 丢弃,回退 unverifiable(绝不假装通过)。"""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    # 测试内容无关紧要(canary 阶段就拒了);用一个真 trivial command
    test_content = "# will be discarded by canary\n"
    # cmd 是 `echo ...` —— 在空 ws 上也是 exit 0(canary 应拒)
    proposer = _make_proposer_with(_trivially_passing_echo_cmd(), test_content)
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="...")
    verdict = v.verify(verify_cmd=None, attempts=1)

    # 关键:canary 拒 → unverifiable(不是 passed)
    assert verdict.status == "unverifiable", f"废测试应被丢弃回退 unverifiable,实得 {verdict!r}"
    assert verdict.self_verified is False
    assert "无 verify_cmd" in verdict.detail


def test_self_test_no_proposer_no_self_test(
    in_tmp_workspace, monkeypatch,
):
    """generator.proposer is None → 不尝试造,直接 unverifiable(默认接口安全)。"""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    gen = TestGenerator(proposer=None)  # 默认 None
    v = Verifier(test_generator=gen, goal="...")
    verdict = v.verify(verify_cmd=None, attempts=1)
    assert verdict.status == "unverifiable"


def _trivially_passing_py_cmd() -> str:
    """返一个白名单内必过的 python3 单行(用于"用户 verify 通过"测)。"""
    return 'python3 -c "import sys; sys.exit(0)"'


def _trivially_passing_echo_cmd() -> str:
    """返一个白名单内必过的 echo(无副作用,空 ws 上也过 → canary 应拒)。"""
    return "echo argos_selftest"


# ── (c) 自验证结果是较弱的一类,不等同用户 verify 的 passed ────


def test_self_verified_verdict_distinguishable_from_user_verified(
    in_tmp_workspace, monkeypatch,
):
    """user_verified passed(self_verified=False)与 self_verified passed(自验证)在 verdict
    对象层面必须能区分;caller(UI/report/统计)能据此分流。"""
    # user-level passed(self_verified=False)
    user_v = Verdict.passed(
        detail="[exit_code=0]", verify_cmd="pytest -q", attempts=1,
    )
    assert user_v.self_verified is False

    # self-level passed(self_verified=True)
    self_v = Verdict.passed_self(
        detail="[self_verified] auto", verify_cmd="pytest -q", attempts=1,
    )
    assert self_v.status == "passed"
    assert self_v.self_verified is True

    # 比较:status 相同("passed"),self_verified 不同 → 谓词"is_user_verified_pass"能分流
    assert (user_v.status == "passed" and user_v.self_verified is False)
    assert (self_v.status == "passed" and self_v.self_verified is True)
    # 它们在 (status, self_verified) 平面里**不**等价
    assert (user_v.status, user_v.self_verified) != (self_v.status, self_v.self_verified)


def test_self_verified_passed_carries_self_verified_marker_in_detail(
    in_tmp_workspace, monkeypatch,
):
    """自验证通过的 Verdict.detail 必须带 [self_verified] 标记;任何人看 detail 字面
    就能知道这是较弱的、不是用户 verify 的。"""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    ws = in_tmp_workspace
    (ws / "thing.py").write_text("X = 1\n")
    test_content = textwrap.dedent("""
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("thing", Path("thing.py").resolve())
        m = importlib.util.module_from_spec(spec)  # type: ignore
        spec.loader.exec_module(m)  # type: ignore
        assert m.X == 1
    """).strip()
    proposer = _make_proposer_with("python3 test_argos_selftest.py", test_content)
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="verify X==1")
    verdict = v.verify(verify_cmd=None, attempts=1)
    assert verdict.status == "passed"
    assert verdict.self_verified is True
    assert "[self_verified]" in verdict.detail
    # 进一步:detail 必含"较弱" / "reviewer 角色"等显式弱化措辞
    assert "较弱" in verdict.detail or "reviewer" in verdict.detail.lower()


# ── (d) 默认关闭 ────────────────────────────


def test_self_test_default_off_returns_unverifiable(in_tmp_workspace, monkeypatch):
    """ARGOS_SELF_TEST 没设(或 != 1)→ verifier 完全不走 self-test,直接 unverifiable。

    本测试同时验:generator 就算被注入了,flag off 时也不被调(proposer 不该跑)。"""
    # 不设 env var
    monkeypatch.delenv("ARGOS_SELF_TEST", raising=False)

    proposer_called = {"n": 0}
    def _spy(goal, workspace):
        proposer_called["n"] += 1
        return ("true", "# never should run", "t.py")
    gen = TestGenerator(proposer=_spy)
    v = Verifier(test_generator=gen, goal="x")
    verdict = v.verify(verify_cmd=None, attempts=1)
    assert verdict.status == "unverifiable"
    assert verdict.self_verified is False
    # 关键:proposer 完全没被调
    assert proposer_called["n"] == 0, "flag off 时 proposer 不应被调"


def test_self_test_flag_off_keeps_existing_behavior(in_tmp_workspace, monkeypatch):
    """flag off + 有 user verify_cmd → 走原有路径(user verify,passed,非 self_verified)。

    防回归:flag off 改动其它任何路径。"""
    monkeypatch.delenv("ARGOS_SELF_TEST", raising=False)
    (in_tmp_workspace / "thing.py").write_text("X = 1\n")
    v = Verifier()
    verdict = v.verify(verify_cmd=_trivially_passing_py_cmd(), attempts=1)
    assert verdict.status == "passed"
    assert verdict.self_verified is False   # user-level


# ── (e) 生成的命令不在白名单 → 丢弃 ───────────────


def test_self_test_rejects_cmd_not_in_whitelist(in_tmp_workspace, monkeypatch):
    """proposer 返的 cmd 跑 ALLOWED_CMDS 白名单复检 → 不在则丢弃(防 reviewer 写出
    `curl example.com` / `bash -c 'rm -rf /'` 等越权命令,即便 canary 假阳性也阻)。"""
    monkeypatch.setenv("ARGOS_SELF_TEST", "1")
    proposer = _make_proposer_with("rm -rf /tmp/nonexistent_argos_dir", "# x")
    gen = TestGenerator(proposer=proposer)
    v = Verifier(test_generator=gen, goal="x")
    verdict = v.verify(verify_cmd=None, attempts=1)
    # 拒收 → unverifiable
    assert verdict.status == "unverifiable"
    assert verdict.self_verified is False


# ── TestGenerator 单元层 ──────────────────────


def test_test_generator_canary_check_unit(tmp_path):
    """TestGenerator._canary_check 直接:废测试(空 ws 上也 exit 0)→ canary_passed=False。"""
    gen = TestGenerator(
        proposer=_make_proposer_with("echo trivially-passing", "# x"),
    )
    proposal = gen.propose_and_validate(goal="x", workspace=tmp_path)
    assert proposal is None   # canary 阻


def test_test_generator_writes_test_file_and_canary_passes(tmp_path, monkeypatch):
    """TestGenerator 在 canary 过时把测试文件写到 verify_dir 内,真跑也可被外部 _run_verify
    找到(它 cwd=verify_dir;workspace 内的 lib.py 通过 PYTHONPATH 也能 import)。"""
    from argos import runtime
    # 切到 tmp_path(workspace=verify_dir=tmp_path)
    token = runtime.use_project(str(tmp_path))
    try:
        (tmp_path / "lib.py").write_text("ANS = 7\n")
        test_content = textwrap.dedent("""
            import importlib.util
            from pathlib import Path
            s = importlib.util.spec_from_file_location("lib", Path("lib.py").resolve())
            m = importlib.util.module_from_spec(s)  # type: ignore
            s.loader.exec_module(m)  # type: ignore
            assert m.ANS == 7
        """).strip()
        gen = TestGenerator(
            proposer=_make_proposer_with(
                "python3 test_argos_selftest.py", test_content,
            ),
        )
        proposal = gen.propose_and_validate(goal="x", workspace=tmp_path)
        assert proposal is not None
        assert proposal.canary_passed is True
        # 测试文件已写到 verify_dir(即 tmp_path,project 模式下 == workspace)
        assert (tmp_path / "test_argos_selftest.py").exists()
        # proposal.cmd 包含我们要跑的 cmd
        assert "python3" in proposal.cmd
    finally:
        runtime.reset(token)


def test_is_whitelisted():
    """_is_whitelisted 白名单复检,真模式要靠它防 reviewer 越权。"""
    assert _is_whitelisted("pytest -q") is True
    assert _is_whitelisted("python3 -c 'x'") is True
    assert _is_whitelisted("python3 -c 'exit 0'") is True
    assert _is_whitelisted("echo x") is True
    assert _is_whitelisted("rm -rf /tmp") is False
    assert _is_whitelisted("curl http://x") is False
    assert _is_whitelisted("bash -c 'echo x'") is False   # bash 不在白名单
    assert _is_whitelisted("true") is False              # 也不在(只验白名单内 token)
    assert _is_whitelisted("") is False
