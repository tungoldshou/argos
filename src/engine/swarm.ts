// swarm.ts — Argos 的核心:契约约束下的多 agent 蜂群编排。
//
// 已用本地 MiniMax-M2.7 验证(scripts/swarm-ab-minimax.py):
//   裸蜂群 8 冲突 → 模型自由契约 6 → 工程化契约模板 0。
// 边界(scripts/swarm-domain2.py 验证):契约层只对「结构化工程任务」有效
//   (API/schema/配置/接口/迁移),对开放式内容生成(写作/分析)无效甚至有害。
// 因此本引擎只面向结构化任务,UI 应明确这一边界。
//
// 流程:目标 → 契约冻结(按完整模板填空)→ 并行蜂群(契约约束)→ 交叉验证(数硬冲突)。
// 通过 hermes 桥调任意厂家模型,实现 model-agnostic。

import type { ChatFn } from '../lib/llm';
import { contractFor, detectGaps, domainOf, dynamicFreezePrompt, gapFillPrompt, requiredItems, type Domain } from './contracts';

/** 一个子任务:蜂群里一个 agent 负责的独立工作单元。 */
export interface Subtask {
  id: string;
  task: string;
}

/** 一个 worker 的产出。 */
export interface WorkerOutput {
  id: string;
  task: string;
  output: string;
}

/** 交叉验证的结论。 */
export interface Verdict {
  conflicts: string[];
  conflictCount: number;
  /** 拼起来是否可直接组装(无硬冲突且解析可信) */
  assemblable: boolean;
  /**
   * 这次判决的【解析】是否可信。fail-closed 的核心:
   * judge 没给出权威计数行(跑题/截断/客套)、或计数与收集到的冲突自相矛盾时为 false。
   * 不可信 ≠ 通过 —— 卖可靠性的产品,测谎仪读不懂判决时绝不能默默判无罪,
   * 应交给 escalation 让人类裁决,而不是亮假绿灯。
   */
  parseTrusted: boolean;
}

/** 一轮「judge 定点修复」的记录:判决 → 针对冲突点修复 → 修复后的产出。 */
export interface ResolveRound {
  /** 第几轮(从 1 开始) */
  round: number;
  /** 本轮修复前的判决(暴露了哪些冲突) */
  verdict: Verdict;
  /** 针对冲突点修复后的产出(下一轮 judge 的输入) */
  repaired: WorkerOutput[];
}

/** 一次完整蜂群运行的全过程,供可视化逐阶段呈现。 */
export interface SwarmRun {
  goal: string;
  domain: Domain;
  contract: string;
  subtasks: Subtask[];
  /** 自检前的原始 worker 产出 */
  workers: WorkerOutput[];
  /** 合规自检 + self-repair 后的产出(无契约时 = workers) */
  checked: WorkerOutput[];
  /**
   * judge 定点修复的回合记录(可能为空 = 首次 judge 即清零)。
   * 每轮把上一轮 judge 找出的具体冲突点回给 worker 定向修复,再重新 judge,
   * 直到清零或达到 maxRounds。这是「多 agent 相互验证 + 自动修复闭环」——
   * 调研确认 0 商用竞品(9/10 真空)的核心护城河。
   */
  rounds: ResolveRound[];
  /** 最终判决(经过修复回合后的最后一次) */
  verdict: Verdict;
}

/** 蜂群运行的阶段回调,驱动可视化。 */
export interface SwarmHooks {
  onDomain?: (domain: Domain, label: string) => void;
  /** Pass A 动态扩展完成、Pass B 漏项回填发生时的可视化反馈。 */
  onFreezeProgress?: (info: FreezeInfo) => void;
  onContract?: (contract: string) => void;
  onPlan?: (subtasks: Subtask[]) => void;
  onWorkerStart?: (id: string) => void;
  onWorkerDone?: (w: WorkerOutput) => void;
  /** worker 合规自检阶段开始/某 worker 完成自检。 */
  onCheckStart?: () => void;
  onWorkerChecked?: (w: WorkerOutput) => void;
  onVerdict?: (v: Verdict) => void;
  /** 一轮定点修复开始:本轮要解决的冲突判决。供「冲突→修复」可视化。 */
  onResolveStart?: (round: number, verdict: Verdict) => void;
  /** 一轮定点修复完成。 */
  onResolveRound?: (r: ResolveRound) => void;
}

