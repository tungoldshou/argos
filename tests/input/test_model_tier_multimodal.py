"""Internal documentation."""
from __future__ import annotations


def _make_tier(**kwargs):
    from argos.core.models import ModelTier
    defaults = dict(name="default", model="test", base_url="https://x", max_tokens=1024)
    defaults.update(kwargs)
    return ModelTier(**defaults)


def test_model_tier_multimodal_defaults_none():
    """Internal documentation."""
    tier = _make_tier()
    assert tier.multimodal is None


def test_model_tier_multimodal_explicit_false_is_override():
    """Internal documentation."""
    tier = _make_tier(multimodal=False)
    assert tier.multimodal is False


def test_model_tier_multimodal_can_be_set_true():
    """Internal documentation."""
    tier = _make_tier(multimodal=True)
    assert tier.multimodal is True


def test_model_tier_is_frozen_with_multimodal():
    """Internal documentation."""
    import pytest
    tier = _make_tier(multimodal=False)
    with pytest.raises((AttributeError, TypeError)):
        tier.multimodal = True  # type: ignore[misc]
