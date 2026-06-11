"""IntentEngine — NL→Goal 意图引擎(设计 §7 + §2.4)。

两步流水线：
    1. 确定性预检（规则层）：空泛检测 + 高风险词表 → 直接生成 risk_flags / confirmation_required。
    2. 模型辅助结构化（AI 层）：提示模型吐 JSON，fail-closed 解析，JSON 坏/字段缺 → 降级。

Fail-closed 原则：任何解析失败 → 降级 IntentCard(goal=原话, confirmation_required=True)。
诚实红线：不编造 goal，不假装理解成功，不静默丢弃 risk_flags。

与仓库 ModelClient 同构的 duck-type（只用 async stream）—— 测试用 FakeModel 脚本驱动，
不连真模型。
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator, Protocol, runtime_checkable

from argos_agent.intent.card import IntentCard


# ─── 高风险词表 ────────────────────────────────────────────────────────────────
# 命中任意词 → risk_flags 打标 + confirmation_required=True
# 词表覆盖：文件删除/金融转账/通信发送/系统卸载/存储格式化等不可逆操作。
# 扩展原则：只加有明确不可逆语义的动词，不加一般操作词（"修改"/"更新"不在表内）。
_RISK_WORDS: dict[str, str] = {
    # 删除类
    "删除": "delete_files",
    "删掉": "delete_files",
    "删光": "delete_files",
    "清空": "delete_files",
    "移除": "delete_files",
    "remove": "delete_files",
    "delete": "delete_files",
    "rm": "delete_files",
    "unlink": "delete_files",
    "purge": "delete_files",
    "wipe": "delete_files",
    "erase": "delete_files",
    # 金融/转账类
    "转账": "financial_transfer",
    "付款": "financial_transfer",
    "打款": "financial_transfer",
    "汇款": "financial_transfer",
    "支付": "financial_transfer",
    "transfer": "financial_transfer",
    "payment": "financial_transfer",
    "pay": "financial_transfer",
    "购买": "purchase",
    "下单": "purchase",
    "buy": "purchase",
    "order": "purchase",
    # 通信/发送类
    "发送": "send_message",
    "发邮件": "send_email",
    "发短信": "send_sms",
    "群发": "send_message",
    "send": "send_message",
    "email": "send_email",
    "邮件": "send_email",
    # 系统操作类
    "卸载": "uninstall",
    "格式化": "format_disk",
    "format": "format_disk",
    "uninstall": "uninstall",
    "格式化硬盘": "format_disk",
    # 权限 / 系统设置类
    "sudo": "elevated_privilege",
    "root": "elevated_privilege",
    "chmod": "permission_change",
    "chown": "permission_change",
}

# 空泛请求模式：太短或无动词目标
_VAGUE_PATTERNS = [
    re.compile(r"^\s*$"),                          # 空
    re.compile(r"^.{0,5}$"),                       # 极短(≤5字符)
    re.compile(r"^(帮我|帮|please|help|do|做)\s*$", re.IGNORECASE),  # 只有动词没有目标
]

# 模型提示模板
_PARSE_PROMPT = """\
你是一个意图解析引擎。将下面的用户请求解析为结构化 JSON，遵守格式要求。

用户请求：
{utterance}

请输出严格 JSON（不要 markdown 代码块，不要额外说明），格式如下：
{{
  "goal": "规范化目标描述（一句话，精确，可直接喂给执行引擎）",
  "deliverable": "交付物形态的人话描述（如：一个 Python 脚本 / 已修改的文件 / 已发送的邮件）",
  "constraints": ["约束1", "约束2"],
  "not_doing": ["明确不做的事1"],
  "questions": ["只问改变方案的澄清问，最多3个"]
}}

