# Context Rot 治理:持续相关性修剪 + 不可丢核心 + 高水位整体压缩

日期 2026-06-07。把上下文管理从"按百分比一锅端式压缩"升级成三层防线,从根上治
context rot(上下文堆脏后模型变笨/跑偏)。

## 问题

提前整体压缩(把阈值调到 30–40%)是**有损**的:它会把还要用的细节(报错、文件内容、
决定)总结没了,反而更糟。原实现只有"高水位整体压缩"(`compact_threshold` 默认 0.8)
一条路径——要么不压、要么一锅端。

## 三层防线

1. **不可丢核心(core-keep)**——永不被修剪/压缩掉:
   - 任务目标:`messages[0]`(本轮 goal);loop 压缩后用 `_anchor_core_messages` 重新钉回。
   - 硬约束:写在 goal 消息里,随 goal 一起保。
   - 当前 verify 命令:`AgentLoop._verify_cmd` 是**实例字段**,本就不入 `messages`,天然不丢。
   - 最近 N 轮对话:`CoreKeep.recent_turns`(默认 6)逐字保留。

2. **持续相关性修剪(prune)**——在触发整体压缩之前就一直做,优先于压缩:
   - `context/prune.py`,**纯函数、不依赖模型、不依赖 store**,作用在内存里要发给模型的
     `messages` 上。
   - 按稳定内容标记把消息分桶(延续 4 桶 analyzer 的"分桶"思路到逐条消息):
     工具输出 `[执行结果]/[执行完成/[执行异常]`、计划摘要 `[Argos 任务清单`。
   - 把中段低价值消息的**内容**折叠成短桩(`[已修剪:…]`),保留条数/顺序/角色交替不变
     (不破坏对话结构),核心原样保留。
   - `aggressiveness` 旋钮(`LoopConfig.prune_aggressiveness`,默认 0.5):
     0=不修剪;0<a<0.66=折叠过期工具输出;a>=0.66=另折叠被取代的旧计划/死路错误。

3. **整体压缩(compaction)= 高水位安全网**:
   - 阈值保持高位(`compact_threshold` 默认 0.8)。
   - `safe_compact_threshold`:`PRECOMPACT_FLOOR=0.5`,**绝不让整体压缩在 50% 以下触发**
     (0 仍表示"关闭主动压");防误配把它调成有损提前压。
   - 触发时保住核心 + 各子任务结果摘要(store 既有摘要 + loop 核心锚),丢可修剪部分。

## 压缩后的诚实兜底

- 一旦发生过压缩(记忆已有损),`AgentLoop._compacted=True`、`_reverified_since_compact=False`。
- 完成必过 verify 这条铁律不变(`run_verify_gate` 永远真跑 verify_cmd,以退出码为准);
  跑完置 `_reverified_since_compact=True`。
- passed-break 加 `honesty.trust_passed_after_compaction(compacted, reverified)` 防御:
  压缩后没真重验过就绝不认 passed。无 verify_cmd 的任务压缩后仍走三态 `unverifiable`
  (`未机检验证`),绝不假装 passed。

## 可观测

- 修剪发 `PrunedEvent`,整体压缩发既有 `CompactedEvent`;TUI 的 context 可视化都能看到。

## 约束(已遵守)

整体压缩阈值绝不下 50%;复用 `context/` 的 analyzer/分桶/tokens,不新建子系统;修剪纯
启发式可优雅降级;verify gate 只加防御不削弱;不破坏既有测试。
