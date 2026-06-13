"""类型基石(SHARED INTERFACE CONTRACT §0)——Phase 2-6 共用。

不变量:
1. 不可变:所有值对象用 @dataclass(frozen=True, slots=True)。
2. 三态 fail-closed:VerdictStatus 含 "unverifiable",绝不当 passed(spec §12.5)。
3. 回执不可伪造 / 一份事件三用——见 §1 events.py / §6 Verdict/Receipt(Phase 3)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

VerdictStatus = Literal["passed", "failed", "unverifiable"]
Phase = Literal["plan", "act", "verify", "report"]
ApprovalLevelName = Literal["observe", "propose", "confirm", "auto"]
DecisionKind = Literal["deny", "once", "session", "always"]
RiskLevel = Literal["low", "medium", "high"]
# 模型 profile 名:自由字符串(已无 worker/premium 档位之分;就是 config.json 里的 profile 名)。
ModelTierName = str


@dataclass(frozen=True, slots=True)
class Verdict:
    """三态 verify 裁决(契约 §6.1;spec §12.5)。'unverifiable' 绝不当 passed。

    canonical 归属:types.py(契约 §6.1 指定)。
    verify_gate.py 重新导出此类以保持旧 import 路径(from argos.core.verify_gate import Verdict)。

    self_verified 字段(任务:为无 verify_cmd 任务自动造测试):
      False (默认) = 用户级 verify;passed 等同于"强验证通过"
      True         = "自验证(较弱)":由系统按 reviewer 角色 + canary 守卫
                     生成的测试通过。verdict 仍是 'passed',但调用方(UI/report/统计)
                     必须读 self_verified 区分"强 / 弱",绝不让 self_verified=True 的 passed
                     与用户 verify 的 passed 混为一谈。
    """
    status: VerdictStatus
    detail: str
    verify_cmd: str | None
    attempts: int
    tampered: list[str] = field(default_factory=list)
    self_verified: bool = False

    @staticmethod
    def passed(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        return Verdict(status="passed", detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    @staticmethod
    def passed_self(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        """自验证通过(canary 守卫 + 白名单 + 真跑都过了)。调用方必须看 self_verified=True
        来区别于用户级 passed,绝不在 UI/汇报里冒充强验证。"""
        return Verdict(
            status="passed", detail=detail, verify_cmd=verify_cmd,
            attempts=attempts, self_verified=True,
        )

    @property
    def is_user_verified(self) -> bool:
        """用户级 verify 通过 = status==passed 且 self_verified==False。

        防火墙单一信源:任何"用户级 passed / 可晋升 / 可对外宣称"判断,必须走本属性,
        **绝不**直接判 status==passed。self_verified=True 的 passed 是系统按 reviewer
        角色 + canary 守卫自造的"较弱通过",绝不能与用户级 verify 混为一谈。
        """
        return self.status == "passed" and not self.self_verified

    @staticmethod
    def failed(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        return Verdict(status="failed", detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    @staticmethod
    def unverifiable(detail: str, tampered: list[str], attempts: int) -> "Verdict":
        # 篡改 → 强制 unverifiable；verify_cmd 可能根本没跑，设 None。
        return Verdict(
            status="unverifiable", detail=detail, verify_cmd=None,
            attempts=attempts, tampered=list(tampered),
        )
