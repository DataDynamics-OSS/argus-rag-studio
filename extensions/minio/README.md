# Argus RAG Studio — MinIO (오브젝트 스토리지, 에어갭)

RAG Studio의 원본 문서·어노테이션/분류 이미지를 저장하는 **S3 호환 오브젝트 스토리지**.
폐쇄망(airgap)에 반입하기 쉽도록 단일 RELEASE 태그로 고정해 배포한다.

## 라이선스 (에어갭에서 중요)

- MinIO 커뮤니티 서버는 **AGPL-3.0** — **내부/에어갭 운영에 라이선스 비용이 없다.**
  AGPL 의 copyleft 의무는 *수정본을 외부(제3자)에 배포/네트워크 제공*할 때 발생하며,
  **변경 없이 사내에서 운영만** 하는 경우 실질적 제약이 없다.
- 본 구성은 **`:latest` 대신 RELEASE 태그를 고정**한다 — (1) 에어갭 재현성, (2) 라이선스/버전 명확화,
  (3) **풀 웹 콘솔**(2025-05 콘솔 기능 축소 이전 RELEASE) 확보.
- 정책상 copyleft 자체를 피해야 하면 Apache-2.0 대안(SeaweedFS·Garage 등)을 검토할 수 있으나,
  RAG Studio 기본 연동은 MinIO(S3 API) 기준이다.

## 구성

```
minio/
├── docker-compose.yml   # minio(:9000 API, :9001 콘솔) + createbuckets(mc 초기화)
├── .env.example         # 이미지 태그·자격증명·포트
└── Makefile             # up/down/logs/ls/buckets
```

## 빠른 시작

```bash
cd extensions/minio
cp .env.example .env        # 이미지 태그/자격증명 확인·수정 (에어갭: 사내 미러 태그로 교체)
docker compose up -d        # minio 기동 + 버킷 자동 생성
# API: http://localhost:9000   콘솔: http://localhost:9001  (minioadmin/minioadmin)
make ls                     # 버킷 확인
```

`createbuckets` 가 RAG Studio 기본 버킷을 멱등 생성한다:
- `rag-documents` — 원본 문서 (`object_storage.bucket`)
- `annotation-images` — 어노테이션 이미지 (`object_storage.annotation_bucket`)
- `classification-images` — 분류 이미지 (`object_storage.classification_bucket`)

## RAG 백엔드 연결

`backend` 의 `object_storage.*`(또는 env `ARGUS_…`)를 이 MinIO 로 맞춘다(기본값이 이미 일치):
```
os.endpoint=http://<minio-host>:9000
os.access_key=minioadmin       # MINIO_ROOT_USER 와 동일
os.secret_key=minioadmin       # MINIO_ROOT_PASSWORD 와 동일
os.use_ssl=false
os.bucket=rag-documents
os.annotation_bucket=annotation-images
os.classification_bucket=classification-images
```
운영에선 자격증명을 반드시 변경하고, 백엔드 설정과 일치시킨다.

## 에어갭 이미지 반입

`:latest` 가 아니라 **고정 태그**를 미러한다(멀티아키 보존 `--all`). zot(`../zot-registry/`)과 동일 패턴:
```bash
# 빌드존 → 매체
skopeo copy --all docker://minio/minio:RELEASE.2025-04-22T22-12-26Z oci-archive:minio.tar
skopeo copy --all docker://minio/mc:RELEASE.2025-04-16T18-13-26Z    oci-archive:mc.tar
# 폐쇄망(사내 zot 로 적재) 후 .env 의 MINIO_IMAGE/MC_IMAGE 를 사내 경로로 교체
skopeo copy --all oci-archive:minio.tar docker://zot.airgap.local:5000/argus/minio:RELEASE.2025-04-22T22-12-26Z
```

## 데이터·백업

- 데이터는 named volume `minio-data`(`/data`)에 영속. 컨테이너 재생성에도 유지.
- 백업: `mc mirror` 또는 볼륨 스냅샷. 폐쇄망 이전 시 `/data` 디렉터리를 그대로 복제해도 된다.

> 개발용 통합 인프라는 `deploy/docker-compose.infra.yml`(PostgreSQL+MinIO 포함)에도 있으나,
> 이 디렉터리는 **MinIO 단독·고정 태그·에어갭** 배포용 구성이다.
