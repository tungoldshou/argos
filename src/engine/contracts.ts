// contracts.ts — Argos 的核心资产:按领域组织的「契约模板填空题」。
//
// 已验证(MiniMax-M2.7):一份覆盖完整的契约模板能把结构化任务的蜂群冲突清零
// (REST API: 裸跑 8 → 模板 0)。每个领域的契约「会打架的约定」不同,所以一个
// 领域一份模板 —— 模板覆盖的领域越多,护城河越深。
//
// 边界(已验证):只对「结构化工程任务」有效(字段/类型/格式/枚举等形式约定),
// 对开放式内容生成(写作/分析)无效。domainOf() 不识别的目标走通用结构化模板。

import type { ChatFn } from '../lib/llm';

export type Domain = 'rest-api' | 'db-schema' | 'state-machine' | 'config' | 'generic';

export interface ContractSpec {
  domain: Domain;
  /** 给用户看的领域名 */
  label: string;
  /** 注入给「契约冻结 agent」的填空模板 */
  template: string;
}

const HEADER =
  '你必须按下面这份契约模板逐条填写,每一项都不许留空、不许自由发挥、不许新增模板外的概念。填完后这份契约对所有子任务 agent 强制生效。\n\n';
const FOOTER = '\n\n只输出填满后的契约,每条一行,不容歧义。';

// ──────────────────────────────────────────────────────────────────────────
// 混合策略:固定骨架(我们手写的「傻模型会漏什么」知识 = 护城河)作为「必检清单」,
// 模型在其上动态扩展目标专属条目。骨架不再是逐字填空的死模板,而是「必须覆盖的项」。
//   Pass A 动态扩展 → Pass B 漏项检测(程序校验必检 ID 是否齐全)→ 缺则强制回填。
// 实测依据:纯动态(模型自由写)漏项 → 6 冲突;固定兜底必检 → 0。混合两者兼得。
// ──────────────────────────────────────────────────────────────────────────

/** 骨架里每条以 [C1]/[D3]/[S2]… 开头,这些 ID 就是「必检项」。 */
function itemIds(body: string): string[] {
  const ids: string[] = [];
  for (const m of body.matchAll(/^\[([A-Z]\d+)\]/gm)) ids.push(m[1]);
  return ids;
}

/** 取某领域骨架的必检项 ID 列表(漏项检测器用它校验)。 */
export function requiredItems(domain: Domain): string[] {
  return itemIds(TEMPLATES[domain].body);
}

/**
 * Pass A —— 动态扩展 prompt。模型既要覆盖固定骨架的每条必检项(用原 ID),
 * 又要按目标新增专属条目(用 X1/X2… 编号),实现 DW 式自适应而不丢兜底。
 */
export function dynamicFreezePrompt(domain: Domain, goal: string): string {
  const t = TEMPLATES[domain];
  return (
    `目标:${goal}\n\n` +
    `这是一个「${t.label}」类的结构化工程任务。你要冻结一份共享契约,供多个互不通信的 agent 强制遵守。\n\n` +
    `第一部分【必检骨架 —— 每条都必须出现并填实,沿用原编号,不许留空、不许跳过】:\n` +
    `${t.body}\n\n` +
    `第二部分【目标专属扩展 —— 根据本目标的特点,新增骨架没覆盖但本任务会让多个 agent 打架的约定】,` +
    `用 X1、X2… 编号,每条同样不容歧义(例如本目标特有的实体关系、分页/排序约定、特殊字段语义等)。\n\n` +
    `只输出填满的契约,每条一行,格式「[编号] 内容」。`
  );
}

/**
 * Pass B —— 漏项回填 prompt。当程序检测到骨架必检项缺失时,把缺的 ID 连同骨架原文
 * 一起甩回去,强制补全(只补缺项,不重写已有)。
 */
export function gapFillPrompt(domain: Domain, prev: string, missing: string[]): string {
  const t = TEMPLATES[domain];
  return (
    `下面这份契约漏掉了必检骨架里的这些条目(绝对不能少):${missing.join('、')}。\n\n` +
    `骨架原文(对照补全缺失项):\n${t.body}\n\n` +
    `你已写的契约:\n${prev}\n\n` +
    `请输出【补全后的完整契约】,保留已有条目,把缺失的 ${missing.join('、')} 按骨架要求填实加进去。每条一行,「[编号] 内容」。`
  );
}

/** 漏项检测器:契约文本里出现了哪些必检 ID,缺了哪些。纯程序,不花 token。 */
export function detectGaps(domain: Domain, contract: string): { covered: string[]; missing: string[] } {
  const required = requiredItems(domain);
  const present = new Set<string>();
  for (const m of contract.matchAll(/\[([A-Z]\d+)\]/g)) present.add(m[1]);
  const covered = required.filter((id) => present.has(id));
  const missing = required.filter((id) => !present.has(id));
  return { covered, missing };
}

