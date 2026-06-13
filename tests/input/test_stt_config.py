"""SttConfig + load_stt_config:读 config.json 的 stt 块,缺省让本地零配置可用。"""
import json
from argos_agent.input.stt_config import SttConfig, load_stt_config


def test_defaults_when_no_stt_block(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"models": {}, "active": "x"}))
    cfg = load_stt_config(config_dir=tmp_path)
    assert cfg.provider == "local"
    assert cfg.model == "base"
    assert cfg.api_key is None

def test_defaults_when_no_config_file(tmp_path):
    cfg = load_stt_config(config_dir=tmp_path)  # 文件都没有 → 全默认,不抛
    assert cfg.provider == "local"

def test_reads_local_block(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"stt": {"provider": "local", "model": "small"}}))
    cfg = load_stt_config(config_dir=tmp_path)
    assert cfg.provider == "local" and cfg.model == "small"

def test_reads_cloud_block_and_resolves_key(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"stt": {
        "provider": "cloud", "model": "whisper-1",
        "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_STT_KEY"}}))
    (tmp_path / ".env").write_text("OPENAI_STT_KEY=sk-test123\n")
    cfg = load_stt_config(config_dir=tmp_path)
    assert cfg.provider == "cloud"
    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.api_key == "sk-test123"
