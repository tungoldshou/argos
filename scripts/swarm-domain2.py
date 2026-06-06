#!/usr/bin/env python3
"""对抗性验证:契约模板在「软领域」(写作,无天然 schema)是否也能收敛蜂群。
若清零→护城河跨领域;若崩→边界在此。同一傻模型 MiniMax-M2.7。"""
import json, os, urllib.request, urllib.error
HERMES = "http://127.0.0.1:8642/v1/chat/completions"
KEY = open(os.path.expanduser("~/.hermes/.argos_api_key")).read().strip()
GOAL = "三人协作写一篇《2026 AI agent 工具横评》文章的三个部分:(1)开发者工具对比 (2)非开发者工具对比 (3)总结与选型建议"

def llm(prompt, system=None, mt=1100):
    msgs = ([{"role":"system","content":system}] if system else []) + [{"role":"user","content":prompt}]
    body = json.dumps({"messages":msgs,"max_tokens":mt,"temperature":0.4}).encode()
    req = urllib.request.Request(HERMES, data=body, headers={"Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)["choices"][0]["message"]["content"]
    except Exception as e: return f"[ERR {e}]"

PARTS = ["写'开发者工具对比'这一节","写'非开发者工具对比'这一节","写'总结与选型建议'这一节"]

# 软领域的契约模板:把写作里会打架的"约定"全列出来强制统一
TEMPLATE = """你必须按下面这份写作契约模板逐条填定,所有作者强制遵守,不许自由发挥:
[W1] 全文统一术语: "agent" 还是 "智能体" 还是 "助手"? 选一个: ____
[W2] 工具名写法: 中文/英文/带版本号? 规定一种, 如 "Claude Code (Opus 4.8)": ____
[W3] 每节统一结构: 规定每节必须包含的小标题序列(如 概述/逐项对比/小结): ____
[W4] 对比维度统一: 所有对比节必须用同一组维度评估(如 价格/能力/生态/学习成本), 列出: ____
[W5] 评分制式: 用星级/分数/文字档位? 选一种并定义档位: ____
[W6] 立场基调: 中立测评 / 推荐导向 / 吐槽向? 选一个: ____
[W7] 引用/数据标注格式: 统一一种(如 "据X(链接)"): ____
[W8] 每节字数上限: ____
[W9] 总结节的选型建议必须引用前两节用过的同一组维度与评分, 不得引入新维度
只输出填满后的契约, 每条一行。"""

def swarm(contract=None):
    sysm = "你只负责文章的一个部分,看不到其他作者写的内容。" + (f"\n\n【强制遵守的写作契约】:\n{contract}" if contract else "")
    return [llm(f"任务:{PARTS[i]}（目标:{GOAL}）", system=sysm, mt=900) for i in range(3)]

def judge(asm):
    return llm(f"目标:{GOAL}\n\n三位互不通信的作者各写一节,拼在一起:\n\n{asm}\n\n"
        "只列出会让这篇文章'读起来像三个人各写各的、无法直接合成一篇'的**硬不一致**:术语不统一、工具名写法不一、"
        "结构不对齐、对比维度不同、评分制式不同、立场基调冲突、总结引用了前文没有的维度等。每条一行,最后输出'硬不一致数: N'。", mt=900)

print(f"# 软领域对抗实验 — MiniMax-M2.7\n目标:{GOAL}\n")
print("## A组:裸蜂群\n")
a=swarm(); print(judge("\n\n".join(f"### 作者{i+1}\n{o}" for i,o in enumerate(a))))
print("\n"+"="*60+"\n## C组:写作契约模板\n")
ct=llm(f"目标:{GOAL}\n\n{TEMPLATE}", mt=800); print("【契约】\n"+ct+"\n")
c=swarm(ct); print(judge("\n\n".join(f"### 作者{i+1}\n{o}" for i,o in enumerate(c))))
json.dump({"goal":GOAL,"A":a,"contract":ct,"C":c}, open("/tmp/swarm-domain2.json","w"), ensure_ascii=False, indent=2)
