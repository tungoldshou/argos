"""出厂默认路由映射测试(自主性 flip:routing 出厂激活,Task 5b.1)。"""
import json

import pytest

from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig, _BUILTIN_DEFAULT, load_routing
from argos.routing.resolver import resolve


def test_load_routing_no_config_is_active(tmp_path):
    """无 config.json → load_routing 返内置默认映射且 is_active() 为 True。"""
    cfg = load_routing(tmp_path)
    assert cfg.is_active() is True


def test_load_routing_no_routing_section_is_active(tmp_path):
    """config.json 有 models 段但无 routing 段 → 仍返内置默认映射,is_active() True。"""
    (tmp_path / "config.json").write_text(
        json.dumps({"active": "default", "models": {"default": {}}})
    )
    cfg = load_routing(tmp_path)
    assert cfg.is_active() is True


def test_builtin_default_simple_read_resolves_to_cheap():
    """SIMPLE_READ → cheap tier(内置默认映射)。"""
    decision = resolve(_BUILTIN_DEFAULT, category=TaskCategory.SIMPLE_READ, tool=None)
    assert decision.tier == "cheap"
    assert decision.source == "by_category"


def test_builtin_default_long_run_resolves_to_strong():
    """LONG_RUN → strong tier(内置默认映射)。"""
    decision = resolve(_BUILTIN_DEFAULT, category=TaskCategory.LONG_RUN, tool=None)
    assert decision.tier == "strong"
    assert decision.source == "by_category"


def test_builtin_default_refactor_resolves_to_strong():
    """REFACTOR → strong tier(内置默认映射)。"""
    decision = resolve(_BUILTIN_DEFAULT, category=TaskCategory.REFACTOR, tool=None)
    assert decision.tier == "strong"
    assert decision.source == "by_category"


def test_builtin_default_plan_resolves_to_cheap():
    """PLAN → cheap tier(内置默认映射)。"""
    decision = resolve(_BUILTIN_DEFAULT, category=TaskCategory.PLAN, tool=None)
    assert decision.tier == "cheap"


def test_builtin_default_file_edit_resolves_to_strong():
    """FILE_EDIT → strong tier(内置默认映射)。"""
    decision = resolve(_BUILTIN_DEFAULT, category=TaskCategory.FILE_EDIT, tool=None)
    assert decision.tier == "strong"


def test_single_tier_routing_no_error(tmp_path):
    """单 tier 配置:router factory 对不存在的 tier 回退到 active tier,不 crash。"""
    from argos.routing.router import ModelRouter
    from argos.core.models import ModelClient, ModelTier, CredentialPool

    def _factory(name: str) -> ModelClient:
        # 单 tier 场景:任何 name 都给同一个 client(模拟 app_factory fallback)
        tier = ModelTier(name="default", model="m", base_url="https://x", max_tokens=1000)
        return ModelClient(tier=tier, pool=CredentialPool(["k"]))

    router = ModelRouter(routing=_BUILTIN_DEFAULT, client_factory=_factory)

    # cheap / strong / file_edit 全都不 crash,都返 client
    client_r, dec_r = router.select(category=TaskCategory.SIMPLE_READ, tool=None)
    assert client_r is not None
    assert dec_r.tier == "cheap"

    client_s, dec_s = router.select(category=TaskCategory.REFACTOR, tool=None)
    assert client_s is not None
    assert dec_s.tier == "strong"
