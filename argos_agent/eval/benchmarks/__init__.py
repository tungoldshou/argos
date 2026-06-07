"""公开 benchmark 适配器(为 EvalRunner 接外部任务格式)。

子模块:
  terminal_bench:把 Terminal-Bench 的 task.yaml + run-tests.sh + Dockerfile
    转成 EvalTask(走本仓 EvalRunner);不嵌套 TB 的 Docker harness(诚实边界)。

设计原则:
  · 复用 corpus.EvalTask / runner.EvalRunner / results.append / compare —— 不另起评估体系
  · 强依赖容器/Docker 的任务被标 "unsupported",如实跳过(不进 pass / fail 计数)
  · verify_cmd 走 host(沿用 runner.D12:eval 是 dogfooding,不嵌套 sandbox)
"""
