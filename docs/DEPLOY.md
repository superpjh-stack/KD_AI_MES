# 배포 — Hostinger VPS Docker Manager (D-231)

경동글로벌텍 제조AI (SF26179182) 를 VPS 1대에 올린다.
저장소: `https://github.com/superpjh-stack/KD_AI_MES` (공개) · VPS: `srv1934103.hstgr.cloud` (187.52.127.215)

## 원 설계와 다른 점 — 기록해 둔다

사업계획서 2.4 는 **AP 1 · DB 2 · Vector DB 1 · AI 1** 의 5대와 클라우드 36개월(36,000천원)을 계상했다.
이 배포는 **VPS 1대에 컨테이너 2개**(앱 + PostgreSQL 17 + pgvector 확장)다.

| 항목 | 사업계획서 2.4 | 이 배포 |
|---|---|---|
| AP 서버 | 4 vCPU / 8G — Nginx·FastAPI·Streamlit·Docker | `app` 컨테이너 (uvicorn 단독) |
| DB 서버 ×2 | 4 vCPU / 16G ×2 | `db` 컨테이너 1개 (이중화 없음) |
| Vector DB | 별도 1대 (pgvector — 4.7 은 Qdrant, D-18) | 같은 `db` 컨테이너의 `vector` 확장 |
| AI 서버 | 8 vCPU / 16G — LangChain·LangGraph·Prophet | 앱 컨테이너 안 (LLM 키 없어 Agent 는 501, D-08) |

시범·검증용이다. **검수 시점에는 이 차이를 SF-PM3 변경관리내역서에 올린다.**

## 같은 VPS 의 다른 앱과 포트

이 VPS 에는 다른 사업의 앱 13개가 떠 있다(afc200 · kwangsung · kkotsuni · imjingang · jaeil_pm · …).
호스트 포트 사용 중: **3000 · 8000 · 8010 · 8011 · 8012 · 8501 · 8504 · 8505 · 8507 · 8600 · 443(Caddy)**.
이 앱은 **8020** 을 쓴다 (goal.md §8 의 개발 포트와 같다). 겹치면 `KYUNGDONG_PORT` 로 바꾼다.

## 절차 — hPanel → VPS → Docker Manager

### 1. 비밀값 2개를 만든다

```bash
openssl rand -base64 32   # POSTGRES_PASSWORD
openssl rand -base64 32   # KYUNGDONG_SESSION_SECRET
```

`KYUNGDONG_SESSION_SECRET` 은 **고정값**이어야 한다. 바뀌면 접속 중인 사용자가 전원 로그아웃된다.

### 2. 저장소를 VPS 에 받아 둔다 — hPanel 우상단 **Web console**

Docker Manager 는 저장소를 빌드하지 않는다 — **Compose from URL 에 저장소 URL 을 주면 빈 `services:` 만 남았다**(실측).
그래서 웹 콘솔에서 저장소를 받아 두고, compose 의 빌드 컨텍스트로 그 경로를 준다.

```bash
cd /root && git clone https://github.com/superpjh-stack/KD_AI_MES.git     # 갱신은 cd KD_AI_MES && git pull
```

### 3. Compose → **Compose manually** (또는 만들어 둔 `kyungdong` 앱의 .yaml 편집기)

| 칸 | 값 |
|---|---|
| Application name | `kyungdong` |
| .yaml editor | `docker/compose.hostinger.yml` 내용 그대로 (`build.context: /root/KD_AI_MES`) |
| Environment | `POSTGRES_PASSWORD=…` `KYUNGDONG_SESSION_SECRET=…` `KYUNGDONG_PORT=8020` `KYUNGDONG_ENV=dev` |

Deploy 를 누르면 이미지를 빌드하고(약 3~5분 — xgboost·shap·scikit-learn 설치) 두 컨테이너가 뜬다.
코드를 바꾼 뒤에는 웹 콘솔에서 `git pull` 하고 Docker Manager 에서 다시 Deploy 한다.

### 4. 최초 기동 로그에서 계정 비밀번호를 받아 적는다

엔트리포인트가 **DB 대기 → 스키마(68테이블) → 시드** 를 순서대로 한다. 시드는 계정 6개
(`admin` `exec` `prod` `quality` `operator` `supplier`)를 만들고 **계정별 난수 비밀번호를 로그에 딱 한 번**
출력한다(G-29 — 저장되지 않는다). 재기동해도 기존 계정의 비밀번호는 바뀌지 않는다(D-207).

