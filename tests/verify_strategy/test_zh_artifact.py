"""tests/verify_strategy/test_zh_artifact.py

中文/英文目标泛化测试（C 轨：实测盲区修复）。

覆盖：
  · 实测原话回归（会议记录整理任务）
  · 动词锚定目录提取（整理到/移动到/创建等）
  · 动词锚定文件提取（创建/写等）
  · 英文对应动词（organize into / move to / create folder）
  · 防过度提取红线：
      a) 否定语境（不要动/别动）
      b) 模板占位符（YYYY/MM/DD/*）
      c) 非法路径片段（../ 开头）
  · 末位仍为 L5
  · 既有策略（发送类红线 / fallback 非空）不受影响
"""
from __future__ import annotations

import pytest

from argos_agent.verify.strategy import (
    VerifyStrategy,
    WorkspaceFacts,
    generate,
    _extract_zh_dir_targets,
    _extract_zh_file_targets,
    _is_valid_artifact_path,
    _is_negation_context,
)

# ═══════════════════════════════════════════════════════
# 实测原话回归（C 轨核心场景）
# ═══════════════════════════════════════════════════════

REAL_WORLD_GOAL = (
    "把这个文件夹里的会议记录整理到 meetings 子文件夹，"
    "文件名统一改成「YYYY-MM-DD 会议记录.txt」格式，"
    "购物清单和随手记不要动"
)


class TestRealWorldGoalRegression:
    """实测原话：会议记录整理任务的策略生成回归测试。"""

    def _get_candidates(self) -> tuple[VerifyStrategy, ...]:
        return generate(REAL_WORLD_GOAL, workspace_facts=WorkspaceFacts())

    def test_has_l2_artifact_exists_for_meetings_dir(self) -> None:
        """候选中必须含 L2 artifact_exists，target=meetings，cmd=test -d meetings。"""
        strats = self._get_candidates()
        l2_dir = [
            s for s in strats
            if s.level == "L2"
            and s.kind == "artifact_exists"
            and s.target == "meetings"
            and s.cmd == "test -d meetings"
        ]
        assert l2_dir, (
            f"实测原话应产出 meetings 目录断言，实际候选：\n"
            + "\n".join(f"  {s}" for s in strats)
        )

    def test_no_template_placeholder_assertion(self) -> None:
        """不含任何字面断言 YYYY-MM-DD 或含「YYYY」的 target/cmd。"""
        strats = self._get_candidates()
        bad = [
            s for s in strats
            if s.target and "YYYY" in s.target
            or s.cmd and "YYYY" in s.cmd
        ]
        assert not bad, (
            f"不得对模板占位符字面断言（YYYY-MM-DD 是格式模板不是文件名）：\n"
            + "\n".join(f"  {s}" for s in bad)
        )

    def test_no_shopping_list_or_notes_assertion(self) -> None:
        """不含购物清单/随手记相关断言（否定语境）。"""
        strats = self._get_candidates()
        bad = [
            s for s in strats
            if (s.target and ("购物清单" in s.target or "随手记" in s.target))
            or (s.cmd and ("购物清单" in s.cmd or "随手记" in s.cmd))
        ]
        assert not bad, (
            f"否定语境的 X 不得被提取断言：\n"
            + "\n".join(f"  {s}" for s in bad)
        )

    def test_last_strategy_is_l5(self) -> None:
        """末位策略仍为 L5 evidence_trail。"""
        strats = self._get_candidates()
        assert strats[-1].level == "L5", f"末位不是 L5：{strats[-1]}"
        assert strats[-1].kind == "evidence_trail"

    def test_result_is_non_empty(self) -> None:
        """generate 永远非空。"""
        strats = self._get_candidates()
        assert len(strats) >= 1


# ═══════════════════════════════════════════════════════
# _extract_zh_dir_targets 单元测试
# ═══════════════════════════════════════════════════════

class TestExtractZhDirTargets:
    """_extract_zh_dir_targets 动词锚定目录提取单元测试。"""

    @pytest.mark.parametrize("goal,expected", [
        # 整理到 X 子文件夹
        ("把会议记录整理到 meetings 子文件夹", ["meetings"]),
        ("整理到 reports 文件夹", ["reports"]),
        # 保存到 X 目录
        ("把文件保存到 archive 目录", ["archive"]),
        # 放到 X 文件夹
        ("文档放到 docs 子文件夹", ["docs"]),
        # 移动到 X 目录
        ("把图片移动到 images 目录", ["images"]),
        # 移到 X 文件夹
        ("日志移到 logs 文件夹", ["logs"]),
        # 归档到 X 目录
        ("旧文件归档到 backup 目录", ["backup"]),
        # 创建 X 文件夹
        ("创建 output 文件夹", ["output"]),
        # 新建 X 目录
        ("新建 data 目录", ["data"]),
        # 英文：organize into
        ("organize meeting notes into notes folder", ["notes"]),
        ("move files to archive directory", ["archive"]),
        # 含路径分隔符
        ("整理到 data/meetings 子文件夹", ["data/meetings"]),
    ])
    def test_extracts_expected_targets(self, goal: str, expected: list[str]) -> None:
        result = _extract_zh_dir_targets(goal)
        for exp in expected:
            assert exp in result, (
                f"goal={goal!r} 应提取目录 {exp!r}，实际结果：{result}"
            )

    def test_no_extraction_from_empty_goal(self) -> None:
        assert _extract_zh_dir_targets("") == []

    def test_deduplication(self) -> None:
        """同一目录名多次出现只保留一个。"""
        goal = "整理到 meetings 子文件夹，再整理到 meetings 目录"
        result = _extract_zh_dir_targets(goal)
        assert result.count("meetings") == 1


