# Argus RAG Studio — zot OCI 레지스트리 (에어갭)

에이전트가 Docker로 배포하는 이미지(`argus-rag-studio-*`)를 보관·서빙하는 **경량 OCI 레지스트리**.
폐쇄망(airgap) 반입이 쉬운 [zot](https://zotregistry.dev)을 사용한다.

## 구성

```
zot-registry/
├── docker-compose.yml      # zot 서비스 (포트 5000, 영속 볼륨)
├── config/
│   ├── config.json         # 기본(무인증) — dedupe/gc + search/ui 확장
│   ├── config.auth.json    # htpasswd 인증 + accessControl (CI push, 익명 read)
│   └── config.sync.json    # 에어갭측: 빌드측 zot 를 주기 미러(sync 확장)
└── Makefile                # up/down/logs/catalog/ls
```

## 빠른 시작

```bash
cd extensions/zot-registry
docker compose up -d          # http://localhost:5000 (UI: /v2/_catalog, search 확장)
make catalog                  # 저장소 목록
```

- **amd64**: 기본 이미지(`ghcr.io/project-zot/zot-linux-amd64`).
- **arm64(DGX Spark 등)**: `ZOT_IMAGE=ghcr.io/project-zot/zot-linux-arm64:latest docker compose up -d`.
- 운영은 `ZOT_IMAGE` 를 특정 버전으로 핀(예: `:v2.1.1`). 포트는 `ZOT_PORT`, 설정 파일은 `ZOT_CONFIG` 로 교체.

## push / pull

```bash
# 빌드 이미지를 zot 로 push (배포 카탈로그 경로 규약: argus/argus-rag-studio-<kind>)
docker tag argus-rag-studio-embedding-server:0.4.2-gpu \
  localhost:5000/argus/argus-rag-studio-embedding-server:0.4.2-gpu
docker push localhost:5000/argus/argus-rag-studio-embedding-server:0.4.2-gpu

# 또는 buildx bake 가 직접 push (image-pipeline.md)
VERSION=0.4.2 REGISTRY=zot.airgap.local:5000/argus docker buildx bake --push
```

RAG Studio 배포 설정: **`deploy.image_registry = <zot-host>:5000/argus`** (servermgr `image_for` 가 이 경로로 이미지를 만든다).

## 무TLS 접근(개발/내부망)

TLS 없이 쓰면 각 에이전트/빌더 호스트의 Docker 데몬에 insecure-registry 등록이 필요하다.
```json
// /etc/docker/daemon.json
{ "insecure-registries": ["zot.airgap.local:5000"] }
```
운영 권장: zot 에 TLS 적용(아래) + 사내 CA 신뢰.

### TLS (권장)
`certs/`에 `server.cert`/`server.key`(+CA) 두고 마운트, `config.json` 의 `http` 에 추가:
```json
"http": { "address": "0.0.0.0", "port": "5000",
  "tls": { "cert": "/etc/zot/certs/server.cert", "key": "/etc/zot/certs/server.key" } }
```
docker-compose.yml 의 `./certs:/etc/zot/certs:ro` 마운트 주석 해제.

### 인증 (선택)
```bash
make auth-user USER=ci PASS=secret           # config/htpasswd 생성(htpasswd -bB)
ZOT_CONFIG=config.auth.json docker compose up -d
docker login zot.airgap.local:5000           # CI/푸시 측
```

## 에어갭 전송 (빌드측 → 폐쇄망)

zot 는 OCI 그대로라 두 경로 모두 가능(둘 다 **멀티아키 매니페스트 보존** = `--all`).

**A. 부분/단방향 연결 — sync 미러(폐쇄망측 zot)**
`config.sync.json` 의 `registries[].urls` 를 빌드측 zot 로 지정 후 기동:
```bash
ZOT_CONFIG=config.sync.json docker compose up -d   # 빌드측 argus/** 를 주기 미러
```

**B. 완전 폐쇄 — OCI 아카이브 매체 반입**
```bash
# 빌드존: 매니페스트 그대로 추출
skopeo copy --all \
  docker://zot-build:5000/argus/argus-rag-studio-embedding-server:0.4.2-gpu \
  oci-archive:embedding-0.4.2-gpu.tar
# 매체로 반입 후 폐쇄망 zot 로 적재
skopeo copy --all \
  oci-archive:embedding-0.4.2-gpu.tar \
  docker://zot.airgap.local:5000/argus/argus-rag-studio-embedding-server:0.4.2-gpu
```

> **모델은 이미지에 동봉하지 않는다.** embedding/reranker 등은 런타임에 모델을 named volume(`argus-rag-*-models`)으로 받는다(이미지 경량 유지). 폐쇄망에서 모델이 필요하면 해당 볼륨만 별도로 반입한다.

## 변형(variant) 규약 요약
- amd64 GPU: `:<ver>-gpu` (onnxruntime-gpu/fastembed, 권장)
- arm64/Blackwell GPU(DGX Spark): `:<ver>-gpu-torch` (torch cu128)
- CPU/단일: `:<ver>`
