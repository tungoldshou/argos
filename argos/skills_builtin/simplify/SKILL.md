---
name: simplify
description: 代码重复 / 复杂度 / 死代码扫描 — 重构前先扫
trust: builtin
enabled: true
---

# /simplify — 重构前的体检

## 何时用
- 重构前先扫(避免拆出新坑)
- 接手老代码摸底(找重复块 / 复杂函数 / 死代码)
- 提交前复扫(避免 PR 引入冗余)

## 3 pass
1. **Pass 1 duplicate** — token shingle(20 token) + blake2b 哈希;**3+ 命中**同一哈希即报
2. **Pass 2 complexity** — 函数体分支计数(`if`/`for`/`while`/`try`/`case`/`&&`/`||` 等);**> 15 分支** = warning
3. **Pass 3 dead code** — 未使用的公共函数(> 1 行 body + 无 `__all__` 标记 + 无 docstring)= info

## 白名单
- **跳过不扫**:`tests/**`(测试 fixture 多含故意重复/复杂/未用代码)
- **`docs/**` / `**/migrations/**`**(生成代码不算"死")

## top-N 截断
- 默认 `top=10`,`/simplify top=20` 改上限(spec §2.5 D6)

## 不做什么
- 不**自动重构**(只报,改由你拍板)
- 不**删**死代码(只标记)