```
[entrypoint] 스키마 적용 완료 — 테이블 68개 · 컬럼 762개
[entrypoint] 시드 — 공통 (db/seed.py)
   admin    / <난수>
   ...
[entrypoint] 앱 기동 — env=dev · llm=미구성(D-08) · 검색=tsvector_keyword(D-08) · CAD=미구성(D-05)
```

놓쳤으면 컨테이너 터미널에서 재발급한다(화면에 1회 출력 · 감사 로그에는 누가 언제만):

```bash
python tools/ops_password.py --login admin
```

### 5. 확인

```
http://187.52.127.215:8020/health     → {"status":"ok","canon":"45/10/49/68/762 일치"}
http://187.52.127.215:8020/dsh/003    → 설비상태 모니터링 (실시간 패널)
```

hPanel 방화벽에서 8020 이 열려 있어야 한다. `canon` 이 일치하지 않으면 정본 파일이 이미지에 빠진 것이다.

### 6. 시연 — PLC 시뮬레이터

컨테이너 안에서 돌린다(장비 IP 가 없어 실물은 못 붙는다, D-169). 데이터에는 시뮬레이터 표지가 남는다(D-174).

```bash
# Docker Manager → kyungdong-app → Terminal
python tools/plc_simulator.py --start-work-order WO-2017-0002
python tools/plc_simulator.py --daemon --via inproc --poll-sec 2 --anomaly-rate 0.05 --fault-every 30
#   (--via http 는 컨테이너 안에서 자기 자신을 부른다: --base-url http://127.0.0.1:8020)
python tools/plc_simulator.py --finish-work-order WO-2017-0002
```

## 프로파일 — dev 로 올렸다. 그 뜻을 알고 써야 한다

| | dev (지금) | prod |
|---|---|---|
| 로그인 | **없다** — 누구나 시스템 관리자로 열린다 (D-206) | 필수 |
| 쿠키 | 평문 | `Secure` — **HTTPS 없이는 로그인이 성립하지 않는다** (D-208) |
| 역할 전환 `?as=` | 가능 | 불가 |

**공개 IP 에 dev 로 두는 것은 시연·검증 동안만이다.** 운영으로 쓰려면 HTTPS 종단을 붙이고 `KYUNGDONG_ENV=prod` 로 바꾼다.

## HTTPS 로 올릴 때

이 VPS 의 443 은 광성정밀 앱의 Caddy(`KwangSung AI Platform/docker/caddy`)가 쥐고 있고 호스트명은
`srv1934103.hstgr.cloud` 하나다. 이 앱을 HTTPS 로 내려면 **그 Caddy 에 사이트 하나를 더 얹는다**
(포트 8443 · 같은 인증서 · 같은 `web` 네트워크):

```caddyfile
srv1934103.hstgr.cloud:8443 {
	reverse_proxy kyungdong-app:8020
	encode zstd gzip
}
```

그리고 Caddy 컨테이너에 `8443:8443` 을 열고, 이 앱의 compose 에 `networks: [default, web]` 을 더한 뒤
`KYUNGDONG_ENV=prod` 로 재기동한다. 이 작업은 **다른 사업의 배포를 건드리는 일**이라 여기서 하지 않았다.
TLS 버전·암호 스위트는 사업계획서에 값이 없다(D-15) — 도입기업 보안 기준에 맞춘다.

## 운영 전 확인 (도입기업 회신 대기)

| 항목 | 현재 | 필요 |
|---|---|---|
| 장비 IP · PLC 태그맵 (D-169 · D-176) | 수집 API 는 prod 에서 403 · 시뮬레이터로만 | 레이저커팅기 PLC · 현장POP IP, 태그 ↔ 레지스터 주소 |
| LLM · 임베딩 (D-08) | 501 "LLM 미구성" · `tsvector_keyword` | 공급자·모델·키 |
| CAD 파서 (D-05) | 501 + 명시 배지 | Autodesk API · YOLOv8 · OCR |
| 표준 작업조건 (D-59 · D-225) | 임계 비교 차단 | 공정별 표준값·허용범위 |
| TLS · 백업 · 보존기간 (D-15 · D-17) | 정책 없음 | 도입기업 기준 |
