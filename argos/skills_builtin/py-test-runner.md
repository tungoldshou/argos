---
name: py-test-runner
description: 跑 pytest 单测、读 traceback 定位失败
trust: builtin
enabled: true
---

# py-test-runner

跑 pytest 时:
1. 先 `run_command("pytest -x")`(失败即停,定位首个红测试)
2. 读 traceback 最后一行,定位文件 + 行号 + 断言
3. 用 `read_file` 看上下文
4. **绝不**改测试让它过;改实现
