"""self-test 子包 —— 任务:无 verify_cmd 时(系统默认 unverifiable),用 reviewer 角色
+ canary 守卫生成一个候选测试,试图把一部分 unverifiable 变成可验证。

诚实铁律(模块顶部 hard rule,绝不松):
  · 自验证结果【不】与用户级 verify 的 passed 混为一谈 —— Verdict.self_verified 字段
    单独标,UI/report/统计必须按它区分"强 / 弱"。
  · 自造测试**必须能失败**(canary:在空 workspace 跑得不出 0,才视为真测试;
    在空 workspace 仍出 0 → 废测试 → 直接丢弃,回退 unverifiable)。
  · 生成的命令仍走白名单(ALLOWED_CMDS)+ detect_tampering —— 与用户 verify 同一道闸。
  · 写代码的 agent 不得为自己造测试(架构上保证:Verifier 在写完后被调用,生成走
    独立 reviewer prompt,无 in-process 通道让 writer 影响)。
  · 默认关闭(opt-in):feature flag `ARGOS_SELF_TEST` 或 settings;不开时这条
    完全空跑,verifier 行为与之前 100% 一致。
"""
