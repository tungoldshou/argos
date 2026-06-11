# Argos v6 — 完整产品设计（2026-06-11）

> 一句话:**一个目标进来,一个验证过的交付物出去——任何模型,最短壁钟时间,全程不撒谎。**
>
> 本文是 v6 总设计:把 v5 的「诚实超级智能体」与 Factory 转型（7 阶段）和 TUI v3 全面重设计
> 整合为一份统一蓝图。分层约定:产品论证见 `docs/argos-product-definition.md`(v5);
> Factory 流水线细节见 `docs/superpowers/plans/2026-06-11-argos-factory-roadmap.md`;
> 本文不重复两者,只做整合决策 + TUI v3 设计系统全文。

## 1. 产品身份

- **名字的含义**:Argos Panoptes,百眼巨人,永不全睡的看守者。产品即看守者——
  模型干活,Argos 的"百眼"盯着每一步:代码执行、验证三态、审批回执、篡改痕迹。
  这个神话身份是 v6 视觉与交互设计的统一母题(见 §5 TUI v3)。
- **三条不随模型强度缩水的卖点**(v5 实测结论,不变):
  1. 确定 100% 而非 67%(verify 硬门禁);
  2. 不撒谎(三态判决 + 诚实协议 + E4 自验证防火墙);
  3. 便宜模型的可及性(模型无关,Anthropic + OpenAI 双协议)。
- **边界(诚实标注)**:只对「结果可被机检验证的事」成立。开放创作/战略分析不承诺。

## 2. 不变量红线（任何阶段不得放松）

1. **三态判决**:`passed / failed / unverifiable`,完成判定只认退出码,不认模型文字。
2. **诚实协议**:不可验证就说 `unverifiable`;无测任务标 `NO_TEST`;绝不编造成功。
3. **E4 自验证防火墙**(2026-06-11 在途,本设计完整保留):`self_verified=True` 的
   "弱通过"绝不冒充用户级 verify——不触发 run_success 记忆、不触发技能蒸馏/晋升,
   TUI 必须用独立视觉态展示(🟡 弱通过 ≠ ✅ 强通过)。
4. **沙箱 broker 唯一通路**:一切副作用过 CapabilityBroker(egress + 审批 + HMAC 回执)。
5. **篡改可见**:agent 动了测试文件,run 结束显著警告。

## 3. 架构（v6 目标态 = v5 引擎 + Factory 流水线 + TUI v3）

```
单 Python 进程(Textual TUI v3)
 ├─ 呈现层:TUI v3「黑曜石之眼」设计系统(§5)——引擎所有诚实信号的可视化面
 ├─ 流水线层(Factory,P1→P7 渐进):goal → IntentCard → 契约 DAG → 接口先行并行
 │   子代理 → 修复梯子 → 集成验收 → 证据包   (细节见 factory-roadmap,不在此重复)
 ├─ 引擎层(现有,保留):framework-free CodeAct loop,四阶段不可跳
 │   plan → act → verify → report;15 工具;模型无关双协议
 └─ 防线层(现有,保留):verify 硬门禁 / 诚实协议 / Seatbelt 沙箱 / 审批闸 / 回执
横切:memory(4 层 JSONL + 向量召回) / context(水位 + 压缩) / learning(E4 防火墙下的
反思与蒸馏) / eval(自评估 harness) / daemon(可选长跑)
```

## 4. 复用决策表

| 资产 | 决策 | 理由 |
|---|---|---|
| `core/`(loop/verify_gate/honesty/harness) | **原样保留** | 护城河本体,P1 契约引擎在其上叠加 |
| `sandbox/` `permissions/` | **原样保留** | 不变量红线载体 |
| `workflow/` | **保留,P3 时并入产物 DAG** | roadmap 既定 |
| `routing/` | **保留,P5 时档位语义并入修复梯子** | roadmap 既定 |
| `daemon/` `memory/` `context/` `learning/` `eval/` | **原样保留** | E4 防火墙在途工作完整保留 |
| `tui/` v2(两栏+智能右栏+行内审批) | **信息架构保留,视觉层完全重做** | v2 的 IA 实测合理;但视觉执行(27 行 theme、无设计 token 体系、组件风格不统一)达不到"美观"标准 → TUI v3(§5) |
| `src/`(Tauri/React 死栈) | **不碰** | 既定死代码 |

## 5. TUI v3「黑曜石之眼」设计系统

完整设计系统全文见 **`2026-06-11-argos-tui-v3-design.md`**(同目录,986 行施工级 spec)。
设计过程:3 个独立设计方向(瞭望塔仪表/黑曜石极简/百眼签名)并行探索 → 3 镜头评审
(美学/Textual 可实现性/产品灵魂)→ 总设计师裁决综合。要点:

- **公式**:B 黑曜石视觉底盘(背景 4 层纵深 + 墨色 5 阶亮度阶梯 + 发丝线 2 档 + 单金强调 3 档)
  + C 百眼母题做签名(眼睛=状态机:◌未睁/◓等你/◔plan/◉act/❂verify/◕阅毕/◍格纹瞳)
  + A 瞭望塔仪表纪律做右栏(四列对齐网格 8·7·11·6、八分块水位、青色 cache sparkline)。
- **字形安全是地基**:全部眼系 glyph 经 unicodedata EAW 实测均为 Narrow;EAW=Ambiguous
  字符(◎⊙●○◐◑◇◆)与全部 emoji 处决;⚠︎ 必须带 VS15。根治 v2 的宽度对齐灾难。
- **诚实可视化升级**:VerdictBadge 四态四重冗余(glyph+色+标签+注解行),self_verified
  弱通过(E4 防火墙)获得专属格纹瞳 ◍ + 强制「未晋级」注解;新接 Compacted/Pruned 事件、
  上下文四桶、verify_cmd/attempts 明细、缓存命中 sparkline、记忆召回提示。
- **金橙分家**:chrome 注意力金(#D9A85C)与「真相不确定」橙(#FF9E64)色相拉开,
  YOLO 徽标改红(危险态非注意力态)——消灭 v2 强调色与 unverifiable 同色的隐患。

## 6. 开发模型分配策略（本次开发自身的资源纪律）

用户指令(2026-06-11):Fable 5 主循环只做编排与设计决策,重活下放。

| 角色 | 模型 | 用在哪 |
|---|---|---|
| 总设计师/编排 | Fable 5(主循环) | 设计决策、spec 撰写、工作流编排、最终综合 |
| 设计刀刃 | opus(子代理) | TUI 设计变体生成、设计评审、实现终审 |
| 主力实现 | sonnet(子代理) | 代码探索浓缩报告、组件实现、测试编写与修复 |
| 机械工 | haiku(子代理) | 清单/格式化/截图脚本/简单测试更新 |

规则:子代理一律**显式指定 model**(省略会继承 Fable);大文件由 sonnet 读后返回浓缩
报告,Fable 不亲读 >100 行文件。

## 7. 验收

- `uv run pytest` 全绿且覆盖率 ≥80%(全量门禁);
- `uv run argos --selftest` 通过;
- TUI v3 截图铁证(Textual SVG export)人眼可审;
- E4 防火墙在途测试(`tests/test_loop_self_verified.py` 等)不回退;
- 视觉断言类旧测试随 v3 更新,行为契约类断言不许动语义。
