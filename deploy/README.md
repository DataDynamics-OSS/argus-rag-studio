# deploy/ — 배포 구성과 서비스별 배포 가이드

배포 방식 4종: ① systemd/shell 수동 실행 ② 에이전트+Docker(배포 API — **권장**)
③ 수동 Docker ④ K8S. 방식별 비교와 선택 기준은 아래 서비스별 가이드 각 문서의 도입부 참조.

## 서비스별 가이드

| 서비스 | 기본 포트 | 권장 배포 방식 | 가이드 |
|---|---|---|---|
| **에이전트** (부트스트랩 — 수동 설치 필수) | 4501 | systemd | [agent-deployment.md](agent-deployment.md) |
| 워커(인제스천) | - | systemd(체크아웃 호스트) / Docker(원격·에어갭) | [workers-deployment.md](workers-deployment.md) |
| 임베딩 서버 | 8080 | Docker(플랫폼 배포) | [embedding-server-deployment.md](embedding-server-deployment.md) |
| 리랭커 서버 | 8081 | Docker(플랫폼 배포) | [reranker-server-deployment.md](reranker-server-deployment.md) |
| 검출 서버 | 8082 | Docker(플랫폼 배포) | [detection-server-deployment.md](detection-server-deployment.md) |
| HWP 렌더 서버 | 8085 | Docker(플랫폼 배포) | [hwp-render-server-deployment.md](hwp-render-server-deployment.md) |
| VLM 서버(vLLM) | 8000 | Docker(플랫폼 배포 — arm64는 NGC 이미지 자동 전환) | [vlm-server-deployment.md](vlm-server-deployment.md) |

## 공통 규약 요약

- **Docker 수동 배포도 탐색되게**: 이름 `argus-rag-<kind>-<N>` + 라벨 `argus.kind=<kind>`
  (에이전트 설치 호스트 한정 — 서비스 관리 탭 자동 노출).
- **systemd 수동은 worker 만** 에이전트 탐색 지원(unit 이름 `argus-rag-worker-<N>`).
  서버형(임베딩/리랭커/검출)은 heartbeat env(`ARGUS_HEARTBEAT_URL`)로 관측.
- 수동 배포는 설정 자동 주입(wire_settings)이 없다 — `*.server_url` 을 직접 맞출 것.
- **모델 준비**(수동 배포 서버): 온라인은 첫 기동 시 자동 다운로드, 에어갭은 Model
  Repository(argus-models) 팩을 수동 전개 — 레이아웃이 kind 별로 다르다(임베딩/리랭커
  = hf-cache 구조, VLM = flat, 검출 = 엔진 캐시 복사). 각 가이드의 "모델 준비" 절 참조.

## 패키지 배포 (systemd/shell — production, 비 Docker) — 상세: [packaging.md](packaging.md)

git 체크아웃 없이 배포하는 **tar/deb/rpm 패키지**: `make packages` (또는
`make package COMP=backend OPTS="--deb --rpm"`) → `dist/argus-rag-studio-<comp>-<V>.tar.gz`
[+ `.deb`/`.rpm`]. tar 는 대상 서버에서 전개 후 `sudo ./install.sh` 가 venv 생성·의존성
설치·설정 전개·systemd 유닛 등록까지 수행한다(`--workers N`·`--variant gpu-torch`·
`--prefix` 옵션은 install.sh 헤더 참조). deb/rpm 은 같은 페이로드를 OS 패키지로 감싼
것 — postinst 가 동일 install.sh 를 실행하고, 제거(purge) 시 venv 등 생성물까지 정리한다
(유닛 자동 시작은 하지 않음 — 설정 확인 후 `systemctl enable --now`).
에어갭은 빌드 시 `OPTS=--with-deps` 로 의존성 wheel 을 동봉해 오프라인 설치.
대상: backend(API+워커)·agent·embedding/reranker/detection 서버.
HWP 렌더는 Chromium 의존이라 Docker 전용, 프론트엔드 패키징은 백로그.

## 이미지 조달 (자체 빌드 vs 업스트림, Docker Hub·zot)

무엇을 우리가 빌드해 배포하고(자체 5종 — backend·embedding·reranker·detection·hwp-render),
무엇을 업스트림 그대로 참조하는지(vLLM·PostgreSQL·MinIO·zot), 에어갭 반입(2-zot 미러)과
이미지가 아닌 배포물(에이전트·모델·rhwp wheel)은
[upstream-images-deployment.md](upstream-images-deployment.md) 참조.

## 구성 파일

- `docker-compose.infra.yml` — postgres/minio 인프라(부트스트랩 — 추론 서비스는 플랫폼 배포)
- `docker-compose.backend.yml` — 백엔드 API 컨테이너(부트스트랩 — 백엔드는 자기 자신을 배포 못 함)
