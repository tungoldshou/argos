"""Internal documentation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos.permissions.autonomy import AutonomyPolicy
from argos.permissions.config import (
    PermissionsConfig, _reset_config, load, reload_config,
)


def test_permissions_config_empty_has_empty_preauth():
    """Internal documentation."""
    c = PermissionsConfig.empty()
    assert c.preauth == {}


def test_load_preauth_from_json(tmp_path: Path):
    """Internal documentation."""
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({
        "version": 1,
        "preauth": {
            "soft_ask:git push": True,
            "soft_ask:git tag": True,
        },
    }), encoding="utf-8")
    cfg = load(p)
    assert cfg.preauth == {
        "soft_ask:git push": True,
        "soft_ask:git tag": True,
    }


def test_load_preauth_invalid_value_skipped(tmp_path: Path):
    """Internal documentation."""
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({
        "version": 1,
        "preauth": {
            "soft_ask:git push": True,
            "soft_ask:deploy": "yes",
            "valid_but_int_key": 123,
        },
    }), encoding="utf-8")
    cfg = load(p)
    assert cfg.preauth == {"soft_ask:git push": True}


def test_load_preauth_missing_defaults_to_empty(tmp_path: Path):
    """Internal documentation."""
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({"version": 1}), encoding="utf-8")
    cfg = load(p)
    assert cfg.preauth == {}


def test_autonomy_policy_from_permissions_config():
    """Internal documentation."""
    cfg = PermissionsConfig(
        version=1,
        preauth={"soft_ask:git push": True},
    )
    p = AutonomyPolicy.from_permissions_config(cfg)
    assert p.preauth == {"soft_ask:git push": True}
    assert p.clarification_required is True
    assert len(p.slow_actions) > 0


def test_autonomy_policy_from_none_config():
    """Internal documentation."""
    p = AutonomyPolicy.from_permissions_config(None)
    assert p.preauth == {}
    assert p.clarification_required is True
