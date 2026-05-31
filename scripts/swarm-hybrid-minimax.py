#!/usr/bin/env python3
"""
swarm-hybrid-minimax.py — 验证「混合契约冻结」(固定骨架 + 动态填充)在真实 MiniMax 上
是否仍能把结构化任务的蜂群冲突清零,即与旧的纯固定模板 C 组(=0)持平。

镜像 src/engine/swarm.ts 的新 freezeContract 逻辑:
  Pass A: 模型按「固定骨架必检项(沿用原 ID) + 目标专属扩展(X 编号)」动态生成契约
  漏项检测(纯程序): 骨架必检 ID 是否齐全
  Pass B: 缺则把缺项甩回去强制回填一次

对照组 H(混合)目标用一个骨架没显式列全、需要动态扩展的 REST API(带分页/过滤/排序),
以检验「动态扩展」真的发生、且「固定兜底」真的防漏。

不打印 key;key 从 ~/.hermes/.argos_api_key 读。
"""
import json, os, re, sys, urllib.request, urllib.error

HERMES = "http://127.0.0.1:8642/v1/chat/completions"
KEY = open(os.path.expanduser("~/.hermes/.argos_api_key")).read().strip()

# 故意选一个比 swarm-ab 更复杂的目标:除了基础 CRUD,还要分页/过滤/排序/软删除——
# 这些骨架 C1-C10 没逐条列,正好逼出「动态扩展」(X 条),检验混合策略。
GOAL = ("为一个多用户笔记 REST API 设计:数据模型 + 端点(创建/列表分页过滤排序/详情/更新/软删除)"
        " + 并发安全 + 标签多对多关系")

# ── 固定骨架(= src/engine/contracts.ts 的 REST_API,必检项 C1-C10) ──
REST_SKELETON = """[C1] 主键: id, 类型与格式 = ____ (如 string/UUIDv4)
[C2] JSON 字段命名风格 = ____ (snake_case 或 camelCase,全局统一)
[C3] 时间字段命名与格式 = ____ (字段名、类型、时区必须明确,如 created_at/updated_at, ISO8601, UTC 带 Z)
[C4] 状态/完成标志的唯一真相来源: 在「枚举字段」与「布尔字段」之间【只选一个】,另一个禁止出现。选定 = ____
[C5] 上一条选定的字段: 数据模型必须持久化它; 若为枚举,完整列出取值且所有写端点必须接受
[C6] 并发控制令牌: 字段名 = ____,【数据模型必须持久化、写操作必须校验】,缺失/冲突时状态码 = ____
[C7] 统一响应封装: 单条 = ____,列表 = ____ (含状态/错误码字段,封装字段不进持久层)
[C8] 错误格式 = ____ (统一一种,含数字 code 与 message)
[C9] 字段长度上限: 各关键字段上限 = ____,超长时状态码 = ____
[C10] 接口-数据模型对齐自检: 列出每个端点的请求字段集与响应字段集,以及数据模型字段集; 确认「数据模型的每个字段都在某端点可达」且「每个端点需要的字段数据模型都能提供」,无悬空。"""

REQUIRED = re.findall(r"^\[([A-Z]\d+)\]", REST_SKELETON, re.M)