/** 混合冻结的过程信息:覆盖了几条必检骨架、动态加了几条专属、回填了哪些缺项。 */
export interface FreezeInfo {
  /** 骨架必检项总数 */
  required: number;
  /** Pass A 后已覆盖的必检项数 */
  covered: number;
  /** 模型动态新增的目标专属条目数(X 编号) */
  dynamic: number;
  /** 触发回填的缺失项 ID(空数组 = 一次过,无需回填) */
  refilled: string[];
}

// ──────────────────────────────────────────────────────────────────────────
// 契约模板:已验证能让傻模型把结构化任务的冲突清零的「填空题」。
// 这是产品的核心资产 —— 覆盖越全,越多便宜模型能产出可组装结果。
// 关键的 [C10] 强制「端点-数据模型对齐自检」是 0 冲突的决定性条款。
// ──────────────────────────────────────────────────────────────────────────
export const CONTRACT_TEMPLATE = `你必须按下面这份契约模板逐条填写,每一项都不许留空、不许自由发挥、不许新增模板外的概念。填完后这份契约对所有子任务 agent 强制生效。

[C1] 主键: id, 类型与格式 = ____ (如 string/UUIDv4)
[C2] JSON 字段命名风格 = ____ (snake_case 或 camelCase,全局统一)
[C3] 时间字段命名与格式 = ____ (字段名、类型、时区必须明确,如 created_at/updated_at, ISO8601, UTC 带 Z)
[C4] 状态/完成标志的唯一真相来源: 在「枚举字段」与「布尔字段」之间【只选一个】,另一个禁止出现。选定 = ____
[C5] 上一条选定的字段: 数据模型必须持久化它; 若为枚举,完整列出取值且所有写端点必须接受
[C6] 并发控制令牌: 字段名 = ____,【数据模型必须持久化、写操作必须校验】,缺失/冲突时状态码 = ____
[C7] 统一响应封装: 单条 = ____,列表 = ____ (含状态/错误码字段,封装字段不进持久层)
[C8] 错误格式 = ____ (统一一种,含数字 code 与 message)
[C9] 字段长度上限: 各关键字段上限 = ____,超长时状态码 = ____
[C10] 接口-数据模型对齐自检: 列出每个端点的请求字段集与响应字段集,以及数据模型字段集; 确认「数据模型的每个字段都在某端点可达」且「每个端点需要的字段数据模型都能提供」,无悬空。

只输出填满后的契约,每条一行,不容歧义。`;

// 注:本地 Hermes 跑在 server_agent 模式,会忽略 max_tokens、倾向长篇发挥
// (实测一个子任务可吐 2937 token / 45s)。蜂群要的是 load-bearing 的结构化要点,不是散文。
// 所以每个阶段都在 system 里下硬性简洁约束 —— 实测可把单次调用从 45s 压到个位数秒,
// 且不损失「契约对齐」所需的字段/类型/约束信息(那本就该是要点而非长文)。
const TERSE = '只输出结构化要点,每条一行、尽量短;禁止散文、禁止复述题目、禁止解释推理过程、禁止客套与总结段。';
// 注意:规划阶段【不能】套用 TERSE 的极简约束 —— 蜂群必须拆出至少 2 个子任务才有交叉验证的意义
// (实测过度压缩会让模型只回 1 行 → 蜂群退化成单 agent,judge 无从比对)。这里强制 2-4 个。
const PLAN_SYSTEM =
  '你是蜂群的规划 agent。必须把目标拆成【2 到 4 个】可并行、互相独立的结构化子任务' +
  '(每个能由一个互不通信的 agent 单独完成;少于 2 个就失去蜂群意义)。' +
  '只输出子任务列表,每行一个、不要编号前缀和解释;至少 2 行。';

