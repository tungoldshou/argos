"""tests/verify_strategy/test_strategy.py

验证梯子策略生成器的全套测试：
  · 各任务类型策略生成 + 梯子降序
  · 发送类红线（绝无 L3/cmd 型策略，首位即 L5）
  · fallback 永远存在（空 goal / 胡乱输入也返回 L5）
  · probe_workspace 只读（不创建文件）
  · capability verify_hint 被消费进 rationale/target
  · VerifyStrategy 不变量（confidence 越界、L5 kind 不符均报错）
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from argos.verify.strategy import (
    Level,
    Kind,
    VerifyStrategy,
    WorkspaceFacts,
    generate,
    probe_workspace,
)


# ═══════════════════════════════════════════════════════
# 基础不变量
# ═══════════════════════════════════════════════════════

class TestVerifyStrategyInvariants:
    """VerifyStrategy dataclass 不变量测试。"""

    def test_valid_strategy_ok(self) -> None:
        s = VerifyStrategy(
            level="L1", kind="exit_code", cmd="pytest",
            target=None, rationale_human="runs pytest", confidence=0.9,
        )
        assert s.level == "L1"
        assert s.confidence == 0.9

    def test_confidence_zero_ok(self) -> None:
        s = VerifyStrategy(
            level="L5", kind="evidence_trail", cmd=None,
            target=None, rationale_human="no machine check", confidence=0.0,
        )
        assert s.confidence == 0.0

    def test_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            VerifyStrategy(
                level="L1", kind="exit_code", cmd="pytest",
                target=None, rationale_human="x", confidence=-0.1,
            )

    def test_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            VerifyStrategy(
                level="L1", kind="exit_code", cmd="pytest",
                target=None, rationale_human="x", confidence=1.01,
            )

    def test_l5_must_be_evidence_trail(self) -> None:
        with pytest.raises(ValueError, match="evidence_trail"):
            VerifyStrategy(
                level="L5", kind="exit_code", cmd="pytest",
                target=None, rationale_human="wrong kind", confidence=0.0,
            )

    def test_frozen(self) -> None:
        s = VerifyStrategy(
            level="L1", kind="exit_code", cmd="pytest",
            target=None, rationale_human="x", confidence=0.8,
        )
        with pytest.raises((AttributeError, TypeError)):
            s.level = "L2"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════
# fallback 永远存在
# ═══════════════════════════════════════════════════════

class TestFallbackAlwaysPresent:
    """任何输入都必须返回至少一个 L5 evidence_trail 策略。"""

    def _has_l5(self, strategies: tuple[VerifyStrategy, ...]) -> bool:
        return any(s.level == "L5" and s.kind == "evidence_trail" for s in strategies)

    def _last_is_l5(self, strategies: tuple[VerifyStrategy, ...]) -> bool:
        return strategies[-1].level == "L5" and strategies[-1].kind == "evidence_trail"

    def test_empty_goal_has_l5(self) -> None:
        strats = generate("", workspace_facts=WorkspaceFacts())
        assert len(strats) >= 1
        assert self._has_l5(strats), "空 goal 必须有 L5 退路"
        assert self._last_is_l5(strats), "L5 必须是最后一条"

    def test_gibberish_goal_has_l5(self) -> None:
        strats = generate("xkq93&&##@!wq", workspace_facts=WorkspaceFacts())
        assert self._has_l5(strats), "胡乱输入必须有 L5"
        assert self._last_is_l5(strats)

    def test_normal_code_task_has_l5(self) -> None:
        facts = WorkspaceFacts(has_pytest=True)
        strats = generate("implement a sort function", workspace_facts=facts)
        assert self._has_l5(strats)
        assert self._last_is_l5(strats)

    def test_result_never_empty(self) -> None:
        """generate 永远非空。"""
        strats = generate("", workspace_facts=WorkspaceFacts())
        assert len(strats) >= 1


# ═══════════════════════════════════════════════════════
# 发送类红线测试（最重要）
# ═══════════════════════════════════════════════════════

class TestSendTaskRedLine:
    """发送/购买/通知类任务：绝无 L3/cmd 型策略，首位即 L5，绝不假绿。

    红线：策略集中若出现 cmd 含 curl/http/wget 给发送类任务 → bug。
    """

    SEND_GOALS = [
        "send an email to alice@example.com",
        "发邮件给张三",
        "notify the user via SMS",
        "post a tweet about the release",
        "buy the item and checkout",
        "purchase product id 42",
        "submit the order",
        "send a Slack message to #general",
        "deploy and push to production",
        "通知所有用户账单已到",
        "发送短信验证码",
        "publish the blog post",
    ]

    def _assert_send_red_line(self, goal: str) -> None:
        strats = generate(goal, workspace_facts=WorkspaceFacts())
        # 1. 永远非空
        assert len(strats) >= 1, f"策略集不能为空: {goal!r}"
        # 2. 首位必须是 L5
        assert strats[0].level == "L5", (
            f"发送类任务首位必须是 L5 退路，实际是 {strats[0].level}: {goal!r}"
        )
        assert strats[0].kind == "evidence_trail", (
            f"发送类任务首位 kind 必须是 evidence_trail: {goal!r}"
        )
        # 3. 绝无 L3 策略
        l3_strats = [s for s in strats if s.level == "L3"]
        assert len(l3_strats) == 0, (
            f"发送类任务不允许有 L3 策略: {goal!r}\n找到: {l3_strats}"
        )
        # 4. 绝无 cmd 含 curl/http/wget 的策略
        bad_cmds = [
            s for s in strats
            if s.cmd and any(
                kw in s.cmd.lower() for kw in ("curl", "http", "wget", "requests")
            )
        ]
        assert len(bad_cmds) == 0, (
            f"发送类任务策略 cmd 不能含 curl/http/wget: {goal!r}\n找到: {bad_cmds}"
        )
        # 5. 整体只有一条（L5），不会混入 L1/L2
        assert len(strats) == 1, (
            f"发送类任务应只有一条 L5 策略，实际有 {len(strats)} 条: {goal!r}\n{strats}"
        )

    @pytest.mark.parametrize("goal", SEND_GOALS)
    def test_send_goals_red_line(self, goal: str) -> None:
        self._assert_send_red_line(goal)

    def test_send_with_workspace_facts_still_l5_only(self) -> None:
        """即使工作区有 pytest，发送类任务仍只返回 L5。"""
        facts = WorkspaceFacts(has_pytest=True, has_cargo=True)
        strats = generate(
            "send email report to manager",
            workspace_facts=facts,
        )
        assert len(strats) == 1
        assert strats[0].level == "L5"

    def test_send_with_capability_hints_still_l5_only(self) -> None:
        """即使有 capability hints，发送类任务仍只返回 L5。"""
        strats = generate(
            "notify all users via push notification",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "#notification-badge", "dom_url": "http://app"},
        )
        assert strats[0].level == "L5"
        assert len(strats) == 1


# ═══════════════════════════════════════════════════════
# 代码任务 + 测试框架策略生成
# ═══════════════════════════════════════════════════════

class TestCodeTaskStrategies:
    """代码任务 + 测试框架存在 → L1 策略出现。"""

    def test_pytest_workspace_yields_l1(self) -> None:
        facts = WorkspaceFacts(has_pytest=True)
        strats = generate("implement a binary search function", workspace_facts=facts)
        l1 = [s for s in strats if s.level == "L1"]
        assert len(l1) >= 1, "有 pytest 的代码任务应生成 L1 策略"
        assert l1[0].kind == "exit_code"
        assert l1[0].cmd is not None
        assert "pytest" in l1[0].cmd.lower()

    def test_cargo_workspace_yields_l1(self) -> None:
        facts = WorkspaceFacts(has_cargo=True)
        strats = generate("implement a Rust parser", workspace_facts=facts)
        l1_cmds = [s.cmd for s in strats if s.level == "L1"]
        assert any(c and "cargo" in c for c in l1_cmds)

    def test_go_workspace_yields_l1(self) -> None:
        facts = WorkspaceFacts(has_go_mod=True)
        strats = generate("implement go http middleware", workspace_facts=facts)
        l1_cmds = [s.cmd for s in strats if s.level == "L1"]
        assert any(c and "go test" in c for c in l1_cmds)

    def test_npm_workspace_yields_l1(self) -> None:
        facts = WorkspaceFacts(has_package_json=True)
        strats = generate("build a React component", workspace_facts=facts)
        l1_cmds = [s.cmd for s in strats if s.level == "L1"]
        assert any(c and "npm test" in c for c in l1_cmds)

    def test_no_framework_no_l1(self) -> None:
        """无框架信号、无代码信号 → 无 L1。"""
        facts = WorkspaceFacts()
        strats = generate("write a report about the market", workspace_facts=facts)
        l1 = [s for s in strats if s.level == "L1"]
        assert len(l1) == 0, f"无框架写作任务不应有 L1: {l1}"

    def test_strategies_ordered_l1_before_l5(self) -> None:
        """L1 策略必须在 L5 之前。"""
        facts = WorkspaceFacts(has_pytest=True)
        strats = generate("implement sorting", workspace_facts=facts)
        levels = [s.level for s in strats]
        assert levels.index("L1") < levels.index("L5")

    def test_capability_hint_pytest_cmd_consumed(self) -> None:
        """pytest_cmd capability hint 被嵌入 L1 策略的 cmd 和 rationale 中。"""
        facts = WorkspaceFacts(has_pytest=True)
        strats = generate(
            "implement feature",
            workspace_facts=facts,
            capability_hints={"pytest_cmd": "pytest tests/unit -x"},
        )
        l1 = [s for s in strats if s.level == "L1"]
        assert l1, "有 pytest 应有 L1"
        assert "pytest tests/unit -x" in l1[0].cmd
        # rationale 提到 hint
        assert "pytest tests/unit -x" in l1[0].rationale_human or "capability" in l1[0].rationale_human.lower()


# ═══════════════════════════════════════════════════════
# 声明产物文件 → L2 策略
# ═══════════════════════════════════════════════════════

class TestArtifactStrategies:
    """声明产物文件 → L2 artifact_exists / schema 策略。"""

    def test_declared_file_yields_l2(self) -> None:
        facts = WorkspaceFacts(declared_files=("output.json",))
        strats = generate("generate output.json with results", workspace_facts=facts)
        l2 = [s for s in strats if s.level == "L2"]
        assert len(l2) >= 1
        targets = [s.target for s in l2 if s.target]
        assert any("output.json" in (t or "") for t in targets)

    def test_json_file_in_goal_yields_schema_check(self) -> None:
        """goal 文本中出现 .json 文件名 → 生成 artifact_schema 策略（JSON 合法性检查）。"""
        strats = generate(
            "write the analysis to report.json",
            workspace_facts=WorkspaceFacts(),
        )
        schema_strats = [s for s in strats if s.kind == "artifact_schema"]
        assert schema_strats, "JSON 文件目标应有 artifact_schema 策略"
        assert all("report.json" in (s.target or "") for s in schema_strats)

    def test_csv_file_in_goal_yields_content_assert(self) -> None:
        strats = generate(
            "export data to results.csv",
            workspace_facts=WorkspaceFacts(),
        )
        content_strats = [s for s in strats if s.kind == "content_assert" and s.target and "results.csv" in s.target]
        assert content_strats, "CSV 文件目标应有 content_assert 策略"

    def test_artifact_target_in_rationale_or_target(self) -> None:
        """verify_file capability hint 被消费进 target / rationale。"""
        strats = generate(
            "create output",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"verify_file": "dist/bundle.js"},
        )
        l2 = [s for s in strats if s.level == "L2"]
        assert l2, "verify_file hint 应生成 L2 策略"
        assert any("dist/bundle.js" in (s.target or "") for s in l2), (
            f"verify_file hint 应出现在 target 中: {l2}"
        )

    def test_l2_before_l5(self) -> None:
        facts = WorkspaceFacts(declared_files=("output.json",))
        strats = generate("write output.json", workspace_facts=facts)
        levels = [s.level for s in strats]
        assert levels.index("L2") < levels.index("L5")


# ═══════════════════════════════════════════════════════
# 网页/DOM 策略
# ═══════════════════════════════════════════════════════

class TestWebStrategies:
    """网页改动 + dom hint → L3 dom_assert；但发送类不得生成 L3。"""

    def test_web_goal_with_hints_yields_l3(self) -> None:
        strats = generate(
            "update the webpage to show the new headline",
            workspace_facts=WorkspaceFacts(),
            capability_hints={
                "dom_selector": "h1.headline",
                "dom_url": "http://localhost:3000",
            },
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert l3, "网页任务 + dom hints 应有 L3 策略"
        assert any("h1.headline" in (s.target or "") for s in l3)

    def test_web_goal_without_hints_no_l3(self) -> None:
        """没有 dom hints → 不生成 L3（无法填充 selector/url，不造空策略）。"""
        strats = generate(
            "update the webpage layout",
            workspace_facts=WorkspaceFacts(),
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert len(l3) == 0, f"无 dom hints 不应有 L3: {l3}"

    def test_l3_before_l5(self) -> None:
        strats = generate(
            "render the html page",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "body", "dom_url": "http://localhost"},
        )
        levels = [s.level for s in strats]
        if "L3" in levels:
            assert levels.index("L3") < levels.index("L5")


# ═══════════════════════════════════════════════════════
# probe_workspace 只读性
# ═══════════════════════════════════════════════════════

class TestProbeWorkspace:
    """probe_workspace 只读：不创建文件、不修改状态。"""

    def test_empty_dir_returns_all_false(self, tmp_path: Path) -> None:
        facts = probe_workspace(tmp_path)
        assert not facts.has_pytest
        assert not facts.has_cargo
        assert not facts.has_package_json
        assert not facts.has_makefile
        assert not facts.has_go_mod
        assert not facts.json_output
        assert not facts.csv_output

    def test_nonexistent_dir_returns_defaults(self) -> None:
        facts = probe_workspace(Path("/nonexistent/workspace/xyz"))
        assert facts == WorkspaceFacts()

    def test_does_not_create_files(self, tmp_path: Path) -> None:
        """探测前后目录内容不变。"""
        before = set(tmp_path.iterdir())
        probe_workspace(tmp_path)
        after = set(tmp_path.iterdir())
        assert before == after, f"probe_workspace 不能创建文件！新增: {after - before}"

    def test_detects_pytest(self, tmp_path: Path) -> None:
        (tmp_path / "conftest.py").write_text("")
        facts = probe_workspace(tmp_path)
        assert facts.has_pytest

    def test_pyproject_only_no_pytest(self, tmp_path: Path) -> None:
        """Phase 5.2:纯 pyproject.toml（无测试文件）不算 has_pytest —— 否则在没测试的项目里
        推 pytest 会收集 0 个、以退出码 5 误判失败。"""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        assert probe_workspace(tmp_path).has_pytest is False

    def test_pyproject_plus_test_files_is_pytest(self, tmp_path: Path) -> None:
        """有可收集的测试文件（tests/test_*.py）→ has_pytest=True（弱信号 + 真测试）。"""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_thing.py").write_text("def test_a():\n    assert True\n")
        assert probe_workspace(tmp_path).has_pytest is True

    def test_top_level_test_file_is_pytest(self, tmp_path: Path) -> None:
        """顶层 test_*.py 也算 has_pytest（pytest 默认能收集）。"""
        (tmp_path / "test_top.py").write_text("def test_a():\n    assert True\n")
        assert probe_workspace(tmp_path).has_pytest is True

    def test_detects_cargo(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\nversion = '0.1.0'")
        facts = probe_workspace(tmp_path)
        assert facts.has_cargo

    def test_detects_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        facts = probe_workspace(tmp_path)
        assert facts.has_package_json

    def test_detects_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("test:\n\tpytest")
        facts = probe_workspace(tmp_path)
        assert facts.has_makefile

    def test_detects_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/m\ngo 1.21")
        facts = probe_workspace(tmp_path)
        assert facts.has_go_mod

    def test_detects_json_output(self, tmp_path: Path) -> None:
        (tmp_path / "result.json").write_text("{}")
        facts = probe_workspace(tmp_path)
        assert facts.json_output

    def test_detects_csv_output(self, tmp_path: Path) -> None:
        (tmp_path / "data.csv").write_text("a,b\n1,2")
        facts = probe_workspace(tmp_path)
        assert facts.csv_output

    def test_does_not_recurse_subdirs(self, tmp_path: Path) -> None:
        """probe 只看顶层文件，不递归（保持只读 + 快速）。"""
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "data.json").write_text("{}")
        facts = probe_workspace(tmp_path)
        # 顶层没有 .json → json_output 应为 False
        assert not facts.json_output

    def test_probe_multiple_times_idempotent(self, tmp_path: Path) -> None:
        (tmp_path / "conftest.py").write_text("")
        f1 = probe_workspace(tmp_path)
        f2 = probe_workspace(tmp_path)
        assert f1 == f2


# ═══════════════════════════════════════════════════════
# capability_hints 消费测试
# ═══════════════════════════════════════════════════════

class TestCapabilityHintsConsumed:
    """capability hints 被消费进 rationale 或 target。"""

    def test_verify_file_hint_in_target(self) -> None:
        strats = generate(
            "build the project and write output",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"verify_file": "build/output.tar"},
        )
        l2 = [s for s in strats if s.level == "L2"]
        assert l2
        assert any("build/output.tar" in (s.target or "") for s in l2)

    def test_dom_hints_in_target(self) -> None:
        strats = generate(
            "render the frontend page",
            workspace_facts=WorkspaceFacts(),
            capability_hints={
                "dom_selector": ".hero-title",
                "dom_url": "http://localhost:8080",
            },
        )
        l3 = [s for s in strats if s.level == "L3"]
        assert l3
        t = l3[0].target or ""
        assert ".hero-title" in t or "localhost:8080" in t

    def test_none_hints_treated_as_empty(self) -> None:
        """capability_hints=None 不报错，行为与 {} 相同。"""
        strats_none = generate("implement feature", workspace_facts=WorkspaceFacts(), capability_hints=None)
        strats_empty = generate("implement feature", workspace_facts=WorkspaceFacts(), capability_hints={})
        assert strats_none == strats_empty

    def test_unknown_hints_ignored(self) -> None:
        """未知 hint key 不影响生成（不报错，不产生奇怪策略）。"""
        strats = generate(
            "implement feature",
            workspace_facts=WorkspaceFacts(has_pytest=True),
            capability_hints={"unknown_key": "some_value", "another": "123"},
        )
        assert any(s.level == "L5" for s in strats)


# ═══════════════════════════════════════════════════════
# 梯子降序保证
# ═══════════════════════════════════════════════════════

class TestLadderOrdering:
    """验证梯子降序：L1 > L2 > L3 > L5（有多个级别时顺序正确）。"""

    LEVEL_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L5": 5}

    def _is_non_decreasing(self, strategies: tuple[VerifyStrategy, ...]) -> bool:
        """策略序列按梯子等级单调不减（允许同级相邻）。"""
        prev = 0
        for s in strategies:
            cur = self.LEVEL_ORDER[s.level]
            if cur < prev:
                return False
            prev = cur
        return True

    def test_code_task_ordering(self) -> None:
        facts = WorkspaceFacts(has_pytest=True)
        strats = generate(
            "implement a sort function and output results.json",
            workspace_facts=facts,
        )
        assert self._is_non_decreasing(strats), (
            f"策略必须按梯子降序: {[(s.level, s.kind) for s in strats]}"
        )

    def test_web_task_ordering(self) -> None:
        strats = generate(
            "update the webpage",
            workspace_facts=WorkspaceFacts(),
            capability_hints={"dom_selector": "h1", "dom_url": "http://localhost"},
        )
        assert self._is_non_decreasing(strats)

    def test_all_zeros_workspace_just_l5(self) -> None:
        strats = generate("describe the algorithm", workspace_facts=WorkspaceFacts())
        # 无代码/框架/产物信号 → 只有 L5
        levels = {s.level for s in strats}
        assert levels == {"L5"}, f"无信号任务应只有 L5: {levels}"


# ═══════════════════════════════════════════════════════
# 去重保证
# ═══════════════════════════════════════════════════════

class TestDeduplication:
    """相同 (level, kind, cmd, target) 不重复出现。"""

    def test_no_duplicate_strategies(self) -> None:
        facts = WorkspaceFacts(has_pytest=True, declared_files=("output.json",))
        strats = generate(
            "implement and write output.json",
            workspace_facts=facts,
        )
        keys = [(s.level, s.kind, s.cmd, s.target) for s in strats]
        assert len(keys) == len(set(keys)), f"策略出现重复: {keys}"

    def test_only_one_l5(self) -> None:
        """L5 退路只出现一次。"""
        facts = WorkspaceFacts(has_pytest=True, has_cargo=True, has_package_json=True)
        strats = generate(
            "implement multi-framework project",
            workspace_facts=facts,
        )
        l5_count = sum(1 for s in strats if s.level == "L5")
        assert l5_count == 1, f"L5 应只出现一次，实际 {l5_count} 次"


# ═══════════════════════════════════════════════════════
# L5 内容检查
# ═══════════════════════════════════════════════════════

class TestL5Content:
    """L5 退路策略内容检查（人话 + cmd=None）。"""

    def test_l5_cmd_is_none(self) -> None:
        strats = generate("", workspace_facts=WorkspaceFacts())
        l5 = [s for s in strats if s.level == "L5"]
        assert all(s.cmd is None for s in l5), "L5 策略不能有 cmd"

    def test_l5_confidence_is_zero(self) -> None:
        strats = generate("", workspace_facts=WorkspaceFacts())
        l5 = [s for s in strats if s.level == "L5"]
        assert all(s.confidence == 0.0 for s in l5)

    def test_l5_rationale_human_not_empty(self) -> None:
        strats = generate("some task", workspace_facts=WorkspaceFacts())
        l5 = [s for s in strats if s.level == "L5"]
        assert all(len(s.rationale_human.strip()) > 0 for s in l5)

    def test_send_l5_rationale_explains_why(self) -> None:
        """发送类任务的 L5 rationale 应解释传输层成功 ≠ 任务正确。"""
        strats = generate("send email to boss", workspace_facts=WorkspaceFacts())
        l5 = strats[0]
        assert "传输层" in l5.rationale_human or "200" in l5.rationale_human or "发送" in l5.rationale_human


# ═══════════════════════════════════════════════════════
# 反向护栏：代码任务不被发送/git 词误伤(终审 major 修正的防回归钉)
# ═══════════════════════════════════════════════════════

class TestCodeTaskNotHijackedBySendWords:
    """含 commit/push/merge/post/order 等词的【代码任务】在有 pytest 的工作区
    必须仍产 L1 策略 —— 防止发送类红线过度触发把日常代码任务压成 L5-only
    (验证强度无谓回退)。红线不变量(无 curl/http 型策略)对这些任务依然成立。
    """

    CODE_GOALS_WITH_TRICKY_WORDS = [
        "implement a sort function and commit it",
        "fix the bug and push",
        "refactor the module and merge the branch",
        "add a post-processing step to the pipeline",
        "implement an order book matching engine",
        "修复 bug 然后提交代码",
    ]

    @pytest.mark.parametrize("goal", CODE_GOALS_WITH_TRICKY_WORDS)
    def test_code_task_keeps_l1_with_pytest(self, goal: str) -> None:
        facts = WorkspaceFacts(has_pytest=True)
        strats = generate(goal, workspace_facts=facts)
        levels = [s.level for s in strats]
        assert "L1" in levels, (
            f"代码任务被发送词误伤压成 {levels}(应含 L1): {goal!r}"
        )
        # L5 退路仍在末位(梯子完整)
        assert strats[-1].level == "L5", f"末位必须是 L5 退路: {goal!r}"
        # 红线全局不变量:仍然绝无传输探活型策略
        bad = [s for s in strats if s.cmd and any(
            kw in s.cmd.lower() for kw in ("curl", "http", "wget", "requests"))]
        assert not bad, f"出现传输探活型策略(假绿红线): {goal!r}\n{bad}"

    def test_pure_send_still_red_lined(self) -> None:
        """修正后纯发送任务红线不松动(双向都钉死)。"""
        strats = generate("send an email to bob", workspace_facts=WorkspaceFacts(has_pytest=True))
        assert len(strats) == 1 and strats[0].level == "L5"


# ═══════════════════════════════════════════════════════
# VLM/截图红线契约测试(P6a §10)
# ═══════════════════════════════════════════════════════

class TestVlmScreenshotRedline:
    """P6a §10 VLM/截图红线:任何 VerifyStrategy 候选都不得以 screenshot 为唯一证据产出 cmd。

    规则来源:spec §10 + CLAUDE.md §3:
      · 截图/VLM 结果永不单独产出 "passed"。
      · 任何策略的 cmd 字段都不得仅依赖截图命令(screencapture / screenshot / scrot)
        来给出 passed 判断。
      · L5 evidence_trail(cmd=None)是唯一合法的"无机检退路"——它诚实声明 unverifiable。
      · 防未来回归:无论如何修改 generate() 或新增策略类型,此契约测试必须继续通过。
    """

    # screenshot 命令关键词集合(防未来回归:若新增截图工具也应加入此集合)
    _SCREENSHOT_CMD_PATTERNS = (
        "screencapture",
        "screenshot",
        "scrot",
        "import -window",   # ImageMagick 截图
        "gnome-screenshot",
    )

    def _has_screenshot_only_cmd(self, strategy: VerifyStrategy) -> bool:
        """判断该策略是否以截图命令为唯一验证手段(cmd 非 None 且仅含截图)。"""
        cmd = strategy.cmd
        if cmd is None:
            return False  # cmd=None 是 L5 诚实退路,不是截图验证
        cmd_lower = cmd.lower()
        # 命令仅含截图指令(不含测试/断言/文件存在等其他验证手段)
        has_screenshot = any(kw in cmd_lower for kw in self._SCREENSHOT_CMD_PATTERNS)
        if not has_screenshot:
            return False
        # 若同时含有 test/assert/grep/python/pytest/cargo 等,说明是混合命令不算纯截图
        real_verify_keywords = ("pytest", "cargo", "assert", "grep", "test -f", "python", "node")
        has_real_verify = any(kw in cmd_lower for kw in real_verify_keywords)
        return not has_real_verify

    @pytest.mark.parametrize("goal", [
        "implement a new feature",
        "fix the login bug",
        "write tests for auth module",
        "create a report.json file",
        "build the project",
        "send an email",
        "take a screenshot of the dashboard",
        "capture the screen and save to png",
        "screenshot the current state",
        "",
        "random gibberish xyz 123",
    ])
    def test_no_screenshot_only_cmd_in_any_goal(self, goal: str) -> None:
        """任何 goal 的策略序列中,均不得出现以截图命令为唯一验证手段的候选。

        这是防未来回归的契约测试:即便将来新增了 VLM/截图相关策略生成逻辑,
        也绝不允许以"截图成功 = 任务通过"逻辑产生 cmd 型策略。
        """
        facts = WorkspaceFacts(
            has_pytest=True,
            has_cargo=False,
            has_package_json=False,
            has_makefile=False,
            has_go_mod=False,
        )
        strats = generate(goal, workspace_facts=facts)
        bad = [s for s in strats if self._has_screenshot_only_cmd(s)]
        assert not bad, (
            f"goal={goal!r} 产出了以截图为唯一验证手段的策略(VLM 红线违反):\n"
            + "\n".join(f"  {s}" for s in bad)
        )

    def test_no_screenshot_only_cmd_with_screenshot_hints(self) -> None:
        """即便 capability_hints 中含有截图相关 hint,也不得产出截图唯一验证策略。"""
        facts = WorkspaceFacts()
        hints = {
            "screenshot_path": "/tmp/test.png",
            "dom_url": "http://localhost:3000",
        }
        strats = generate(
            "verify the UI looks correct",
            workspace_facts=facts,
            capability_hints=hints,
        )
        bad = [s for s in strats if self._has_screenshot_only_cmd(s)]
        assert not bad, (
            "capability_hints 含截图路径时仍产出截图唯一验证策略(VLM 红线违反):\n"
            + "\n".join(f"  {s}" for s in bad)
        )

    def test_l5_is_always_last_and_cmd_is_none(self) -> None:
        """L5 退路永远在末位,且 cmd=None(诚实 unverifiable,不是截图验证)。

        这是红线的另一面:L5 不含 cmd 就是诚实说"无法机检",不能被截图 cmd 替换。
        """
        for goal in ("take a screenshot", "capture screen", "verify UI visually"):
            facts = WorkspaceFacts()
            strats = generate(goal, workspace_facts=facts)
            last = strats[-1]
            assert last.level == "L5", f"末位不是 L5:{goal!r}"
            assert last.cmd is None, (
                f"L5 退路 cmd 不得为 screenshot 命令(应为 None):{goal!r}, cmd={last.cmd!r}"
            )
            assert last.kind == "evidence_trail", f"L5 kind 必须是 evidence_trail:{goal!r}"
