"""G-29 개인정보 마스킹. 대상 컬럼은 `contracts/db-schema.md` §6 (6컬럼).

TD5 criteria: 사용자명·연락처·이메일·공급처 담당자는 **암호화 또는 마스킹 대상**.
시드에 실명을 넣지 않는다. TD3 `role_matrix` 의 실명도 제거했다(D-39).
"""
from __future__ import annotations

KINDS = ("name", "phone", "email", "generic")


def mask(value: str | None, kind: str = "generic") -> str:
    """마스킹. `None`·빈값은 빈 문자열 — 화면이 `미확정` 을 따로 붙인다."""
    if not value:
        return ""
    if kind == "name":
        return value[0] + "*" * (len(value) - 1) if len(value) > 1 else value
    if kind == "phone":
        digits = [c for c in value if c.isdigit()]
        return f"{''.join(digits[:3])}-****-{''.join(digits[-4:])}" if len(digits) >= 7 else "*" * len(value)
    if kind == "email":
        local, _, domain = value.partition("@")
        if not domain:
            return "*" * len(value)
        head = local[:2] if len(local) > 2 else local[:1]
        return f"{head}{'*' * max(1, len(local) - len(head))}@{domain}"
    return value[:1] + "*" * max(1, len(value) - 1)