# ═══════════════════════════════════════════════════════
# _extract_zh_file_targets 单元测试
# ═══════════════════════════════════════════════════════

class TestExtractZhFileTargets:
    """_extract_zh_file_targets 动词锚定文件提取单元测试。"""

    @pytest.mark.parametrize("goal,expected", [
        ("创建 report.json 文件", ["report.json"]),
        ("生成 output.csv", ["output.csv"]),
        ("写 summary.txt", ["summary.txt"]),
        ("新建 config.yaml 文件", ["config.yaml"]),
        ("create report.json", ["report.json"]),
        ("generate output.csv", ["output.csv"]),
    ])
    def test_extracts_expected_file_targets(self, goal: str, expected: list[str]) -> None:
        result = _extract_zh_file_targets(goal)
        for exp in expected:
            assert exp in result, (
                f"goal={goal!r} 应提取文件 {exp!r}，实际结果：{result}"
            )

    def test_no_extraction_without_extension(self) -> None:
        """无扩展名的字符串不被提取为文件目标（防误伤）。"""
        result = _extract_zh_file_targets("创建 output 文件夹")
        assert "output" not in result, "无扩展名不应被当作文件提取"


# ═══════════════════════════════════════════════════════
# 防过度提取红线：否定语境
# ═══════════════════════════════════════════════════════

class TestNegationContextRedLine:
    """否定语境的 X 绝不提取。"""

    @pytest.mark.parametrize("goal", [
        "购物清单和随手记不要动",
        "不要动 archive 文件夹",
        "别动 backup 目录",
        "保持不变 logs 文件夹",
        "don't touch shopping folder",
        "keep notes unchanged",
    ])
    def test_negation_context_not_extracted_dir(self, goal: str) -> None:
        """否定语境中的目录词不被提取。"""
        result = _extract_zh_dir_targets(goal)
        # 这些 goal 中的关键词都在否定语境后，不应提取任何目录
        assert result == [], (
            f"否定语境不应提取目录目标，goal={goal!r}，实际结果：{result}"
        )

    def test_mixed_goal_only_positive_extracted(self) -> None:
        """混合 goal：只提取肯定语境的目标，否定语境的跳过。"""
        goal = "把会议记录整理到 meetings 子文件夹，购物清单不要动"
        result = _extract_zh_dir_targets(goal)
        assert "meetings" in result, f"肯定语境 meetings 应被提取：{result}"
        # 购物清单后面没有目录词，不存在"购物清单"作为目录被提取的情况
        # 主要验证否定语境不污染结果
        assert len(result) >= 1

    def test_real_world_negation_isolation(self) -> None:
        """实测原话：购物清单随手记不要动，不被提取。"""
        goal = REAL_WORLD_GOAL
        dir_targets = _extract_zh_dir_targets(goal)
        # 不应含有"购物清单"或"随手记"作为目录目标
        assert "购物清单" not in dir_targets
        assert "随手记" not in dir_targets


# ═══════════════════════════════════════════════════════
# 防过度提取红线：模板占位符
# ═══════════════════════════════════════════════════════

class TestTemplatePlaceholderRedLine:
    """含模板占位符的目标字符串绝不字面断言。"""

    @pytest.mark.parametrize("placeholder_path", [
        "YYYY-MM-DD 会议记录.txt",
        "YYYY/MM/DD.log",
        "report_YYYY.csv",
        "file-*.json",
        "<filename>.txt",
        "{date}.md",
        "[任意名称].xml",
        "2024-01-01.txt",   # 含具体日期格式也视为模板
    ])
    def test_placeholder_path_is_invalid(self, placeholder_path: str) -> None:
        assert not _is_valid_artifact_path(placeholder_path), (
            f"模板占位符路径应判定为不合法：{placeholder_path!r}"
        )

    def test_real_filename_is_valid(self) -> None:
        """真实文件名应判定为合法。"""
        valid_names = ["meetings", "report.json", "data/output.csv", "my-file.txt"]
        for name in valid_names:
            assert _is_valid_artifact_path(name), f"合法路径被误判为不合法：{name!r}"

    def test_no_template_assertion_in_generate(self) -> None:
        """generate 对含模板 goal 不产出含 YYYY 的断言。"""
        goal = "文件名统一改成「YYYY-MM-DD 会议记录.txt」格式"
        strats = generate(goal, workspace_facts=WorkspaceFacts())
        bad = [
            s for s in strats
            if (s.target and "YYYY" in s.target)
            or (s.cmd and "YYYY" in s.cmd)
        ]
        assert not bad, f"不得对模板占位符字面断言：{bad}"