const WORKER_SYSTEM =
  '你是蜂群里的执行 agent,只负责一个子任务,看不到其他 agent 的工作。' +
  `产出用「名:值」式要点逐行列出(字段/类型/约束/状态码等)。${TERSE}`;

const JUDGE_SYSTEM =
  '你是交叉验证 agent。只数「真冲突」:两个 agent 对同一项各自给出了不同的具体值。' +
  '一方未提及/未复述另一方写的内容,是分工沉默,绝不算冲突。不做润色建议。' +
  '只逐条列出真冲突、最后一行给「硬冲突数: N」,不要解释推理、不要复述各 agent 全文。';

const CHECK_SYSTEM =
  '你是严格的合规自检 agent,契约是唯一权威,你只负责让产出符合契约,不质疑契约。' +
  '只输出修正后的产出本身(结构化要点、逐行),不要解释改了什么、不要复述契约。';

/** worker 合规自检 prompt:拿契约逐条核对自己的产出,违反则以契约为权威改正。 */
function complianceCheckPrompt(contract: string, task: string, output: string): string {
  return (
    `这是必须遵守的共享契约:\n${contract}\n\n` +
    `你刚才负责的子任务:${task}\n\n你的产出:\n${output}\n\n` +
    '现在做合规自检:逐条对照契约,检查你的产出有没有任何一处【违反或偏离】契约的具体规定' +
    '(例如契约规定 deleted_at IS NULL 过滤已删除,你却写成 IS NOT NULL;契约规定某字段上限,' +
    '你却没限制或写了别的值;字段命名、状态码、并发令牌字段名与契约不一致等)。\n' +
    '凡发现违反,一律以【契约为唯一权威】改正,不许反过来质疑契约。\n' +
    '只输出修正后的完整产出(若本就完全合规,原样重述即可),不要解释改了什么。'
  );
}

/**
 * 从 LLM 文本里粗解析子任务列表。
 * 列表前缀(1. / - / * / [1])是【可选】的:剥掉它,剩下的非空行就是子任务。
 * 必须兼容纯文本行 —— 真模型在「不要编号前缀」约束下就只回纯文本行,若强制要求前缀会解析出 0 个、
 * 蜂群退化成空跑(2026-05-31 真模型实测教训)。
 */
export function parsePlan(text: string): Subtask[] {
  const tasks: Subtask[] = [];
  for (const raw of text.split('\n')) {
    // 剥掉可选的列表/编号前缀,纯文本行原样保留。
    const task = raw.trim().replace(/^(?:\[?\d+\]?[.)、]|[-*•])\s*/, '').trim();
    if (task.length > 4) tasks.push({ id: String(tasks.length + 1), task });
  }
  return tasks.slice(0, 4);
}

/**
 * 从交叉验证文本里抓「硬冲突数: N」,并把每条冲突拆出来。
 * 真实模型(MiniMax 级)输出带 markdown 装饰(**粗体**、-- 分隔线、标题行),
 * 所以解析前先剥装饰,再用一组规则把非冲突行(分隔线/标题/计数行/「无」)剔掉。
 */
