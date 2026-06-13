---
name: security-review
description: 安全审计 — secrets 扫描 + 依赖漏洞 + 危险 API
trust: builtin
enabled: true
---

# /security-review — 提交前扫一遍

## 何时用
- 提交前最后一道(防泄漏 / 防注入)
- 接手新项目时扫底
- 改认证/网络代码后复扫

## 3 pass
1. **Pass 1 secrets** — 9 条 regex(AWS / GitHub / OpenAI / **Anthropic** / private key / .env / hardcoded pwd)
2. **Pass 2 deps** — lockfile detect + shell out to npm/pip/cargo audit(**D5 缺工具必报 error**)
3. **Pass 3 permissions** — Python + JS/TS 危险 API(os.system / shell=True / eval / exec / child_process / innerHTML)

## 白名单
- **跳过不扫**:`.env` / `.env.*` / `secrets.toml` / `*.pem` / `*.key`(user-controlled 秘密存储)
- **降级 info**:`tests/fixtures/**` / `docs/**` / `**/example*`
- 测试代码 `eval` / `exec` 在 tests/ 下也降 info

## 不做什么
- 不**自动装**审计工具(用户责任:pip install pip-audit)
- 不**修复** finding(只报)
