"""autonomy 配置加载 + AutonomyPolicy 派生(任务:复用 permissions/config.py 的加载方式)。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos_agent.permissions.autonomy import AutonomyPolicy
from argos_agent.permissions.config import (
    PermissionsConfig, _reset_config, load, reload_config,
)


def test_permissions_config_empty_has_empty_preauth():
    """PermissionsConfig.empty() 默认 preauth={}(D20 锁:无文件 → 空配置)。"""
    c = PermissionsConfig.empty()
    assert c.preauth == {}


def test_load_preauth_from_json(tmp_path: Path):
    """permissions.json 含 preauth 节点 → PermissionsConfig.preauth 正确加载。"""
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
    """permissions.json preauth 含非 bool 值 → 跳过 + log warning,整体加载不破。"""
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({
        "version": 1,
        "preauth": {
            "soft_ask:git push": True,
            "soft_ask:deploy": "yes",  # 非 bool,应被跳过
            "valid_but_int_key": 123,  # 非 str key,应被跳过
        },
    }), encoding="utf-8")
    cfg = load(p)
    # 只有合法的 bool 值进入
    assert cfg.preauth == {"soft_ask:git push": True}


def test_load_preauth_missing_defaults_to_empty(tmp_path: Path):
    """permissions.json 没 preauth 节点 → 默认为空 dict(向后兼容)。"""
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({"version": 1}), encoding="utf-8")
    cfg = load(p)
    assert cfg.preauth == {}


def test_autonomy_policy_from_permissions_config():
    """AutonomyPolicy.from_permissions_config 透传 preauth。"""
    cfg = PermissionsConfig(
        version=1,
        preauth={"soft_ask:git push": True},
    )
    p = AutonomyPolicy.from_permissions_config(cfg)
    assert p.preauth == {"soft_ask:git push": True}
    assert p.clarification_required is True  # 默认
    assert len(p.slow_actions) > 0  # 默认有 slow_actions


def test_autonomy_policy_from_none_config():
    """None config → 默认 AutonomyPolicy(不破)。"""
    p = AutonomyPolicy.from_permissions_config(None)
    assert p.preauth == {}
    assert p.clarification_required is True
