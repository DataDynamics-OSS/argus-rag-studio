# 이미지 조달 가이드 — 자체 빌드 vs 업스트림, 레지스트리 채널

우리가 Docker 로 배포하는 구성요소는 두 부류다. **자체 빌드 이미지**(코드가 들어가는 것)와
**업스트림 이미지**(그대로 참조하는 것). 이 문서는 "무엇을 어디서 받아 어떻게 옮기는가"를
정리한다. 서비스별 실행 방법은 각 배포 가이드([README](README.md) 표) 참조.

## 1. 자체 빌드 이미지 (5종 — `docker-bake.hcl` 이 단일 진실원천)

| 이미지 | 태그(변형) | 아키 | 비고 |
|---|---|---|---|
| `argus-rag-studio-backend` | `{V}` | amd64+arm64 | API·워커 겸용(command 로 분기) |
| `argus-rag-studio-embedding-server` | `{V}` / `{V}-gpu` / `{V}-gpu-torch` | gpu(onnx)는 amd64 전용 | |
| `argus-rag-studio-reranker-server` | 동일 3종 | 동일 | |
| `argus-rag-studio-detection-server` | `{V}` / `{V}-gpu` | amd64+arm64 | |
| `argus-rag-studio-hwp-render-server` | `{V}` | amd64+arm64 | rhwp 버전 정책: `scripts/check-rhwp-version.sh` |

`{V}` = RAG Studio 버전(`backend/app/__init__.py`). **모델은 이미지에 동봉하지 않는다**
(모델 레지스트리 팩 — §4).

배포 채널 2개:

- **Docker Hub(공개 배포 채널)** — 단일 리포 `datadynamics/argus-rag-studio` 에
  **태그로 컴포넌트를 구분**해 올린다(플랜의 리포 수 제약 대응):
  `argus-rag-studio:<컴포넌트>-<버전>[-변형]` (예: `backend-0.1.1`,
  `embedding-server-0.1.1-gpu-torch`, `hwp-render-server-latest`).
  ```bash
  VERSION=<V> FLAT_REPO=datadynamics/argus-rag-studio make images-push
  ```
  공개 리포 정책(2026-07-12 결정) — 이미지에 소스가 포함되므로 공개 범위 변경 시
  리포 공개설정과 함께 재검토. 비인증 pull rate limit 이 있으므로 운영 pull 은
  로그인 또는 zot 미러 경유.
- **zot(에어갭 정본)** — 폐쇄망 배포의 기준 레지스트리.
  ```bash
  VERSION=<V> REGISTRY=<zot>:5000/argus make images-push   # 빌드측 zot
  ```

## 2. 업스트림 이미지 (재배포하지 않음 — 참조·미러만)

| 구성요소 | 이미지 | 사용처 | 태그 정책 |
|---|---|---|---|
| VLM(vLLM) | `vllm/vllm-openai`(amd64) / `nvcr.io/nvidia/vllm`(arm64 — `deploy.vlm_image_arm64`) | 배포 카탈로그 `vlm` kind | 버전 태그 고정([vlm 가이드](vlm-server-deployment.md)) |
| PostgreSQL | `pgvector/pgvector:pg16` | `docker-compose.infra.yml` | 메이저 태그 고정(pg16) |
| MinIO | `minio/minio` | `docker-compose.infra.yml` | **릴리스 태그 고정 권장** — compose 의 `latest` 는 개발 편의(운영 반입 시 특정 `RELEASE.*` 태그로 미러) |
| zot | `ghcr.io/project-zot/zot-linux-*` | `extensions/zot-registry` | 버전 태그 고정 |

이들은 Docker Hub 에 우리가 다시 올리지 않는다 — 크기·라이선스·업데이트 추적 면에서
이점이 없다. 폐쇄망은 §3 미러로 반입한다.

## 3. 에어갭 반입 절차 (2-zot 체계 — `extensions/zot-registry` 참조)

```
[인터넷] --pull--> 빌드측 zot --(sync 미러 / export·import)--> 폐쇄망측 zot --pull--> 각 호스트
```

1. **빌드측 zot 적재** (인터넷 연결 가능 호스트):
   ```bash
   # 자체 이미지: make images-push REGISTRY=<빌드측zot>:5000/argus
   # 업스트림 이미지: pull → retag → push
   docker pull pgvector/pgvector:pg16
   docker tag  pgvector/pgvector:pg16 <빌드측zot>:5000/upstream/pgvector:pg16
   docker push <빌드측zot>:5000/upstream/pgvector:pg16
   ```
   arm64 업스트림(NGC vLLM 등)은 대상 아키 호스트에서 pull 하거나
   `docker pull --platform linux/arm64` 로 받는다.
2. **폐쇄망측 zot 동기화**: 단방향 연결이 있으면 sync 미러
   (`extensions/zot-registry` 의 `config.sync.json`), 완전 단절이면 단건 반출:
   ```bash
   docker save <이미지> | gzip > img.tgz     # 반출 매체로 이동 후
   gunzip -c img.tgz | docker load && docker tag ... && docker push <폐쇄망zot>...
   ```
3. **zot 자체 부트스트랩**(닭-달걀): 레지스트리가 없는 최초 1회는 zot 이미지를
   §3-2 의 `save/load` 로 직접 반입해 기동한다.
4. 반입 후 각 참조 지점을 zot 주소로 교체 — 배포 화면의 이미지 오버라이드,
   설정 `deploy.vlm_image_arm64`, compose 의 `image:`.

## 4. 이미지가 아닌 배포물 (Docker 로 배포하지 않는 것)

| 대상 | 방법 | 가이드 |
|---|---|---|
| **에이전트** | tar 패키지(`make package COMP=agent`) 또는 pip+systemd 수동 — 부트스트랩(호스트당 1회) | [agent-deployment.md](agent-deployment.md) |
| **워커(비 Docker)** | 개발=관리형 systemd(체크아웃), production=tar 패키지(`make package COMP=backend`) | [workers-deployment.md](workers-deployment.md) |
| **모델**(임베딩/리랭커/VLM/검출) | 모델 레지스트리 팩 → Model Repository(`argus-models` 버킷) → 배포 시 대상 볼륨 자동 설치(에어갭 오프라인 서빙). 수동 서버는 각 가이드 "모델 준비" 절 | 모델 레지스트리 화면 안내 |
| **rhwp_py wheel**(백엔드 네이티브 확장) | 소스 빌드(maturin) 후 venv 설치 — 버전 정책·런북은 | `backend/native/rhwp_py/README.md` |
| **프론트엔드** | Next.js 빌드 산출물(웹서버/노드) — 이미지화는 백로그 | - |