export function parseVerdict(text: string): Verdict {
  const conflicts: string[] = [];
  for (const raw of text.split('\n')) {
    // 1) 去掉前导列表/标题标记(数字编号、- * # 以及成对 **),再剥成对加粗。
    let c = raw.trim()
      .replace(/^#{1,6}\s*/, '')                       // markdown 标题 ###
      .replace(/^(?:\[?\d+\]?[.)、]|[-*]+)\s*/, '')      // 列表前缀 1. / - / * / **
      .replace(/\*\*/g, '')                             // 成对加粗装饰
      .trim();
    if (!c) continue;
    // 2) 剔除非冲突行:纯分隔线、计数行、「无冲突」类结论、纯标题(以冒号结尾且无实质值)。
    if (/^[-=_*\s]+$/.test(c)) continue;                // -- 或 *** 分隔线
    if (/硬冲突数/.test(c)) continue;                    // 计数行
    if (/^(无|没有|none|n\/a)[。.\s]*$/i.test(c)) continue; // 「无」结论
    // 纯标题行:任何以冒号结尾、后面没有实质值的行都是标题/小节头(如「逐条检查:」「真冲突:」),
    // 不是冲突。真冲突一定是「名:值」式、冒号后有具体值。这条比白名单标题词更稳,
    // 避免漏网的标题行被当成幽灵冲突(否则计数=0+幽灵冲突会被 fail-closed 误判为自相矛盾)。
    if (/[:：]\s*$/.test(c)) continue;
    conflicts.push(c);
  }
  const m = text.match(/硬冲突数[:：]\s*\**\s*(\d+)/);
  // fail-closed:测谎仪读不懂判决时绝不判无罪。
  // 1) 没有权威计数行 → 解析不可信。哪怕没收集到冲突行也【不能】当 0 通过
  //    (judge 跑题/被 maxTokens 截断/只回客套都会走到这,旧 bug 正是这里静默判 assemblable=true)。
  if (!m) {
    return { conflicts, conflictCount: conflicts.length || -1, assemblable: false, parseTrusted: false };
  }
  const count = parseInt(m[1], 10);
  // 2) 计数=0 却收集到了冲突行 → judge 自相矛盾,绝不信这个 0。
  if (count === 0 && conflicts.length > 0) {
    return { conflicts, conflictCount: conflicts.length, assemblable: false, parseTrusted: false };
  }
  // 3) 自洽:有权威计数且与冲突行不矛盾,可信。
  return { conflicts, conflictCount: count, assemblable: count === 0, parseTrusted: true };
}

/** 数出契约里有几条目标专属扩展条目([X1]/[X2]…)。 */
function countDynamic(contract: string): number {
  const set = new Set<string>();
  for (const m of contract.matchAll(/\[X\d+\]/g)) set.add(m[0]);
  return set.size;
}

/**
 * 混合契约冻结(本产品的核心):
 *   Pass A — 模型按「固定骨架必检项 + 目标专属扩展」动态生成契约(DW 式自适应)。
 *   程序漏项检测 — 纯代码校验骨架必检 ID 是否齐全(不花 token)。
 *   Pass B — 若有缺项,把缺的 ID 甩回去强制回填一次(固定骨架兜底,保证不漏)。
 * 实测:纯 Pass A(模型自由)会漏项 → 6 冲突;加 Pass B 兜底 → 0。
 */
async function freezeContract(
  goal: string,
  domain: Domain,
  chat: ChatFn,
  onProgress?: (info: FreezeInfo) => void,
): Promise<string> {
  const required = requiredItems(domain);

  // Pass A:动态扩展
  let contract = await chat(dynamicFreezePrompt(domain, goal), { maxTokens: 1100 });

  // 漏项检测(纯程序)
  let { covered, missing } = detectGaps(domain, contract);
  onProgress?.({ required: required.length, covered: covered.length, dynamic: countDynamic(contract), refilled: [] });

  // Pass B:有缺项则强制回填一次
  const refilled = missing;
  if (missing.length) {
    contract = await chat(gapFillPrompt(domain, contract, missing), { maxTokens: 1100 });
    ({ covered, missing } = detectGaps(domain, contract));
    onProgress?.({ required: required.length, covered: covered.length, dynamic: countDynamic(contract), refilled });
  }

  return contract;
}

/**
 * 跑一次契约约束下的蜂群。chat 是注入的 LLM 调用(走 hermes 桥 → 任意模型)。
 * useContract=false 时退化为裸蜂群(用于 A/B 对照演示)。
 */
