"""ModelTier.multimodal 能力位 TDD 验收(spec §5)。"""
from __future__ import annotations


def _make_tier(**kwargs):
    from argos.core.models import ModelTier
    defaults = dict(name="default", model="test", base_url="https://x", max_tokens=1024)
    defaults.update(kwargs)
    return ModelTier(**defaults)


def test_model_tier_multimodal_defaults_none():
    """ModelTier 不传 multimodal → 默认 None(未知 → 走探针检测,不再默认 False)。"""
    tier = _make_tier()
    assert tier.multimodal is None


def test_model_tier_multimodal_explicit_false_is_override():
    """ModelTier(multimodal=False) → 显式 override 保留(用户声明纯文本)。"""
    tier = _make_tier(multimodal=False)
    assert tier.multimodal is False


def test_model_tier_multimodal_can_be_set_true():
    """ModelTier(multimodal=True) → 能力位保留。"""
    tier = _make_tier(multimodal=True)
    assert tier.multimodal is True


def test_model_tier_is_frozen_with_multimodal():
    """ModelTier 仍是 frozen dataclass，multimodal 不可在线改。"""
    import pytest
    tier = _make_tier(multimodal=False)
    with pytest.raises((AttributeError, TypeError)):
        tier.multimodal = True  # type: ignore[misc]
