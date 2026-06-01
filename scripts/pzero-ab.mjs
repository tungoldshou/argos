// pzero-ab.mjs — P0 生死表:便宜模型「裸调 vs Argos verify 硬门禁闭环」对照实验。
//
// 这张表是 Argos 整个方向的生死开关(对抗审查的存亡问题 1+2):
//   1) 便宜模型 + 确定性 verify,能不能把一次过率显著拉高?
//   2) 拉高的代价(多花的 verify/重试 token)划不划算?
//
// 不靠 LLM 自评(那会谄媚),靠【退出码】当 ground truth:模型生成 TS 函数 → 我们用
// 它看不到的隐藏测试 + tsc 编译,跑出 exit code。0=真过,非0=真没过。模型无法对退出码撒谎。
//
// 两个 arm 共享第 1 轮产出 → 差异纯粹来自「有没有 verify+重试闭环」,不掺模型随机性。
//
// 用法:node scripts/pzero-ab.mjs [每个任务跑几遍,默认1] [闭环最大轮数,默认3]
// 依赖:仅 Node 24(原生 fetch + 顶层 await)+ 仓库里的 tsc。无额外安装。

import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

// 真实 tsc 的绝对路径。【关键】不能用 `npx tsc` —— 环境里的 RTK hook 会把它劫持成
// "This is not the tsc command you are looking for",导致验证器把所有代码误判为挂。
// 直接指向仓库装的真 tsc 二进制,绕过任何 PATH 层的重写。
const REPO = fileURLToPath(new URL('..', import.meta.url));
const TSC_BIN = join(REPO, 'node_modules', '.bin', 'tsc');

// ── 配置 ────────────────────────────────────────────────────────────────────
const TRIALS = Number(process.argv[2] ?? 1);     // 每个任务跑几遍(看稳定性)
const MAX_ROUNDS = Number(process.argv[3] ?? 3);  // 闭环最多重试几轮
const ENDPOINT = 'https://api.minimaxi.com/anthropic/v1/messages';

function loadEnv() {
  const env = Object.fromEntries(
    readFileSync(new URL('../.env.local', import.meta.url), 'utf8')
      .split('\n')
      .filter((l) => l.includes('=') && !l.trim().startsWith('#'))
      .map((l) => { const i = l.indexOf('='); return [l.slice(0, i).trim(), l.slice(i + 1).trim()]; }),
  );
  if (!env.VITE_MINIMAX_KEY) throw new Error('缺 VITE_MINIMAX_KEY,请检查 .env.local');
  return { key: env.VITE_MINIMAX_KEY, model: env.VITE_MINIMAX_MODEL || 'MiniMax-M2' };
}
const { key: KEY, model: MODEL } = loadEnv();

// 累计 token 计量(回答存亡问题 2:成本账)
const cost = { in: 0, out: 0, calls: 0 };

// ── MiniMax 调用(Anthropic 端,与 llm.ts 同格式;thinking block 自动隔离)──────
async function chat(prompt, system, maxTokens = 1500) {
  const res = await fetch(ENDPOINT, {
    method: 'POST',
    headers: { 'x-api-key': KEY, 'anthropic-version': '2023-06-01', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: MODEL,
      ...(system ? { system } : {}),
      messages: [{ role: 'user', content: prompt }],
      max_tokens: maxTokens,
      temperature: 0.2,
    }),
  });
  if (!res.ok) throw new Error(`MiniMax ${res.status}: ${(await res.text()).slice(0, 300)}`);
  const j = await res.json();
  cost.calls++;
  cost.in += j.usage?.input_tokens ?? 0;
  cost.out += j.usage?.output_tokens ?? 0;
  return (j.content ?? []).filter((b) => b.type === 'text').map((b) => b.text).join('');
}

// 从模型输出里抠出代码(剥 ```ts ... ``` 围栏;没围栏就原样)。
function extractCode(text) {
  const fence = text.match(/```(?:ts|typescript|js|javascript)?\s*\n([\s\S]*?)```/);
  return (fence ? fence[1] : text).trim();
}