规则：
- goal 不得为空
- questions 最多 3 个，只问对方案有实质影响的问题；如果意图已足够清晰则输出空数组
- 所有字段必须存在
- 输出纯 JSON，不加任何说明文字
"""


# ─── Model duck-type ───────────────────────────────────────────────────────────

@runtime_checkable
class _ModelLike(Protocol):
    """与 ModelClient.stream 同构的 duck-type。
    测试用 FakeModel 只要实现这个方法签名即可。"""

    def stream(
        self, messages: list[dict], *, system: str, system_dynamic: str | None = None,
    ) -> AsyncIterator[str]:
        ...  # pragma: no cover


# ─── IntentEngine ──────────────────────────────────────────────────────────────

class IntentEngine:
    """NL→Goal 意图引擎。

    parse(utterance, model) -> IntentCard
    render_confirmation(card) -> str
    """

    # ─── 确定性预检 ────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_risk_flags(utterance: str) -> tuple[str, ...]:
        """扫描高风险词表，返回去重 flag 元组（保持 deterministic 顺序）。"""
        lower = utterance.lower()
        seen: dict[str, None] = {}  # 用 dict 保序去重（Python 3.7+）
        for word, flag in _RISK_WORDS.items():
            if word.lower() in lower:
                seen[flag] = None
        return tuple(seen.keys())

    @staticmethod
    def _is_vague(utterance: str) -> bool:
        """空泛检测：极短或只有动词没有目标。"""
        for pat in _VAGUE_PATTERNS:
            if pat.match(utterance):
                return True
        return False

    # ─── 模型解析 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _call_model(utterance: str, model: _ModelLike) -> str:
        """调用模型，收集全文并返回。"""
        prompt = _PARSE_PROMPT.format(utterance=utterance)
        messages = [{"role": "user", "content": prompt}]
        chunks: list[str] = []
        async for chunk in model.stream(messages, system="你是意图解析助手，只输出 JSON。"):
            chunks.append(chunk)
        return "".join(chunks)

    @staticmethod
    def _parse_model_output(raw: str) -> dict | None:
        """解析模型输出的 JSON。fail-closed：任何异常 → None。"""
        # 剥 markdown 代码块（模型可能不听话）
        stripped = raw.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            # 去头尾 ```
            inner = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            stripped = inner.strip()
        try:
            obj = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(obj, dict):
            return None
        # 必须字段检查
        required = {"goal", "deliverable", "constraints", "not_doing", "questions"}
        if not required.issubset(obj.keys()):
            return None
        # goal 不得为空字符串
        if not isinstance(obj.get("goal"), str) or not obj["goal"].strip():
            return None
        return obj

    @staticmethod
    def _coerce_tuple(value: object) -> tuple[str, ...]:
        """将 list/None/str 转为 tuple[str, ...]，fail-safe。"""
        if isinstance(value, (list, tuple)):
            return tuple(str(v) for v in value if isinstance(v, str))
        return ()

    # ─── 公开 API ──────────────────────────────────────────────────────────────

    async def parse(self, utterance: str, model: _ModelLike) -> IntentCard:
        """口语 → IntentCard。

        流程：
            1. 确定性预检（规则层）：空泛 + 风险词扫描。
            2. 模型辅助结构化。
            3. fail-closed：解析失败 → 降级 card（goal=原话，confirmation_required=True）。
            4. 明确目标（预检清晰 + 模型 0 问） → confirmation_required=False 直出。
        """
        utterance = utterance.strip()

        # 1. 确定性预检
        risk_flags = self._detect_risk_flags(utterance)
        is_vague = self._is_vague(utterance)

        # 2. 模型解析（即使已检测到风险也调用，以获取 goal/deliverable 等结构化字段）
        try:
            raw = await self._call_model(utterance, model)
            parsed = self._parse_model_output(raw)
        except Exception:  # noqa: BLE001
            # 网络/超时等异常：fail-closed 降级
            parsed = None

        if parsed is None:
            # Fail-closed 降级：goal=原话，保留预检风险
            return IntentCard(
                utterance=utterance,
                goal=utterance,
                deliverable="",
                constraints=(),
                not_doing=(),
                risk_flags=risk_flags,
                confirmation_required=True,
                questions=(),
            )

        # 3. 组装 IntentCard
        model_questions = self._coerce_tuple(parsed.get("questions"))
        # 最多保留 3 个问题
        questions = model_questions[:3]

        # 4. 判断是否需要确认：
        #    - 有风险标签 → 必须确认
        #    - 空泛 → 必须确认（有问题）
        #    - 模型有澄清问 → 必须确认
        #    - 否则直出
        needs_confirm = bool(risk_flags) or is_vague or len(questions) > 0

        return IntentCard(
            utterance=utterance,
            goal=parsed["goal"].strip(),
            deliverable=str(parsed.get("deliverable", "")).strip(),
            constraints=self._coerce_tuple(parsed.get("constraints")),
            not_doing=self._coerce_tuple(parsed.get("not_doing")),
            risk_flags=risk_flags,
            confirmation_required=needs_confirm,
            questions=questions,
        )

    @staticmethod
    def render_confirmation(card: IntentCard) -> str:
        """生成人话确认文本，回显给用户确认意图。

        风险标签显式列出；not_doing 明确说明；questions 列于末尾。
        """
        lines: list[str] = []

        # 主目标
        goal_line = f"我理解你要：{card.goal}"
        lines.append(goal_line)

        # 交付物
        if card.deliverable:
            lines.append(f"交付物：{card.deliverable}")

        # 约束
        if card.constraints:
            constraints_str = "、".join(card.constraints)
            lines.append(f"约束：{constraints_str}")

        # 明确不做
        if card.not_doing:
            not_doing_str = "、".join(card.not_doing)
            lines.append(f"我不会做：{not_doing_str}")

        # 风险标签
        if card.risk_flags:
            flags_str = "、".join(card.risk_flags)
            lines.append(f"⚠️  检测到高风险操作：{flags_str}（此操作可能不可逆，请确认）")

        # 确认询问
        lines.append("")
        lines.append("对吗？")

        # 澄清问
        if card.questions:
            lines.append("")
            lines.append("另外，有几个问题需要你确认：")
            for i, q in enumerate(card.questions, 1):
                lines.append(f"  {i}. {q}")

        return "\n".join(lines)