def llm(prompt, system=None, max_tokens=1200):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    body = json.dumps({"messages": msgs, "max_tokens": max_tokens, "temperature": 0.3}).encode()
    req = urllib.request.Request(HERMES, data=body, headers={
        "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.load(r)
        return d["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return f"[HTTP {e.code}: {e.read().decode()[:200]}]"
    except Exception as e:
        return f"[ERR: {e}]"


def detect_gaps(contract):
    present = set(re.findall(r"\[([A-Z]\d+)\]", contract))
    missing = [i for i in REQUIRED if i not in present]
    return missing


def count_dynamic(contract):
    return len(set(re.findall(r"\[X\d+\]", contract)))


def freeze_hybrid():
    """镜像 swarm.ts freezeContract:Pass A 动态扩展 → 漏项检测 → Pass B 回填。"""
    # Pass A
    passA = llm(
        f"目标:{GOAL}\n\n这是一个「REST API」类的结构化工程任务。你要冻结一份共享契约,供多个互不通信的 agent 强制遵守。\n\n"
        f"第一部分【必检骨架 —— 每条都必须出现并填实,沿用原编号,不许留空、不许跳过】:\n{REST_SKELETON}\n\n"
        "第二部分【目标专属扩展 —— 根据本目标的特点,新增骨架没覆盖但本任务会让多个 agent 打架的约定】,"
        "用 X1、X2… 编号(例如分页参数名与上限、过滤/排序参数约定、标签多对多的关联表与字段、软删除字段与查询过滤规则等)。\n"
        "每条 X 扩展必须像骨架一样【无歧义、可直接照抄实现】:凡涉及请求头/响应字段/状态码/关联表字段的,"
        "必须把确切字段名、确切状态码、确切表名列出来,不许只给概念。\n\n"
        "第三部分【全局对齐自检 —— 必须输出,编号 [Z1]】:把第一、二部分所有涉及的"
        "请求头、响应字段、状态码、关联表字段逐一汇总成一张清单,确认每个端点(含 DELETE)"
        "都明确了是否需要并发令牌头、409 响应体含哪些字段、每个关联/标签操作走哪个确切端点,无任何一处只在某条提到而其他端点没覆盖。\n\n"
        "只输出填满的契约,每条一行,格式「[编号] 内容」。",
        max_tokens=1100)
    missing = detect_gaps(passA)
    dyn = count_dynamic(passA)
    print(f"[Pass A] 覆盖必检 {len(REQUIRED)-len(missing)}/{len(REQUIRED)},动态扩展 {dyn} 条,缺项={missing or '无'}")

    contract = passA
    refilled = []
    if missing:
        refilled = missing
        contract = llm(
            f"下面这份契约漏掉了必检骨架里的这些条目(绝对不能少):{'、'.join(missing)}。\n\n"
            f"骨架原文(对照补全缺失项):\n{REST_SKELETON}\n\n"
            f"你已写的契约:\n{passA}\n\n"
            f"请输出【补全后的完整契约】,保留已有条目,把缺失的 {'、'.join(missing)} 按骨架要求填实加进去。每条一行,「[编号] 内容」。",
            max_tokens=1200)
        missing2 = detect_gaps(contract)
        print(f"[Pass B] 回填 {refilled} 后,剩余缺项={missing2 or '无'}")
    return contract, refilled


SUBTASKS = [
    "设计笔记数据模型与持久层(实体字段、类型、约束、标签多对多关联表、软删除字段、DDL)。",
    "设计端点接口契约:POST /notes、GET /notes(分页/过滤/排序)、GET /notes/{id}、PATCH /notes/{id}、DELETE /notes/{id}(软删)。",
    "识别并修复并发 PATCH 下的 lost-update 竞态,并说明标签关联在并发下的一致性处理。",
]


def run_swarm(contract):
    sys_msg = ("你是一个只负责单个子任务的工程 agent,看不到其他 agent 的工作。产出要具体、简洁。"
               "\n\n【必须严格遵守的共享契约,不得偏离】:\n" + contract)
    return [llm(f"子任务[{i}]:{st}", system=sys_msg, max_tokens=900) for i, st in enumerate(SUBTASKS, 1)]


def self_check(contract, task, output):
    """worker 合规自检 + self-repair:拿着契约逐条核对自己的产出,违反则改。
    只输出修正后的产出(若本就合规则原样)。这是把『worker 没遵守已存在条款』这一
    执行层失败模式在拼装前就修掉的关键一步。"""
    return llm(
        f"这是必须遵守的共享契约:\n{contract}\n\n"
        f"你刚才负责的子任务:{task}\n\n你的产出:\n{output}\n\n"
        "现在做合规自检:逐条对照契约,检查你的产出有没有任何一处【违反或偏离】契约的具体规定"
        "(例如契约规定 deleted_at IS NULL 过滤已删除,你却写成 IS NOT NULL;契约规定 content 上限 65536,"
        "你却没限制或写了别的值;字段命名、状态码、令牌字段名与契约不一致等)。\n"
        "凡发现违反,一律以【契约为唯一权威】改正,不许反过来质疑契约。\n"
        "只输出修正后的完整产出(若本就完全合规,原样重述即可),不要解释改了什么。",
        system="你是严格的合规自检 agent,契约是唯一权威,你只负责让产出符合契约。",
        max_tokens=1000)


def judge(assembled):
    return llm(
        f"原目标:{GOAL}\n\n以下是三个互不通信的 agent 的产出拼在一起:\n\n{assembled}\n\n"
        "你只数【真冲突】,定义极严:**同一个字段/参数/状态码,两个 agent 各自明确给出了【不同的具体值】**"
        "(例如 A 写 title≤200、B 写 title≤255;A 用 snake_case、B 用 camelCase;A 完成标志叫 status、B 叫 is_done)。\n"
        "**以下一律不算冲突,禁止计入**:\n"
        "  - 某 agent 只是【没有提及/没有复述】另一个 agent 写的东西(分工不同导致的沉默 ≠ 冲突);\n"
        "  - 一方更详细、一方更简略,但两者不矛盾;\n"
        "  - 你推测『可能不一致』但没有看到两个明确且不同的值。\n"
        "判定每条前先自问:『我能同时引用两个 agent 给出的、针对同一项的两个不同具体值吗?』不能 → 不是冲突。\n"
        "逐条列出真冲突(注明两个 agent 各自的值),若无则写『无』。最后一行精确输出『硬冲突数: N』(只用阿拉伯数字,不要加粗不要符号)。",
        max_tokens=900)


def main():
    print(f"# Argos 混合契约冻结实验 — 模型: MiniMax-M2.7(经 Hermes)\n# 目标: {GOAL}\n")
    contract, refilled = freeze_hybrid()
    print("\n【冻结后的契约】\n" + contract + "\n")
    outs = run_swarm(contract)

    def conflicts_of(outputs):
        asm = "\n\n".join(f"### Agent{i+1}\n{o}" for i, o in enumerate(outputs))
        v = judge(asm)
        mm = re.search(r"硬冲突数[:：]\s*\**\s*(\d+)", v)
        return (int(mm.group(1)) if mm else -1), v

    # 基线:无自检
    n0, v0 = conflicts_of(outs)
    print("=" * 60 + "\n## 交叉验证 — 自检前\n" + v0)
    print(f"\n>>> 自检前硬冲突数 = {n0}")

    # 合规自检 + self-repair:每个 worker 对照契约修正自己的产出
    print("\n" + "=" * 60 + "\n## worker 合规自检中…\n")
    checked = [self_check(contract, st, o) for st, o in zip(SUBTASKS, outs)]
    n1, v1 = conflicts_of(checked)
    print("## 交叉验证 — 自检后\n" + v1)
    print(f"\n>>> 自检后硬冲突数 = {n1}  (Δ {n0} → {n1})")

    with open("/tmp/swarm-hybrid.json", "w") as f:
        json.dump({"goal": GOAL, "contract": contract, "refilled": refilled,
                   "outs": outs, "checked": checked,
                   "verdict_before": v0, "conflicts_before": n0,
                   "verdict_after": v1, "conflicts_after": n1}, f, ensure_ascii=False, indent=2)
    print("(完整产出已存 /tmp/swarm-hybrid.json)")


if __name__ == "__main__":
    main()