// ── 隔离验证:把模型代码 + 隐藏测试写进临时目录,跑 tsc 看退出码 ────────────────
// ground truth。返回 { ok, detail }。ok 来自退出码,不来自任何模型判断。
function verify(task, code) {
  const dir = mkdtempSync(join(tmpdir(), 'argos-pzero-'));
  try {
    writeFileSync(join(dir, 'sol.ts'), code);
    // 隐藏测试:import 模型的实现,断言行为。用 tsc 编译(含类型)+ node 跑断言。
    writeFileSync(join(dir, 'test.ts'), task.test);
    // 极简 tsconfig:严格、ESM、不发射(只类型检查 sol.ts 与 test.ts 是否自洽)。
    // CommonJS 输出:编译后 require 风格解析自动补 .js 后缀,避免 ESM 的
    // ERR_MODULE_NOT_FOUND(import './sol' 找不到 './sol.js')。strict 保留全部类型检查力度。
    writeFileSync(join(dir, 'tsconfig.json'), JSON.stringify({
      compilerOptions: { strict: true, target: 'ES2022', module: 'CommonJS', moduleResolution: 'node', noEmit: false, outDir: 'out', skipLibCheck: true, esModuleInterop: true },
      include: ['sol.ts', 'test.ts'],
    }));
    // 第1关:tsc 类型检查 + 编译。类型不过 = 直接失败(退出码非0)。
    try {
      execFileSync(TSC_BIN, ['-p', 'tsconfig.json'], { cwd: dir, stdio: 'pipe', timeout: 60000 });
    } catch (e) {
      return { ok: false, detail: 'tsc 编译失败:\n' + (e.stdout?.toString() || e.message).slice(0, 800) };
    }
    // 第2关:跑编译出的测试,断言失败会 throw → 退出码非0。
    try {
      const out = execFileSync('node', ['out/test.js'], { cwd: dir, stdio: 'pipe', timeout: 30000 });
      return { ok: true, detail: out.toString().slice(0, 200) };
    } catch (e) {
      return { ok: false, detail: '测试失败:\n' + (e.stdout?.toString() || '') + (e.stderr?.toString() || e.message).slice(0, 800) };
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

// ── 一次完整对照:裸调 vs 闭环(共享第1轮产出)────────────────────────────────
const WORKER_SYS = '你是 TypeScript 工程师。只输出一个完整、可直接编译的 TypeScript 实现,放在一个 ```ts 代码块里。禁止解释、禁止散文、禁止写测试。导出方式严格按要求。';

async function runOne(task) {
  // 第1轮:两个 arm 共享的初始产出。
  let code = extractCode(await chat(task.prompt, WORKER_SYS));
  const v1 = verify(task, code);
  const bare = v1.ok; // 裸调结果 = 第1轮是否过

  // 闭环:第1轮过就直接成;没过就把真实错误 bounce 回去重试,带单调护栏。
  let loopOk = v1.ok;
  let rounds = 0;
  let lastDetail = v1.detail;
  while (!loopOk && rounds < MAX_ROUNDS) {
    rounds++;
    const fix = await chat(
      `你之前的实现没通过验证。这是确定性验证器(tsc + 隐藏测试)的真实报错:\n\n${lastDetail}\n\n` +
      `原始需求:\n${task.prompt}\n\n你上次的实现:\n\`\`\`ts\n${code}\n\`\`\`\n\n` +
      `请只针对报错修正,输出修正后的【完整】实现(一个 \`\`\`ts 代码块,禁止解释)。`,
      WORKER_SYS,
    );
    const newCode = extractCode(fix);
    const v = verify(task, newCode);
    // 单调护栏:这里用「过/没过」做收敛信号。过了就采纳;没过就继续喂新报错。
    code = newCode;
    lastDetail = v.detail;
    if (v.ok) { loopOk = true; break; }
  }
  return { bare, loopOk, rounds };
}

// ── 任务集:结构化、退出码可判、便宜模型容易在边角翻车 ──────────────────────────
const TASKS = [
  {
    name: 'parseDuration',
    prompt:
      '实现并 `export function parseDuration(s: string): number`,把人类时长字符串解析成毫秒。\n' +
      '规则:支持组合单位,如 "1h30m"→5400000,"500ms"→500,"2d"→172800000,"90s"→90000,"1h"→3600000。\n' +
      '单位:ms, s, m, h, d。非法输入(空串、未知单位、纯数字无单位)抛 Error。',
    test:
      "import { parseDuration } from './sol';\n" +
      "function eq(a:number,b:number,msg:string){ if(a!==b) throw new Error(msg+` expected ${b} got ${a}`); }\n" +
      "eq(parseDuration('500ms'),500,'500ms');\n" +
      "eq(parseDuration('90s'),90000,'90s');\n" +
      "eq(parseDuration('1h'),3600000,'1h');\n" +
      "eq(parseDuration('1h30m'),5400000,'1h30m');\n" +
      "eq(parseDuration('2d'),172800000,'2d');\n" +
      "let threw=false; try{ parseDuration('10x'); }catch{ threw=true; } if(!threw) throw new Error('10x should throw');\n" +
      "threw=false; try{ parseDuration(''); }catch{ threw=true; } if(!threw) throw new Error('empty should throw');\n" +
      "threw=false; try{ parseDuration('123'); }catch{ threw=true; } if(!threw) throw new Error('no-unit should throw');\n" +
      "console.log('OK');\n",
  },
  {
    name: 'paginate',
    prompt:
      '实现并 `export function paginate<T>(items: T[], page: number, size: number): { data: T[]; total: number; page: number; pages: number }`。\n' +
      'page 从 1 开始。size<1 视为 1。page 超界则 data 为空数组但 total/pages 仍正确。total=元素总数,pages=Math.ceil(total/size)(空数组时 pages=0)。',
    test:
      "import { paginate } from './sol';\n" +
      "const a=[1,2,3,4,5];\n" +
      "function J(x:unknown){return JSON.stringify(x);}\n" +
      "if(J(paginate(a,1,2))!==J({data:[1,2],total:5,page:1,pages:3})) throw new Error('p1');\n" +
      "if(J(paginate(a,3,2))!==J({data:[5],total:5,page:3,pages:3})) throw new Error('p3');\n" +
      "if(J(paginate(a,9,2))!==J({data:[],total:5,page:9,pages:3})) throw new Error('oob');\n" +
      "if(J(paginate([],1,10))!==J({data:[],total:0,page:1,pages:0})) throw new Error('empty');\n" +
      "if(J(paginate(a,1,0))!==J({data:[1],total:5,page:1,pages:5})) throw new Error('size0');\n" +
      "console.log('OK');\n",
  },
  {
    name: 'deepMerge',
    prompt:
      '实现并 `export function deepMerge<A, B>(a: A, b: B): A & B`,深度合并两个普通对象。\n' +
      '规则:b 的值覆盖 a;两边都是普通对象的键递归合并;数组直接被 b 覆盖(不拼接);undefined 不覆盖已有值。',
    test:
      "import { deepMerge } from './sol';\n" +
      "function J(x:unknown){return JSON.stringify(x);}\n" +
      "if(J(deepMerge({a:1,b:{x:1,y:2}},{b:{y:3,z:4}}))!==J({a:1,b:{x:1,y:3,z:4}})) throw new Error('nested');\n" +
      "if(J(deepMerge({a:[1,2]},{a:[3]}))!==J({a:[3]})) throw new Error('array-replace');\n" +
      "if(J(deepMerge({a:1},{a:undefined}))!==J({a:1})) throw new Error('undefined-skip');\n" +
      "console.log('OK');\n",
  },
];

// ── 主流程 ──────────────────────────────────────────────────────────────────
console.log(`\n模型: ${MODEL}  |  每任务 ${TRIALS} 遍  |  闭环上限 ${MAX_ROUNDS} 轮\n`);
const t0 = Date.now();
let bareWins = 0, loopWins = 0, total = 0, roundsSum = 0;

for (const task of TASKS) {
  for (let i = 0; i < TRIALS; i++) {
    total++;
    process.stdout.write(`[${task.name}] 第${i + 1}遍 … `);
    const r = await runOne(task);
    if (r.bare) bareWins++;
    if (r.loopOk) loopWins++;
    roundsSum += r.rounds;
    console.log(`裸调=${r.bare ? '过' : '挂'}  闭环=${r.loopOk ? '过' : '挂'}${r.rounds ? `(修${r.rounds}轮)` : ''}`);
  }
}

const wall = ((Date.now() - t0) / 1000).toFixed(1);
const pct = (n) => `${((n / total) * 100).toFixed(0)}%`;
console.log('\n' + '='.repeat(56));
console.log('P0 生死表');
console.log('='.repeat(56));
console.log(`样本数              : ${total}`);
console.log(`裸调一次过率        : ${bareWins}/${total}  (${pct(bareWins)})`);
console.log(`Argos 闭环交付率    : ${loopWins}/${total}  (${pct(loopWins)})   ← 关键对比`);
console.log(`闭环净挽救          : +${loopWins - bareWins} 个 (verify+重试救回的)`);
console.log(`总修复轮数          : ${roundsSum}`);
console.log(`LLM 调用次数        : ${cost.calls}`);
console.log(`Token (in/out)      : ${cost.in} / ${cost.out}  (总 ${cost.in + cost.out})`);
console.log(`墙钟时间            : ${wall}s`);
console.log('='.repeat(56));
console.log('\n判读:闭环交付率显著高于裸调一次过率 = 方向成立的第一个信号。');
console.log('     再看「净挽救」对应的 token 成本是否划算(存亡问题2)。\n');
