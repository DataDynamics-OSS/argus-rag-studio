# 기여 가이드 (Contributing to Argus RAG Studio)

Argus RAG Studio 에 관심을 가져 주셔서 감사합니다! 버그 리포트든, 기능 제안이든, 문서 한 줄
고치는 일이든, 코드 기여든 모두 환영합니다. 처음 기여하시는 분도 막히지 않도록, 이 문서는
"어디서부터 어떻게 시작하면 되는지"를 차근차근 안내합니다.

> 문서·주석·커밋 메시지는 **한국어를 기본**으로 하며, 영어도 무방합니다.

## 목차

- [행동 강령](#행동-강령)
- [기여 방법](#기여-방법)
- [개발 환경 설정](#개발-환경-설정)
- [브랜치 & 커밋 컨벤션](#브랜치--커밋-컨벤션)
- [코드 스타일](#코드-스타일)
- [테스트](#테스트)
- [Pull Request 절차](#pull-request-절차)
- [버전 관리](#버전-관리)
- [보안 취약점 제보](#보안-취약점-제보)
- [라이선스](#라이선스)

## 행동 강령

좋은 코드만큼이나 중요한 게 서로를 대하는 태도입니다. 서로 존중하고 건설적으로 소통해
주세요. 차별·괴롭힘·비방은 허용되지 않습니다.

## 기여 방법

- **버그 리포트** — [이슈](../../issues/new/choose)의 *버그 리포트* 템플릿을 사용해 주세요.
- **기능 제안** — *기능 제안* 템플릿으로 동기와 사용 사례를 설명해 주세요.
- **코드 기여** — 아래 절차에 따라 Fork → 브랜치 → PR 을 보내 주세요.
- 큰 변경(아키텍처·공개 API 변경 등)은 먼저 이슈로 논의해 주시면 좋습니다.

## 개발 환경 설정

먼저 코드를 받아 손에 익히는 단계입니다. 이 프로젝트는 여러 구성 요소를 한 저장소에 모아 둔
모노레포로, 다음과 같이 나뉘어 있습니다: `backend/`(FastAPI), `frontend/`(Next.js),
`agent/`(호스트 배포 에이전트), `extensions/`(임베딩·리랭커·검출·HWP 렌더 등 독립 서버),
`deploy/`(배포 가이드), `docs/`(Antora 매뉴얼). 자세한 구조는 [README](README.md)를 참고하세요.

### 인프라 (PostgreSQL + pgvector, MinIO)

```bash
docker compose -f deploy/docker-compose.infra.yml up -d
```

### Backend (Python 3.11+)

```bash
cd backend
make dev      # 개발 의존성 설치 (pip install -e ".[dev]")
make run      # 개발 서버 실행 (uvicorn --reload, port 4700)
make test     # pytest
make lint     # ruff check + ruff format --check
make format   # ruff format + ruff check --fix
```

DB·오브젝트 스토리지 연결 정보는 코드에 박아 넣지 않고 설정 파일
(`backend/packaging/config/`)이나 환경변수로 주입합니다.

### Frontend

```bash
cd frontend
pnpm install
pnpm dev        # 개발 서버 (Turbopack, port 3000)
pnpm build      # 프로덕션 빌드
pnpm lint       # ESLint
pnpm typecheck  # tsc --noEmit
```

프런트엔드는 기본적으로 백엔드 API(`http://localhost:4700`)에 연결됩니다.

### Extensions (선택)

임베딩·리랭킹은 백엔드 내장 경로로도 동작하므로 필수는 아닙니다. 분리·확장할 때만 띄우세요.

```bash
cd extensions/embedding_server && docker compose up -d --build   # :8080
cd extensions/reranker_server  && docker compose up -d --build   # :8081
```

## 브랜치 & 커밋 컨벤션

여러 사람이 함께 작업하다 보면 변경 이력을 알아보기 쉽게 정리하는 약속이 필요합니다.
브랜치 이름과 커밋 메시지를 아래 형식에 맞춰 주시면 리뷰와 추적이 훨씬 수월해집니다.

### 브랜치

`main` 에 직접 커밋하지 말고, 작업할 내용별로 작업용 브랜치를 따로 만들어 주세요.

```
feature/<요약>     # 기능 추가
fix/<요약>         # 버그 수정
docs/<요약>        # 문서
```

### 커밋 메시지 — Conventional Commits

```
<type>(<scope>): <요약>

[본문 — 필요 시 변경 이유/맥락]
```

- **type**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`
- **scope**: 영향 영역 (예: `ingestion`, `retrieval`, `routing`, `frontend`, `agent`, `deploy`)
- 예: `feat(routing): 내용 임베딩 유사도 기반 컬렉션 자동 배정 추가`

## 코드 스타일

스타일은 취향 싸움이 아니라 도구에 맡깁니다. 아래 규칙만 통과하면 됩니다.

- **Python** — [ruff](https://docs.astral.sh/ruff/) 로 lint/format. PR 전 `make lint` 통과.
- **TypeScript** — ESLint + `tsc`. PR 전 `pnpm lint && pnpm typecheck` 통과.
- **주석** — 한국어 기본 (식별자·로그 메시지는 영문 유지).
- **라이선스 헤더** — 새 Python 파일 첫 줄에 `# SPDX-License-Identifier: Apache-2.0` 을 넣어 주세요.
- 기존 코드의 네이밍·스타일·관용구를 따라 주세요.

## 테스트

테스트는 "내 변경이 다른 곳을 망가뜨리지 않았다"는 것을 자신과 리뷰어 모두에게 보여 주는
가장 좋은 방법입니다.

- 동작 변경에는 가능한 한 테스트를 추가해 주세요.
- 백엔드 테스트는 [`backend/tests/`](backend/tests) — 외부 인프라 없이 도는 것을 원칙으로 합니다.
- HWP/HWPX 파싱 회귀 테스트는 [`samples/hwp/`](samples/hwp) 샘플을 사용합니다.
  네이티브 확장(`rhwp_py`)이 없으면 해당 케이스는 자동 skip 됩니다.
- PR 전 관련 테스트가 통과하는지 확인해 주세요.

## Pull Request 절차

여기까지 왔다면 이제 변경을 세상에 내놓을 차례입니다. 아래 순서를 따라가면 됩니다.

1. 저장소를 **Fork** 하고 작업 브랜치를 만듭니다.
2. 변경을 커밋합니다(컨벤션 준수, lint/test 통과).
3. PR 을 생성하고 [PR 템플릿](.github/PULL_REQUEST_TEMPLATE.md)을 채웁니다.
4. 관련 이슈가 있으면 `Closes #이슈번호` 로 연결합니다.
5. 리뷰 피드백에 따라 보완합니다. CI 가 통과해야 머지됩니다.

작은 단위로 나눠 주시면 리뷰가 빠릅니다.

## 버전 관리

제품 버전은 **락스텝(lockstep)** 입니다 — 백엔드·프론트엔드·에이전트·확장 서버·rhwp_py
바인딩이 모두 같은 버전을 쓰고 릴리스 때 함께 올립니다. 단일 소스는
**`backend/app/__init__.py` 의 `__version__`** 이며, 릴리스 전
`scripts/check-versions.sh` 로 불일치를 검사합니다. 자세한 규칙·절차는
[VERSIONING.md](VERSIONING.md) 를 참고하세요.

## 보안 취약점 제보

보안 취약점은 **공개 이슈로 올리지 말고** 비공개로 제보해 주세요. 자세한 절차는
[SECURITY.md](SECURITY.md) 를 참고하세요. 배포 시 `ARGUS_JWT_SECRET`,
`ARGUS_OS_SECRET_KEY` 등 운영 시크릿 설정은
[README 의 운영 보안 설정](README.md#운영-환경-보안-설정-️) 섹션을 참고하세요.

## 라이선스

기여하신 내용은 프로젝트와 동일하게 [Apache License 2.0](LICENSE) 으로 배포됩니다.
PR 을 제출함으로써 본인의 기여를 이 라이선스로 제공하는 데 동의하는 것으로 간주합니다.
