"""DATA cluster 文案 —— memory / routing / context / skills_curator / skills_runtime / skills。

key 命名空间:mem.* / route.* / ctx.* / skill.*。
ZH 值与重构前原始中文串逐字一致,ARGOS_LANG=zh 下旧测试断言不破。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── ctx: context/prune.py ────────────────────────────────────────────────
    "ctx.stub_tool": "[pruned: stale tool output]",
    "ctx.stub_plan": "[pruned: superseded plan]",
    "ctx.stub_dead": "[pruned: dead-end exploration]",
    # ── mem: memory/store.py ──────────────────────────────────────────────────
    "mem.summary_prefix": "(early conversation summary)",
    "mem.recall_hit_sim": "goal similarity {sim:.2f}",
    "mem.recall_hit_model": "model {model}",
    "mem.recall_hit_prefix": "hit: ",
    "mem.recall_hit_fallback": "hit: embedding unavailable, falling back to literal match (goal contains query)",
    # ── mem: memory/auto.py ───────────────────────────────────────────────────
    "mem.empty": "  (empty)",
    # ── route: routing/config.py ──────────────────────────────────────────────
    "route.not_valid_json": "not valid JSON",
    "route.config_parse_fail": "config.json parse failed: {detail}",
    "route.tier_must_be_str": "routing.{key} tier value must be str, got {type_name}",
    "route.tier_force_confirm_must_be_str": "routing.tier_force_confirm entries must be str",
    "route.category_key_invalid": "routing.by_category key {key!r} not in valid categories {valid} ",
    "route.tier_not_in_models": "routing tier '{tier}' not in config.models {models} (typo guard)",
    "route.no_config_set_category": "no {path}, cannot set_category",
    # ── route: routing/router.py ──────────────────────────────────────────────
    "route.factory_returned_none": "profile '{tier}' factory returned None, cannot construct ModelClient",
    # ── skill: skills_curator/recommend.py ────────────────────────────────────
    "skill.recommend_py_files": "edited {count} .py file(s)",
    "skill.recommend_test_files": "edited {count} test file(s)",
    "skill.recommend_verify_fail": "verify failed {count} time(s)",
    "skill.recommend_verify_fail_3plus": "verify failed 3+ times consecutively",
    "skill.recommend_ts_files": "edited {count} TS file(s)",
    "skill.recommend_sql_files": "edited {count} .sql file(s)",
    "skill.recommend_git_commit": "ran git commit",
    "skill.recommend_web_search": "used web_search",
    "skill.recommend_security_review": "used /security-review",
    "skill.recommend_many_suffixes": "project uses {count} different extensions",
    "skill.recommend_debug_pattern": "debugging (failures + many edits)",
    "skill.recommend_long_session": "long session, check for dead code",
    # ── skill: skills_curator/install.py ──────────────────────────────────────
    "skill.install_network_confirm_required": "network_capability_requires_confirmation: {name!r} declares network traffic",
    # ── skill: skills_runtime/analysis.py ────────────────────────────────────
    "skill.finding_severity_invalid": "Finding.severity must be one of {valid}, got {value!r}",
    "skill.finding_snippet_too_long": "Finding.snippet length {length} > 120 (token explosion guard)",
    "skill.result_verdict_invalid": "AnalysisSkillResult.verdict must be one of {valid}, got {value!r}",
    "skill.result_duration_negative": "duration_ms must not be negative, got {value}",
    "skill.name_invalid": "AnalysisSkill.name {name!r} invalid: only ASCII alphanumeric + _ + - allowed",
    # ── skill: skills_runtime/__init__.py ────────────────────────────────────
    "skill.builtin_verify_desc": "explicitly run verify_cmd (D9/D13 — bypasses propose_verify)",
    "skill.builtin_security_review_desc": "3-pass security audit (secrets + deps + permissions)",
    "skill.builtin_simplify_desc": "3-pass duplicate/complexity/dead-code scan",
    # ── skill: skills_runtime/runner.py ──────────────────────────────────────
    "skill.arg_timeout_invalid": "invalid args: timeout {value!r} must be in range 1-600",
    "skill.arg_top_invalid": "invalid args: top {value!r} must be in range 1-100",
}

ZH: dict[str, str] = {
    # ── ctx: context/prune.py ────────────────────────────────────────────────
    "ctx.stub_tool": "[已修剪:过期工具输出]",
    "ctx.stub_plan": "[已修剪:被取代的旧计划]",
    "ctx.stub_dead": "[已修剪:走死路的探索]",
    # ── mem: memory/store.py ──────────────────────────────────────────────────
    "mem.summary_prefix": "(早期对话摘要)",
    "mem.recall_hit_sim": "goal 相似 {sim:.2f}",
    "mem.recall_hit_model": "模型 {model}",
    "mem.recall_hit_prefix": "命中：",
    "mem.recall_hit_fallback": "命中：embedding 不可用,降级字面匹配（goal 含查询串）",
    # ── mem: memory/auto.py ───────────────────────────────────────────────────
    "mem.empty": "  (空)",
    # ── route: routing/config.py ──────────────────────────────────────────────
    "route.not_valid_json": "不是合法 JSON",
    "route.config_parse_fail": "config.json 解析失败:{detail}",
    "route.tier_must_be_str": "routing.{key} 的 tier 值必须是 str,得 {type_name}",
    "route.tier_force_confirm_must_be_str": "routing.tier_force_confirm 项必须是 str",
    "route.category_key_invalid": "routing.by_category 的键 {key!r} 不在合法类别 {valid} 内",
    "route.tier_not_in_models": "routing tier '{tier}' 不在 config.models {models} 内(防拼写退化)",
    "route.no_config_set_category": "无 {path},无法 set_category",
    # ── route: routing/router.py ──────────────────────────────────────────────
    "route.factory_returned_none": "profile '{tier}' 工厂返 None,无法构造 ModelClient",
    # ── skill: skills_curator/recommend.py ────────────────────────────────────
    "skill.recommend_py_files": "编辑 {count} 个 .py 文件",
    "skill.recommend_test_files": "编辑 {count} 个 test 文件",
    "skill.recommend_verify_fail": "verify 失败 {count} 次",
    "skill.recommend_verify_fail_3plus": "verify 连续失败",
    "skill.recommend_ts_files": "编辑 {count} 个 TS 文件",
    "skill.recommend_sql_files": "编辑 {count} 个 .sql 文件",
    "skill.recommend_git_commit": "跑过 git commit",
    "skill.recommend_web_search": "用过 web_search",
    "skill.recommend_security_review": "已用 /security-review",
    "skill.recommend_many_suffixes": "项目扩展 {count} 种后缀",
    "skill.recommend_debug_pattern": "调试中(失败 + 多 edit)",
    "skill.recommend_long_session": "长 session,扫下死代码",
    # ── skill: skills_curator/install.py ──────────────────────────────────────
    "skill.install_network_confirm_required": "network_capability_requires_confirmation: {name!r} 声明会发网络流量",
    # ── skill: skills_runtime/analysis.py ────────────────────────────────────
    "skill.finding_severity_invalid": "Finding.severity 必须是 {valid} 之一,收到 {value!r}",
    "skill.finding_snippet_too_long": "Finding.snippet 长度 {length} > 120(防 token 暴)",
    "skill.result_verdict_invalid": "AnalysisSkillResult.verdict 必须是 {valid} 之一,收到 {value!r}",
    "skill.result_duration_negative": "duration_ms 不能为负,收到 {value}",
    "skill.name_invalid": "AnalysisSkill.name {name!r} 非法:仅允许 ASCII 字母数字 + _ + -",
    # ── skill: skills_runtime/__init__.py ────────────────────────────────────
    "skill.builtin_verify_desc": "显式跑 verify_cmd(D9/D13 — 不走 propose_verify)",
    "skill.builtin_security_review_desc": "3-pass 安全审计(secrets + deps + permissions)",
    "skill.builtin_simplify_desc": "3-pass 重复/复杂度/死代码扫描",
    # ── skill: skills_runtime/runner.py ──────────────────────────────────────
    "skill.arg_timeout_invalid": "invalid args: timeout {value!r} 必须在 1-600",
    "skill.arg_top_invalid": "invalid args: top {value!r} 必须在 1-100",
}
