---
name: verify
description: 用户中途一键复跑 verify_cmd(防 agent 假绿,user-driven 不走 propose_verify)
trust: builtin
enabled: true
---

# /verify — 显式复核 verify 门

## 何时用
- agent 报"已 verify"但你想再跑一次(防假绿)
- 改了一行配置 / 装新依赖后想复跑测试
- 跨 stage 复核(plan → act → verify 间的非自动验)

## 调用
- `/verify` —— 用 config 全局 verify_cmd
- `/verify src/foo.py` —— 显式 path(spec v1.1 支持,本期 v1 仅记录)

## 与 propose_verify 的区别
| 维度 | propose_verify | /verify |
|---|---|---|
| 触发 | agent(从 code block) | **用户**(从 TUI) |
| 入口 | propose_verify 解析 | **直接** Verifier.verify |
| cmd 来源 | agent 声明 | config 全局 |

## 不做什么
- 不**自动 fix**(本 skill 只跑 verify,不写文件)
- 不**改 verify_cmd**(改 ~/.argos/config.json 走外部)
