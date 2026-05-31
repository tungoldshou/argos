#!/usr/bin/env python3
"""
swarm-ab-minimax.py — 用本地 Hermes(MiniMax-M2.7)做一次 A/B 对照实验:
  A 组:裸蜂群(3 个 agent 各自闷头干,无共享契约)
  B 组:契约层蜂群(先冻结共享契约,3 个 agent 在契约约束下干)

验证命题:对"傻模型",加一层「契约冻结」能否显著减少蜂群产出的互不兼容冲突。
这是 Argos 核心壁垒("model-agnostic 的契约+验证层")能否成立的决定性证据。

不打印 key;key 从 ~/.hermes/.argos_api_key 读。
"""
import json, os, sys, urllib.request, urllib.error

HERMES = "http://127.0.0.1:8642/v1/chat/completions"
KEY = open(os.path.expanduser("~/.hermes/.argos_api_key")).read().strip()
GOAL = "为一个 TODO REST API 设计:数据模型 + 3 个核心端点(创建/查询/更新)+ 一个并发安全隐患的修复建议"

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

SUBTASKS = [
    "设计 TODO 数据模型与持久层(实体字段、类型、约束、DDL)。",
    "设计 3 个核心 REST 端点的接口契约:POST /todos、GET /todos/{id}、PATCH /todos/{id}(请求/响应/错误)。",
    "识别并修复 TODO API 在并发 PATCH 下的'读取-修改-写回'竞态(lost update)。",
]

def run_swarm(contract=None):
    """跑 3 个互不通信的 worker。contract 非空时注入共享契约。"""
    outs = []
    sys_msg = "你是一个只负责单个子任务的工程 agent,看不到其他 agent 的工作。产出要具体、简洁。"
    if contract:
        sys_msg += "\n\n【必须严格遵守的共享契约,不得偏离】:\n" + contract
    for i, st in enumerate(SUBTASKS, 1):
        outs.append(llm(f"子任务[{i}]:{st}", system=sys_msg, max_tokens=900))
    return outs

def freeze_contract():
    """B 组:先让模型冻结一份共享接口契约。"""
    return llm(
        f"目标:{GOAL}\n\n你是'契约冻结 agent'。在任何人开始干活前,先锁定一份所有子任务都必须遵守的共享接口契约,"
        "明确规定:(1)ID 类型与格式 (2)JSON 字段命名风格 (3)完成标志字段名 (4)统一响应封装格式 "
        "(5)统一错误码风格 (6)并发控制令牌字段名与缺失时的状态码 (7)字段长度上限。"
        "只输出这份契约,要简短到每条一行、不容歧义。",
        max_tokens=700)

# C 组:用工程化的「完整契约模板」强制傻模型按模板填满,堵住 B 组暴露的漏项。
# 这是 Argos 的护城河假设:不让模型自由写契约,而是按一份覆盖完整的 checklist 填。
CONTRACT_TEMPLATE = """你必须按下面这份契约模板逐条填写,每一项都不许留空、不许自由发挥、不许新增模板外的概念。
填完后这份契约对所有子任务 agent 强制生效。

[C1] 主键: id, 类型=string, 格式=UUIDv4
[C2] JSON 字段命名: 全部 snake_case
[C3] 时间字段: created_at / updated_at, 类型=string(ISO8601), 时区=必须 UTC(带 Z 后缀)
[C4] 完成状态的唯一真相来源: 在 status 枚举 与 is_completed 布尔 之间【只选一个】, 另一个禁止出现。选定: ____ (你来定, 但只能有一个)
[C5] status 若选用, 枚举值完整列出且 PATCH 必须全部接受; is_completed 若选用, 数据模型必须持久化该字段
[C6] 并发控制令牌: 字段名=____, 且【数据模型必须持久化该字段、PATCH 必须校验它】, 缺失时状态码=____
[C7] 统一响应封装: 单条=____, 列表=____ (必须包含 code 字段, 且数据模型外的封装字段不进持久层)
[C8] 错误格式: ____ (统一一种, 含数字 code 与 message)
[C9] 字段长度: title ≤ ____, description ≤ ____, 超长状态码=____
[C10] 端点与数据模型对齐: 数据模型里出现的每个字段, 必须在某个端点的请求或响应中可达; 端点需要的每个字段, 数据模型必须能提供。列出 POST/GET/PATCH 各自的字段集, 确认无悬空。

只输出填满后的契约, 每条一行, 不容歧义。"""

def freeze_contract_templated():
    """C 组:按工程化完整模板冻结契约(堵住 B 组漏项)。"""
    return llm(f"目标:{GOAL}\n\n{CONTRACT_TEMPLATE}", max_tokens=900)

def judge(assembled, label):
    """交叉验证 agent:数互不兼容的硬冲突。"""
    out = llm(
        f"原目标:{GOAL}\n\n以下是三个互不通信的 agent 的产出拼在一起:\n\n{assembled}\n\n"
        "只做一件事:列出会导致'直接拼起来集成/编译失败'的**硬冲突**(ID 类型矛盾、字段命名不一致、"
        "完成标志不同名、响应封装不一致、错误码/状态码冲突、缺口等)。每条一行。最后一行输出:'硬冲突数: N'。",
        max_tokens=900)
    return out

def main():
    only = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(f"# Argos 契约层实验 — 模型: MiniMax-M2.7(经 Hermes) [{only}]\n")

    if only in ("all", "ab"):
        print("## A 组:裸蜂群(无共享契约)\n")
        a = run_swarm(contract=None)
        a_asm = "\n\n".join(f"### Agent{i+1}\n{o}" for i, o in enumerate(a))
        print(judge(a_asm, "A"))
        print("\n" + "=" * 60 + "\n")
        print("## B 组:模型自由冻结契约\n")
        contract = freeze_contract()
        print("【契约】\n" + contract + "\n")
        b = run_swarm(contract=contract)
        b_asm = "\n\n".join(f"### Agent{i+1}\n{o}" for i, o in enumerate(b))
        print(judge(b_asm, "B"))
        print("\n" + "=" * 60 + "\n")

    if only in ("all", "c"):
        print("## C 组:工程化完整契约模板(堵住漏项)\n")
        ct = freeze_contract_templated()
        print("【模板填满后的契约】\n" + ct + "\n")
        c = run_swarm(contract=ct)
        c_asm = "\n\n".join(f"### Agent{i+1}\n{o}" for i, o in enumerate(c))
        print(judge(c_asm, "C"))
        with open("/tmp/swarm-c-full.json", "w") as f:
            json.dump({"goal": GOAL, "contract": ct, "C": c}, f, ensure_ascii=False, indent=2)
        print("\n(C 组完整产出已存 /tmp/swarm-c-full.json)")

if __name__ == "__main__":
    main()