// REST API —— 已用 MiniMax 验证清零的模板。C10 的「接口-数据模型对齐自检」是关键。
const REST_API = `[C1] 主键: id, 类型与格式 = ____ (如 string/UUIDv4)
[C2] JSON 字段命名风格 = ____ (snake_case 或 camelCase,全局统一)
[C3] 时间字段命名与格式 = ____ (字段名、类型、时区必须明确,如 created_at/updated_at, ISO8601, UTC 带 Z)
[C4] 状态/完成标志的唯一真相来源: 在「枚举字段」与「布尔字段」之间【只选一个】,另一个禁止出现。选定 = ____
[C5] 上一条选定的字段: 数据模型必须持久化它; 若为枚举,完整列出取值且所有写端点必须接受
[C6] 并发控制令牌: 字段名 = ____,【数据模型必须持久化、写操作必须校验】,缺失/冲突时状态码 = ____
[C7] 统一响应封装: 单条 = ____,列表 = ____ (含状态/错误码字段,封装字段不进持久层)
[C8] 错误格式 = ____ (统一一种,含数字 code 与 message)
[C9] 字段长度上限: 各关键字段上限 = ____,超长时状态码 = ____
[C10] 接口-数据模型对齐自检: 列出每个端点的请求字段集与响应字段集,以及数据模型字段集; 确认「数据模型的每个字段都在某端点可达」且「每个端点需要的字段数据模型都能提供」,无悬空。`;

// 数据库 schema —— 多张表协作时打架的约定:命名、主外键、类型、约束、索引一致性。
const DB_SCHEMA = `[D1] 表/列命名风格 = ____ (snake_case 复数表名 还是 单数,全局统一)
[D2] 主键策略 = ____ (自增 BIGINT / UUID / ULID,所有表统一一种)
[D3] 外键命名约定 = ____ (如 <表单数>_id,且类型必须与被引用主键完全一致)
[D4] 时间戳列 = ____ (列名、类型如 TIMESTAMPTZ、是否带时区,所有表统一)
[D5] 软删除策略 = ____ (用 deleted_at 还是物理删除;若用,所有相关查询必须过滤)
[D6] 金额/精度类型 = ____ (用 NUMERIC(p,s) 还是整数分,禁止 FLOAT 存钱)
[D7] 枚举落库方式 = ____ (CHECK 约束 / 独立枚举表 / 原生 ENUM,全局统一一种)
[D8] 字符串长度与字符集 = ____ (VARCHAR 上限、utf8mb4 等)
[D9] 跨表引用完整性自检: 列出每个外键的(子表.列 → 父表.列),确认类型一致、父表先建、无环依赖或已用延迟约束。`;

// 状态机 —— 多人定义状态/事件/守卫时打架:状态集、事件名、非法转移处理、幂等。
const STATE_MACHINE = `[S1] 状态集合 = ____ (完整列出所有状态,全局唯一命名,禁止同义不同名)
[S2] 事件/动作命名 = ____ (动词时态统一,如全部用过去式或全部祈使式)
[S3] 初始状态 = ____,终止状态集 = ____
[S4] 合法转移表: 列出 (当前状态, 事件) → (新状态),穷举,不留歧义
[S5] 非法转移处理 = ____ (拒绝并返回什么错误/状态码,所有实现统一)
[S6] 幂等性: 同一事件重复触发的行为 = ____ (忽略/报错/重放,统一一种)
[S7] 守卫/前置条件命名与语义 = ____ (统一表达方式)
[S8] 转移闭合性自检: 确认每个非终止状态对每个可能事件都有明确定义(转移或显式拒绝),无未定义组合。`;

// 配置文件 —— 多模块各写一段配置时打架:键命名、层级、类型、默认值、环境覆盖。
const CONFIG = `[F1] 键命名风格 = ____ (snake_case / kebab-case / camelCase,全局统一)
[F2] 嵌套层级约定 = ____ (按模块/按环境分组,统一一种结构)
[F3] 布尔/数值/时长的类型与单位 = ____ (如时长统一用秒还是 "30s" 字符串)
[F4] 默认值标注方式 = ____ (每个键是否必须给默认值与说明)
[F5] 环境变量覆盖规则 = ____ (前缀、大小写、优先级,统一约定)
[F6] 密钥/敏感项处理 = ____ (禁止明文,统一用占位符或引用)
[F7] 键命名空间自检: 确认无两个模块定义同名但语义不同的键,无层级冲突。`;

