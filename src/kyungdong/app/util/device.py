"""수집 장비 인증 (D-103 후속) — **지금은 인증할 수단이 없다. 그 사실을 말한다.**

D-103 은 기계 대 기계 엔드포인트 4건을 CSRF 에서 면제하면서 **"다른 수단(장비 등록 기반
인증)으로 보호한다"** 고 적었다. 그 수단이 **구현되지 않은 채로 남아 있었고**, 실측해 보니
prod 에서 `POST /api/ingest/plc` 와 `/api/ingest/gateway/resend` 가 **403** 이다 —
세션이 없으면 `role_code` 가 빈 문자열이 되고 `rbac.can_write()` 가 막는다.
**PLC 와 Gateway 가 운영에서 데이터를 넣지 못한다.** 개발에서는 `x-kyungdong-role` 헤더가
SYSADMIN 을 주기 때문에 게이트가 전부 통과해 이것이 보이지 않았다.

**왜 아직 고치지 못하나 — 자리가 없다.**
  · TD5 `IF_DEVICE_REGISTRY` 11컬럼에 **비밀키·인증서·토큰 칸이 없다**
    (DEVICE_NAME · DEVICE_TYPE · MODEL_NAME · IP_ADDRESS · PROTOCOL · COLLECT_INTERVAL ·
     LOCATION_DESC · USE_YN · CREATED_DT · UPDATED_DT). **컬럼을 추가하지 않는다** (G-02 762 고정).
  · 인증에 쓸 수 있는 유일한 칸은 `IP_ADDRESS` 인데 **등록된 2대 모두 NULL 이다** —
    도입기업이 장비 IP 를 주지 않았고, 시드는 IP 를 **지어내지 않았다**.

그래서 이 모듈은 **동작을 바꾸지 않는다.** 오늘 바꾸는 것은 **실패 메시지 하나**다:
`데이터관리 등록 권한 없음`(권한 문제처럼 보인다) → `등록된 수집 장비가 아니다 + 왜 그런지`.
조용한 실패는 아니었지만 **틀린 진단**이었다 — 현장에서 이 403 을 보면 권한 설정을 뒤진다.

IP 가 등록되면 이 모듈이 그대로 통과시킨다. **IP 대조는 암호학적 인증이 아니다** —
사업계획서 9.2 의 VPN/암호화 통신과 외부 접속 최소화 위에 얹는 **보조 수단**이고,
그 한계를 `reason()` 이 문장으로 달고 나간다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 이 경로들만 장비가 부른다. `util/csrf.EXEMPT_PATHS` 와 **같은 목록이어야 한다** —
# 둘이 어긋나면 CSRF 는 면제인데 장비 인증은 안 보는 구멍이 생긴다. 테스트가 대조한다.
from .csrf import EXEMPT_PATHS

MACHINE_PATHS: tuple[str, ...] = tuple(EXEMPT_PATHS)

# 시뮬레이터 선언 (D-174) — `SYNTHETIC_THREAD`(D-131) · `ASSUMED_ANSWERS`(D-160) 와 같은 방식.
# **IP 가 등록돼 있으면 그것이 실물인지 시뮬레이터인지 반드시 구분된다.** 구분이 없으면
# 시뮬레이터로 채운 IP 가 "장비가 붙었다" 로 읽힌다.
CONFIG_TYPE = "시스템설정"
CONFIG_KEY = "PLC_SIMULATOR"

# IP 대조가 막지 못하는 것 — 판정 문장에 그대로 싣는다. 강도를 부풀리지 않는다.
LIMIT_NOTE = ("IP 대조는 암호학적 인증이 아니다 — 같은 IP 를 쓰는 다른 프로그램을 가리지 "
              "못한다. 사업계획서 9.2 의 VPN·폐쇄망 위에 얹는 보조 수단이다")


@dataclass(frozen=True)
class Device:
    device_id: int
    name: str
    device_type: str
    ip: str


def simulation() -> str | None:
    """시뮬레이터 선언의 결정번호. 없으면 `None`.

    선언이 있으면 `IF_DEVICE_REGISTRY.IP_ADDRESS` 는 **시뮬레이터가 넣은 값**이다 —
    실물 장비가 붙은 것이 아니다. 선언을 지우면 `tools/plc_simulator.py --unregister`
    가 IP 도 함께 거둔다: **데이터만 남기고 표시만 떼는 것이 되지 않게** 한다.
    """
    import conn

    try:
        row = conn.q1("select CONFIG_VALUE from SYS_CONFIGS where CONFIG_TYPE = %s "
                      "and CONFIG_KEY = %s and USE_YN = 'Y'", (CONFIG_TYPE, CONFIG_KEY))
    except Exception:                 # noqa: BLE001
        return None
    return (row["config_value"] or None) if row else None


def simulation_note() -> str:
    """등록된 IP 가 시뮬레이터라는 **한 문장**. 실물이면 빈 문자열."""
    decl = simulation()
    return "" if decl is None else (
        f"시뮬레이터 기준 ({decl}) — 등록된 장비 IP 는 실물이 아니라 "
        f"`tools/plc_simulator.py` 가 넣은 값이다. 도입기업 장비 IP 는 아직 없다 (D-169)")


def client_ip(request: Any) -> str:
    """요청의 출발지 IP. 프록시 헤더를 **믿지 않는다** — 헤더는 누구나 적을 수 있다."""
    c = getattr(request, "client", None)
    return (getattr(c, "host", "") or "") if c is not None else ""


def _registered() -> list[dict]:
    """`USE_YN='Y'` 이고 **IP 가 등록된** 장비. DB 를 못 읽으면 **빈 목록**이다.

    빈 목록은 '장비 없음' 이지 '전부 허용' 이 아니다 — 부르는 쪽이 막는다.
    """
    import conn                       # 지연 임포트 — util 이 db 를 끌고 들어오지 않게

    try:
        return conn.q(
            "select DEVICE_ID, DEVICE_NAME, DEVICE_TYPE, IP_ADDRESS from IF_DEVICE_REGISTRY "
            "where USE_YN = 'Y' and IP_ADDRESS is not null and length(trim(IP_ADDRESS)) > 0 "
            "order by DEVICE_ID")
    except Exception:                 # noqa: BLE001 — DB 장애는 G-30 이 503 으로 잡는다
        return []


def identify(request: Any) -> Device | None:
    """출발지 IP 가 등록된 장비면 그 장비. 아니면 **None** — 통과시키지 않는다."""
    ip = client_ip(request)
    if not ip:
        return None
    for r in _registered():
        if str(r["ip_address"]).strip() == ip:
            return Device(int(r["device_id"]), str(r["device_name"]),
                          str(r["device_type"]), ip)
    return None


def reason(request: Any) -> str:
    """왜 인증되지 않았는지 **한 문장**. 현장에서 이걸 읽고 어디를 고칠지 알아야 한다."""
    import conn

    ip = client_ip(request) or "알 수 없음"
    try:
        total = int(conn.q1("select count(*) as n from IF_DEVICE_REGISTRY "
                            "where USE_YN = 'Y'")["n"])
    except Exception:                 # noqa: BLE001
        total = -1
    with_ip = len(_registered())
    if total == 0:
        return (f"출발지 {ip} — IF_DEVICE_REGISTRY 에 사용중인 수집 장비가 0건이다. "
                f"화면 034 수집장비관리에서 등록해야 한다")
    if with_ip == 0:
        return (f"출발지 {ip} — 등록된 수집 장비 {total}대 전부 **IP_ADDRESS 가 비어 있다**. "
                f"도입기업이 장비 IP 를 주지 않았고 시드가 지어내지 않았다 — "
                f"화면 034 수집장비관리에서 IP 를 넣으면 이 경로가 열린다 (D-168)")
    sim = simulation_note()
    return (f"출발지 {ip} 는 등록된 수집 장비 {with_ip}대 어디와도 맞지 않는다 — "
            f"화면 034 수집장비관리에서 IP 를 확인한다" + (f" · {sim}" if sim else ""))
