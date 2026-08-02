# 패키징 가이드 — systemd/shell(비 Docker) production 배포

git 체크아웃 없이 배포하는 패키지 체계. Docker 배포(에이전트 배포 API — 권장)와
이미지 조달([upstream-images-deployment.md](upstream-images-deployment.md))의 보완 채널로,
**컨테이너를 쓸 수 없는 production 호스트·에어갭 환경**을 대상으로 한다.
빌더는 `scripts/package.sh`(단일 진실원천 — 이 문서와 어긋나면 스크립트 헤더가 정본).

## 1. 형식 × 컴포넌트

| 형식 | 용도 | 산출물 |
|---|---|---|
| **tar** | 범용(수동 전개 + `install.sh`) | `dist/argus-rag-studio-<comp>-<V>.tar.gz` |
| **deb** | Debian/Ubuntu (`dpkg -i`) | `dist/argus-rag-studio-<comp>_<V>_<arch>.deb` |
| **rpm** | RHEL 계열 (`rpm -i`) — 빌드에 rpmbuild 필요 | `dist/argus-rag-studio-<comp>-<V>-1.<arch>.rpm` |

| 컴포넌트 | 패키징 방식 | systemd 유닛 |
|---|---|---|
| `backend` | wheel | `argus-rag-studio-server`(API) + `argus-rag-worker-<N>`(--workers N — 에이전트 탐색 규약 이름, `ARGUS_WORKER_RUNTIME=systemd` 자기 보고) |
| `agent` | wheel | `argus-rag-studio-agent` |
| `embedding`/`reranker`/`detection` | 소스 모듈(pyproject 없음) | `argus-rag-studio-<c>-server` |

HWP 렌더는 Chromium 의존이라 **Docker 전용**, 프론트엔드 패키징은 백로그.
`<V>` 는 락스텝 제품 버전([VERSIONING.md](../VERSIONING.md))이 자동 반영된다.

## 2. 빌드

```bash
make packages                                        # 전체(tar)
make package COMP=backend                            # 단일(tar)
make package COMP=backend OPTS="--deb --rpm"         # + OS 패키지
make package COMP=embedding OPTS="--with-deps gpu-torch --deb"   # 에어갭 + 변형
```

- `--with-deps [cpu|gpu|gpu-torch]`: 의존성 wheel 을 `wheels/` 에 동봉 → 오프라인 설치.
  wheel 은 **빌드 호스트의 아키/파이썬 기준** — 대상 서버와 같은 플랫폼에서 빌드할 것.
  동봉 시 deb/rpm 아키 표기도 호스트 아키로 바뀐다(기본 all/noarch).
- 패키지 구성: `install.sh` + (wheel | 모듈 소스) + `requirements*.txt` + `config/` +
  `systemd/`(+ backend 는 스키마 DDL 동봉).

## 3. 설치 / 제거

**tar**: 대상 서버에서 전개 후
```bash
sudo ./install.sh [--prefix /opt/argus-rag-studio] [--variant gpu-torch] \
                  [--workers N] [--python python3.11] [--no-enable]
```
Python 3.11+ 확인 → `<prefix>/<comp>/venv` 생성 → 의존성 설치(`wheels/` 있으면
`--no-index` 오프라인) → 설정 전개(**기존 config 보존**, 새 기본값은 `*.new`) →
systemd 유닛 렌더·등록·기동(`--no-enable` 시 등록만).

**deb/rpm**: `dpkg -i <pkg>.deb` / `rpm -i <pkg>.rpm`
- 페이로드는 `/opt/argus-rag-studio/dist/<name>/` 에 설치되고, postinst(%post)가 동봉
  install.sh 를 `--no-enable` 로 실행한다 — **유닛 자동 시작 없음**. 설정
  (`/opt/argus-rag-studio/<comp>/config`) 확인 후 `systemctl enable --now <유닛>`.
- 워커 수 조정 등 옵션이 필요하면 설치 후
  `/opt/argus-rag-studio/dist/<name>/install.sh --workers 4` 재실행(멱등).
- 제거: `dpkg -P` / `rpm -e` — 유닛 정지·제거 + venv 등 생성물(`/opt/argus-rag-studio/<comp>`)까지 정리.

## 4. 설치 후 확인

- 유닛 상태: `systemctl status argus-rag-studio-server argus-rag-worker-1 …`
- 버전: 백엔드 `GET /health`, 확장 서버 `GET /stats` — 락스텝 버전과 일치해야 한다
  (`scripts/check-versions.sh` 기준). RAG Studio 화면(서비스 관리·잡 모니터링)에서도 확인.
- systemd 수동 배포 서버는 배포 API 관리 대상이 아니다 — 관측 연결(heartbeat env /
  설정 URL)은 각 서비스 배포 가이드([README](README.md) 표) 참조.

## 5. 알려진 공존/제약

- `agent/packaging/debian/`(debhelper 정식 deb, `make -C agent deb`)은 generic 패키징과
  **공존** — 정식 배포 채널 확정 시 하나로 정리 예정. Maintainer 는 두 체계 모두
  `support@data-dynamics.io`.
- rpm 은 Ubuntu 빌드 호스트에서 생성은 되지만 설치 검증은 rpm 계열 호스트에서 필요.
- deb/rpm 의 postinst 는 네트워크로 PyPI 를 받는다(오프라인은 `--with-deps` 패키지 사용).