export async function runSwarm(
  goal: string,
  chat: ChatFn,
  hooks: SwarmHooks = {},
  useContract = true,
  /** judge 定点修复的最大回合数(硬上限,防无限循环 + token 失控)。默认 2。 */
  maxRounds = 2,
): Promise<SwarmRun> {
  // 0) 判定领域,选对应骨架(覆盖越多领域,护城河越深)
  //    传入 chat → LLM 语义分类(能识别「登录流程」这类无字面词的目标);失败自动退正则兜底。
  const domain = await domainOf(goal, chat);
  const spec = contractFor(domain);
  hooks.onDomain?.(domain, spec.label);

  // 1+2) 契约冻结与规划互不依赖(都只看 goal/domain),并行跑省一个串行长调用。
  //    契约冻结(Pass A 动态扩展→漏项检测→缺则 Pass B 回填):固定骨架保证不漏项(护城河),
  //    动态扩展提供 DW 式自适应。规划:把目标拆成 2-4 个可并行子任务。
  const contractP: Promise<string> = useContract
    ? freezeContract(goal, domain, chat, hooks.onFreezeProgress).then((c) => {
        hooks.onContract?.(c);
        return c;
      })
    : Promise.resolve('');
  const subtasksP: Promise<Subtask[]> = chat(`目标:${goal}\n只输出子任务列表,每行一个。`, {
    system: PLAN_SYSTEM,
    maxTokens: 500,
  }).then((planText: string) => {
    const s = parsePlan(planText);
    hooks.onPlan?.(s);
    return s;
  });
  const [contract, subtasks] = await Promise.all([contractP, subtasksP]);

  // 3) 并行蜂群(契约约束)
  const workerSys = useContract
    ? `${WORKER_SYSTEM}\n\n【必须严格遵守的共享契约,不得偏离】:\n${contract}`
    : WORKER_SYSTEM;
  const workers = await Promise.all(
    subtasks.map(async (st): Promise<WorkerOutput> => {
      hooks.onWorkerStart?.(st.id);
      const output = await chat(`子任务[${st.id}]:${st.task}`, { system: workerSys, maxTokens: 900 });
      const w = { id: st.id, task: st.task, output };
      hooks.onWorkerDone?.(w);
      return w;
    }),
  );

  // 3.5) worker 合规自检 + self-repair
  //   实测(swarm-hybrid-minimax.py):剩余真冲突全是「worker 没遵守已存在的契约条款」
  //   (软删除过滤写反、长度上限缺失)——执行层失败,不是契约缺失。让每个 worker 拿契约当
  //   唯一权威,自查并改正自己的产出,实测把硬冲突 6→0。这一步把执行层失败在拼装前修掉。
  let checked = workers;
  if (useContract) {
    hooks.onCheckStart?.();
    checked = await Promise.all(
      workers.map(async (w): Promise<WorkerOutput> => {
        const output = await chat(complianceCheckPrompt(contract, w.task, w.output), {
          system: CHECK_SYSTEM,
          maxTokens: 1100,
        });
        const cw = { id: w.id, task: w.task, output };
        hooks.onWorkerChecked?.(cw);
        return cw;
      }),
    );
  }

  // 4) 交叉验证(用自检后的产出)
  let current = checked;
  let verdict = await judgeOnce(goal, current, chat);
  hooks.onVerdict?.(verdict);

  // 5) judge 定点修复闭环(核心护城河:多 agent 相互验证 + 自动修复,0 商用竞品)。
  //    judge 找出的不是「契约缺失」(那在阶段 1 解决)而是「worker 仍给了互相矛盾的值」。
  //    把这些【具体冲突点】回给所有 worker 定向修复(不是笼统重跑),再重新 judge,
  //    直到清零或达 maxRounds。maxRounds 是硬上限:防无限循环 + token 失控
  //    (调研里某团队 11 天递归 loop 烧了 $47k —— 自动修复必须有终止条件)。
  //    防发散护栏(真模型实测必需):全员重写会引入新分歧,judge 出现 1→3 越修越多。
  //    所以每轮修完比较新旧冲突数,**未严格下降(>=)就判定这轮修坏了**:回退到上一轮的
  //    产出与判决,立即停止。这保证闭环单调改善或不动,绝不让自动修复把结果改差。
  const rounds: ResolveRound[] = [];
  let round = 1;
  while (useContract && !verdict.assemblable && round <= maxRounds) {
    hooks.onResolveStart?.(round, verdict);
    const prevVerdict = verdict;
    const repaired = await Promise.all(
      current.map(async (w): Promise<WorkerOutput> => {
        const output = await chat(
          resolveConflictsPrompt(contract, prevVerdict.conflicts, w.task, w.output),
          { system: CHECK_SYSTEM, maxTokens: 1100 },
        );
        return { id: w.id, task: w.task, output };
      }),
    );
    const newVerdict = await judgeOnce(goal, repaired, chat);

    // 非单调 → 回退:这轮修复没让冲突严格减少,丢弃它,保留上一轮的较优结果并停止。
    if (newVerdict.conflictCount >= prevVerdict.conflictCount) break;

    verdict = newVerdict;
    const r: ResolveRound = { round, verdict: prevVerdict, repaired };
    rounds.push(r);
    hooks.onResolveRound?.(r);
    hooks.onVerdict?.(verdict);
    current = repaired;
    round++;
  }

  return { goal, domain, contract, subtasks, workers, checked, rounds, verdict };
}