# ═══════════════════════════════════════════════════════
# 防过度提取红线：非法路径片段
# ═══════════════════════════════════════════════════════

class TestInvalidPathRedLine:
    """非法路径片段不被提取（无空格起止、无 ../）。"""

    @pytest.mark.parametrize("invalid_path", [
        "",
        " leading-space",
        "trailing-space ",
        "../parent-dir",
        "./current-dir",
    ])
    def test_invalid_path_rejected(self, invalid_path: str) -> None:
        assert not _is_valid_artifact_path(invalid_path), (
            f"非法路径应被拒绝：{invalid_path!r}"
        )

    @pytest.mark.parametrize("valid_path", [
        "meetings",
        "data/reports",
        "my-folder",
        "会议记录",
        "output_2024",
    ])
    def test_valid_path_accepted(self, valid_path: str) -> None:
        assert _is_valid_artifact_path(valid_path), (
            f"合法路径不应被拒绝：{valid_path!r}"
        )


# ═══════════════════════════════════════════════════════
# generate() 集成：目录 L2 策略属性验证
# ═══════════════════════════════════════════════════════

class TestGenerateDirL2Integration:
    """generate() 集成验证：目录类 L2 策略属性正确。"""

    def test_dir_strategy_uses_test_d(self) -> None:
        """目录断言 cmd 必须用 test -d，而非 test -f。"""
        goal = "把日志整理到 logs 文件夹"
        strats = generate(goal, workspace_facts=WorkspaceFacts())
        dir_strats = [
            s for s in strats
            if s.level == "L2" and s.kind == "artifact_exists" and s.target == "logs"
        ]
        assert dir_strats, f"应有 logs 目录断言：{strats}"
        assert all(s.cmd == "test -d logs" for s in dir_strats), (
            f"目录断言必须用 test -d：{dir_strats}"
        )

    def test_dir_strategy_confidence(self) -> None:
        """目录断言 confidence 应为 0.75。"""
        goal = "把文件归档到 archive 目录"
        strats = generate(goal, workspace_facts=WorkspaceFacts())
        dir_strats = [
            s for s in strats
            if s.level == "L2" and s.target == "archive"
        ]
        assert dir_strats
        assert all(s.confidence == 0.75 for s in dir_strats)

    def test_dir_l2_before_l5(self) -> None:
        """L2 目录策略必须在 L5 之前。"""
        goal = "整理到 output 目录"
        strats = generate(goal, workspace_facts=WorkspaceFacts())
        levels = [s.level for s in strats]
        if "L2" in levels:
            assert levels.index("L2") < levels.index("L5")

    def test_dir_and_file_both_extracted(self) -> None:
        """同一 goal 中同时含目录和文件目标 → 两者都被提取。"""
        goal = "整理到 meetings 文件夹，生成 summary.json"
        strats = generate(goal, workspace_facts=WorkspaceFacts())
        targets = [s.target for s in strats if s.target]
        assert "meetings" in targets, f"meetings 目录应被提取：{targets}"
        assert "summary.json" in targets, f"summary.json 文件应被提取：{targets}"


# ═══════════════════════════════════════════════════════
# 既有红线不受影响（回归护栏）
# ═══════════════════════════════════════════════════════

class TestExistingRedLinesUnaffected:
    """新增功能不破坏既有发送类红线和 fallback 非空保证。"""

    def test_send_goal_with_zh_dir_keyword_still_l5_only(self) -> None:
        """发送类 goal 即使含「整理到」也只返回 L5（纯发送+无代码信号）。"""
        goal = "发送整理到 inbox 文件夹的文件给所有用户"
        strats = generate(goal, workspace_facts=WorkspaceFacts())
        # 含「发送」且无代码信号 → 红线触发 → 只有 L5
        assert strats[0].level == "L5"
        assert len(strats) == 1

    def test_fallback_always_present_with_zh_goal(self) -> None:
        """中文 goal 也必须含 L5 兜底。"""
        goals = [
            "整理到 meetings 子文件夹",
            "把图片移动到 photos 目录",
            "创建 output 文件夹",
            "",
        ]
        for goal in goals:
            strats = generate(goal, workspace_facts=WorkspaceFacts())
            assert strats[-1].level == "L5", f"末位必须是 L5：{goal!r} → {strats}"

    def test_no_duplicate_dir_strategies(self) -> None:
        """目录策略不重复。"""
        goal = "整理到 meetings 子文件夹，会议记录整理到 meetings 目录"
        strats = generate(goal, workspace_facts=WorkspaceFacts())
        dir_meetings = [
            s for s in strats
            if s.target == "meetings" and s.cmd == "test -d meetings"
        ]
        assert len(dir_meetings) == 1, f"meetings 目录断言应去重，实际 {len(dir_meetings)} 条"