// 通用结构化任务 —— 不属于上面任一领域时的兜底:仍强制命名/类型/接口对齐。
const GENERIC = `[G1] 标识符命名风格 = ____ (全局统一)
[G2] 数据类型与格式约定 = ____ (关键字段的类型、格式、单位)
[G3] 时间/日期表示 = ____ (统一格式与时区)
[G4] 枚举/状态取值 = ____ (完整列出,统一命名)
[G5] 错误/异常表示 = ____ (统一一种结构)
[G6] 模块间接口对齐自检: 列出各子任务产出的「对外契约」(字段/函数签名/数据形状),确认互相引用处类型一致、无悬空、无重名冲突。`;

const TEMPLATES: Record<Domain, { label: string; body: string }> = {
  'rest-api': { label: 'REST API', body: REST_API },
  'db-schema': { label: '数据库 Schema', body: DB_SCHEMA },
  'state-machine': { label: '状态机', body: STATE_MACHINE },
  config: { label: '配置文件', body: CONFIG },
  generic: { label: '通用结构化', body: GENERIC },
};

// 关键词分类:根据目标文本猜领域。命中多个时按 REST>schema>状态机>config 优先。
const KEYWORDS: [Domain, RegExp][] = [
  ['rest-api', /\b(rest|api|端点|endpoint|接口契约|http|路由|route)\b|接口/i],
  ['db-schema', /\b(schema|数据库|表结构|table|外键|migration|迁移|ddl|orm)\b|建表/i],
  ['state-machine', /\b(状态机|state\s?machine|状态流转|workflow|流转|fsm)\b|状态机/i],
  ['config', /\b(配置|config|yaml|toml|\.env|settings|参数文件)\b/i],
];

/** 正则兜底:纯字面词匹配,0 成本,浏览器/离线/LLM 降级时用。 */
function domainByKeyword(goal: string): Domain {
  for (const [d, re] of KEYWORDS) if (re.test(goal)) return d;
  return 'generic';
}

const ALL_DOMAINS: Domain[] = ['rest-api', 'db-schema', 'state-machine', 'config', 'generic'];

// 注入给分类 agent 的领域定义。靠语义而非字面词 —— 「登录流程」该归 state-machine,
// 「支付回调对接」该归 rest-api,即便目标里没有「状态机 / api」这些字。
const CLASSIFY_PROMPT = (goal: string) =>
  `把下面这个结构化工程目标归到唯一一个契约领域。只看语义,不要只看字面词。\n\n` +
  `领域定义:\n` +
  `- rest-api: 对外接口/端点/HTTP 路由/回调对接/微服务间通信契约\n` +
  `- db-schema: 数据库表结构/字段/外键/索引/迁移/实体关系建模\n` +
  `- state-machine: 状态流转/工作流/生命周期/审批流/登录注册等多步骤流程\n` +
  `- config: 配置文件/参数/环境变量/feature flag/settings\n` +
  `- generic: 以上都不明确归属的其它结构化工程任务\n\n` +
  `目标:${goal}\n\n` +
  `只输出领域 id 本身(rest-api / db-schema / state-machine / config / generic 之一),不要解释。`;

/** 从可能带杂音(空格/引号/解释)的 LLM 输出里抽出合法领域 id。 */
function parseDomain(raw: string): Domain | null {
  const lower = raw.toLowerCase();
  // 优先精确单词,避免 'generic' 子串误吞;按 id 长度降序匹配防止 'config' 命中 'config-xxx' 之类。
  for (const d of [...ALL_DOMAINS].sort((a, b) => b.length - a.length)) {
    if (new RegExp(`\\b${d}\\b`).test(lower)) return d;
  }
  return null;
}

/**
 * 根据目标文本判定契约领域。
 * 选错领域 = 用错契约模板 = 护城河白搭,所以这一步要尽量准。
 *   • 传入 chat 时走 LLM 语义分类(能识别正则识别不了的目标,如「登录流程」→ state-machine);
 *   • 不传 chat(浏览器/离线)或 LLM 失败时,降级到正则关键词兜底。
 * model-agnostic:复用注入的 ChatFn,不绑定具体厂家。
 */
export async function domainOf(goal: string, chat?: ChatFn): Promise<Domain> {
  if (!chat) return domainByKeyword(goal);
  try {
    const raw = await chat(CLASSIFY_PROMPT(goal), { maxTokens: 20, temperature: 0 });
    return parseDomain(raw) ?? 'generic';
  } catch {
    // LLM 不可用时不让整个 run 崩,退回正则兜底。
    return domainByKeyword(goal);
  }
}

/** 取某领域的完整契约填空 prompt。 */
export function contractFor(domain: Domain): ContractSpec {
  const t = TEMPLATES[domain];
  return { domain, label: t.label, template: HEADER + t.body + FOOTER };
}

/** 取所有领域(用于 UI 展示覆盖范围)。 */
export function allDomains(): { domain: Domain; label: string }[] {
  return (Object.keys(TEMPLATES) as Domain[]).map((d) => ({ domain: d, label: TEMPLATES[d].label }));
}