/**
 * 一次严格交叉验证。只数「真冲突」(两 agent 对同一项给出不同的具体值),不把「一方没复述」
 * 的 omission 当冲突。实测(swarm-hybrid-minimax.py):同一份契约,宽松 judge 报 7、严格 judge
 * 报 2,被砍掉的 5 条全是分工沉默造成的假阳性。omission 当冲突会让契约越详细越「冲突多」,误导。
 */
async function judgeOnce(goal: string, workers: WorkerOutput[], chat: ChatFn): Promise<Verdict> {
  const assembled = workers.map((w) => `### Agent${w.id}\n${w.output}`).join('\n\n');
  const judgeText = await chat(
    `原目标:${goal}\n\n以下是几个互不通信的 agent 的产出拼在一起:\n\n${assembled}\n\n` +
      '你只数【真冲突】,定义极严:**同一个字段/参数/状态码,两个 agent 各自明确给出了【不同的具体值】**' +
      '(如 A 写 title≤200、B 写 title≤255;A 用 snake_case、B 用 camelCase;A 完成标志叫 status、B 叫 is_done)。\n' +
      '以下一律不算冲突,禁止计入:① 某 agent 只是没提及/没复述另一个写的东西(分工不同的沉默 ≠ 冲突);' +
      '② 一方更详细一方更简略但不矛盾;③ 你推测「可能不一致」却拿不出两个明确且不同的值。\n' +
      '判定每条前先自问:「我能同时引用两个 agent 针对同一项给出的两个不同具体值吗?」不能 → 不是冲突。\n' +
      '逐条列出真冲突(注明两 agent 各自的值),若无则写「无」。最后一行精确输出「硬冲突数: N」(只用阿拉伯数字)。',
    { system: JUDGE_SYSTEM, maxTokens: 900 },
  );
  return parseVerdict(judgeText);
}

/** 定点修复 prompt:把 judge 找出的【具体冲突点】回给 worker,以契约为权威对齐,只改冲突处。 */
function resolveConflictsPrompt(
  contract: string,
  conflicts: string[],
  task: string,
  output: string,
): string {
  return (
    `这是必须遵守的共享契约(唯一权威):\n${contract}\n\n` +
    `交叉验证发现了这些跨 agent 冲突,你必须按以下冲突逐条对齐(以契约为准,契约没写到的取最严格/最明确的一方):\n` +
    `${conflicts.map((c, i) => `${i + 1}. ${c}`).join('\n')}\n\n` +
    `你负责的子任务:${task}\n\n你当前的产出:\n${output}\n\n` +
    `请只针对上述冲突点修正你的产出,使其与契约和其它 agent 对齐;无关部分保持不变。` +
    `只输出修正后的完整产出,不要解释改了什么。`
  );
}
