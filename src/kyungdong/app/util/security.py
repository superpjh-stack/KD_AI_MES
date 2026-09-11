"""보안 헤더 · CSP (goal.md §10-12 · G-26 · G-30).

직전 사업(송월타월)에서 **시드 계정이 공통 비밀번호를 공유**한 것이 최대 보안 결함이었다.
그때 얻은 것들을 **처음부터** 넣는다 — 외부 CDN 0 · 전역 500 핸들러 · 속도 제한 · 서버측 세션 무효화.

사업계획서 9.2 는 "외부 접속 최소화 · 필요 시 VPN/암호화 통신" 까지만 적었다.
**TLS 버전·암호화 알고리즘은 미기재(D-15)** 이므로 다른 사업의 사양을 정본인 척 적지 않는다.
"""
from __future__ import annotations

from ..settings import settings

# 외부 CDN 0 — 차트도 인라인 CSS/SVG 로 그린다(goal.md 개발2 지시).
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",   # Jinja 인라인 style 속성 때문에 필요
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])

BASE_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",          # 업무 데이터가 프록시·브라우저에 남지 않게
}

# prod 에서만 — 로컬은 TLS 종단이 없다. 설정과 코드 경로 존재로 판정한다(G-26).
PROD_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


def headers() -> dict[str, str]:
    h = dict(BASE_HEADERS)
    if settings().is_prod:
        h.update(PROD_HEADERS)
    return h
