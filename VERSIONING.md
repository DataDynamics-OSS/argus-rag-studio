# 버전 관리 규약

## 정책

- **제품 버전은 락스텝(lockstep)** — 백엔드·프론트엔드·에이전트·확장 서버·rhwp_py 바인딩은
  모두 같은 버전을 쓰고, 릴리스 때 함께 올린다. 단일 소스는
  **`backend/app/__init__.py` 의 `__version__`** 이다.
- **rhwp 코어는 별도 축**(업스트림 릴리스, 현재 v0.7.18) — 세 소비처가 같은 릴리스면 된다.
  절차는 [`backend/native/rhwp_py/README.md`](backend/native/rhwp_py/README.md) 런북.
- **업스트림 이미지는 태그 고정**(`latest` 금지) — vLLM·PostgreSQL·MinIO·zot.
  조달 정책은 [`deploy/upstream-images-deployment.md`](deploy/upstream-images-deployment.md).
- 검사: **`scripts/check-versions.sh`** (불일치 시 exit 1) — 릴리스 전 필수 실행.

한 곳에서 일괄 조정하는 자동화는 없다(빌드 체계가 Python/Node/Rust 로 갈려 현실적으로
어려움). 대신 **아래 파일 목록이 전부**이고, 검사 스크립트가 누락을 잡는다.

## 버전 올리기 절차 (예: 0.1.1 → 0.1.2)

### 1) 고칠 파일 (제품 버전 — 총 11곳)

| # | 파일 | 위치 | 비고 |
|---|---|---|---|
| 1 | `backend/app/__init__.py` | `__version__` | **기준(단일 소스)** — pyproject dynamic·/health·배너가 참조 |
| 2 | `frontend/apps/web/package.json` | `"version"` | |
| 3 | `frontend/package.json` | `"version"` | 워크스페이스 루트 |
| 4 | `agent/app/__init__.py` | `__version__` | heartbeat·서비스 관리 화면에 노출 |
| 5 | `agent/pyproject.toml` | `version` | |
| 6 | `extensions/embedding_server/__init__.py` | `__version__` | `/stats` server_version 으로 노출 |
| 7 | `extensions/reranker_server/__init__.py` | `__version__` | 〃 |
| 8 | `extensions/detection_server/__init__.py` | `__version__` | 〃 |
| 9 | `extensions/hwp_render_server/package.json` | `"version"` | `/stats` version 으로 노출. 갱신 후 `npm install --package-lock-only` 로 락 동기화 |
| 10 | `backend/native/rhwp_py/pyproject.toml` + `Cargo.toml` | `version` (2파일) | wheel 재빌드 필요(`maturin build --release`) |
| 11 | `backend/packaging/config/argus-rag-studio-postgresql.sql` | 헤더 `-- 정합 앱 버전:` | 스키마 변경이 있는 릴리스는 반드시, 없어도 함께 올리는 것을 권장 |

> `frontend/packages/ui`(0.0.0)는 비공개 내부 워크스페이스 — 대상 아님.

### 2) 검증·태그·산출물

```bash
scripts/check-versions.sh          # 11곳 + rhwp 코어 정합 검사 (전부 OK 여야 함)
git commit -am "chore: v0.1.2"     # 버전 변경을 한 커밋으로
git tag v0.1.2 && git push --follow-tags
```

- **git 태그가 이미지 버전의 근원이다** — `Makefile` 의 `VERSION ?= git describe --tags`
  가 이 태그를 쓴다. 태그 없이 push 하면 이미지 태그가 커밋 해시가 된다.
- 산출물 재빌드(해당 릴리스에 배포할 것만):
  - 이미지: `VERSION=0.1.2 REGISTRY=<r> make images-push` (zot) 또는
    `VERSION=0.1.2 FLAT_REPO=datadynamics/argus-rag-studio make images-push` (Docker Hub
    단일 리포 — 태그로 컴포넌트 구분. [조달 가이드](deploy/upstream-images-deployment.md))
  - systemd/shell 패키지: `make packages` (tar) / `OPTS="--deb --rpm"` (OS 패키지) — 버전 자동 반영
  - rhwp_py wheel: `maturin build --release` → backend venv/배포 환경에 설치
  - 에이전트: 원격 호스트는 tar 전송 후 **venv pip 재설치 + 재시작** 필수(`deploy/agent-deployment.md`)

### 3) 배포본 버전 확인 지점 (런타임)

| 컴포넌트 | 확인 방법 |
|---|---|
| 백엔드 | `/health`·시작 배너·OpenAPI |
| 에이전트/워커 | 서비스 관리 탭·잡 모니터링(heartbeat version) |
| 확장 서버 4종 | 각 `/stats` (잡 모니터링 서비스 탭에 표시) |
| rhwp_py | `rhwp_py.__version__`(바인딩) / `__rhwp_version__`(코어) |

## rhwp 코어 (별도 축 — 요약)

세 소비처(backend Cargo rev = 릴리스 태그 커밋, frontend·render server npm 정확 버전)를
같은 릴리스로. 검사 `scripts/check-rhwp-version.sh`, 절차는 rhwp_py README 런북.

## 그 외 버전이 있는 것들 (앱이 관리 — 손댈 필요 없음)

- API prefix `/api/v1`, 파이프라인 버전·라우팅 정책 버전(DB 데이터), 모델 레지스트리
  revision(팩 단위 — HF commit 자동 고정은 백로그).
