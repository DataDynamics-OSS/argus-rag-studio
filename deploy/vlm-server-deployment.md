# VLM 서버 배포 가이드 (vLLM)

- **역할**: 이미지 분류·내용 인식용 비전-언어 모델 서빙(OpenAI 호환 `/v1`)
- **런타임**: vLLM · **기본 포트**: 8000
- **설정 연결**: 전역 `image_classification.server_url`(`/v1` 포함) + `.model`(served-model-name 일치 필수)
- **모델**: 레지스트리(모델 관리) 등록 → Model Repository(argus-models) 반입 → 볼륨 설치(flat 레이아웃).
  온라인 개발망은 HF 직접 다운로드 폴백 가능.
- **관측**: heartbeat 채널은 없지만 백엔드가 `image_classification.server_url` 로
  `/v1/models`·`/metrics` 를 프로브한다 — 관리형(규약 Docker)이면 그 행에 모델·버전·
  GPU 지표가 병합되고, 수동/네이티브 배포도 서비스 관리에 **MANUAL 행**으로 관측된다.

## 방법 1 — 플랫폼 배포 (권장)

**에이전트 > 서비스/배포**(kind=vlm, 모델 콤보에서 레지스트리 모델 선택) 또는
`POST /api/v1/deploy`. 보유 검증 → 에이전트 모델 설치 → `HF_HUB_OFFLINE=1` 오프라인
서빙 + `image_classification.*` 설정 주입까지 자동. 컨테이너는 `--ipc host` 로 뜬다
(vLLM 공유메모리 요구 — kind 규약에 내장).

> **arm64/GB10(DGX Spark)**: 기본 이미지 `vllm/vllm-openai` 는 x86 전용이라, 호스트
> arch 가 arm64 면 백엔드가 **자동으로** NGC 이미지(`deploy.vlm_image_arm64`, 기본
> `nvcr.io/nvidia/vllm:26.02-py3`)로 전환하고 entrypoint 차이(`nvidia_entrypoint.sh`)에
> 맞춰 `vllm serve` 커맨드 prefix 도 자동 처리한다 — **모델만 선택하면 amd64/arm64
> 동일하게 배포**. 에어갭은 설정 키를 zot 미러 주소로 교체.
> 고급 제어(예: `--gpu-memory-utilization 0.3` — 공유 GPU 배려)는 env `VLLM_ARGS` 로
> 커맨드 전체를 지정(이 경우 `image_classification.model` 자동 주입은 생략 — 직접 확인).

## 방법 2 — 수동 Docker

```bash
# amd64(intel) — 공식 이미지(entrypoint 가 vllm serve 라 인자만 넘김)
docker run -d --name argus-rag-vlm-1 --label argus.kind=vlm \
  --restart unless-stopped --gpus all --ipc host -p 8000:8000 \
  -v argus-rag-vlm-models:/models -e HF_HOME=/models -e HF_HUB_OFFLINE=1 \
  vllm/vllm-openai:latest \
  --model /models/qwen2-vl-7b --served-model-name qwen2-vl-7b --max-model-len 8192

# arm64(GB10 등) — NGC 이미지(entrypoint 가 nvidia_entrypoint.sh 라 커맨드 전체 지정)
docker run -d --name argus-rag-vlm-1 --label argus.kind=vlm \
  --restart unless-stopped --gpus all --ipc host -p 8000:8000 \
  -v argus-rag-vlm-models:/models -e HF_HOME=/models -e HF_HUB_OFFLINE=1 \
  nvcr.io/nvidia/vllm:26.02-py3 \
  vllm serve /models/qwen2-vl-7b --served-model-name qwen2-vl-7b --max-model-len 8192

# 온라인 개발망: HF 에서 직접 받게 하려면 HF_HUB_OFFLINE 을 빼고 모델에 repo id
#   (예: Qwen/Qwen2-VL-7B-Instruct)
```

## 방법 3 — systemd 직접 실행 (비컨테이너)

컨테이너를 쓸 수 없는 정책/환경에서만 사용(arm64 도 NGC 이미지가 있으므로 아키텍처 때문에 필요하지는 않다 — 방법 1·2 권장).

```bash
python3 -m venv /opt/vllm-venv && /opt/vllm-venv/bin/pip install vllm
```

```ini
# /etc/systemd/system/argus-vlm-server.service
[Unit]
Description=Argus VLM Server (vLLM)
After=network-online.target

[Service]
ExecStart=/opt/vllm-venv/bin/vllm serve Qwen/Qwen2-VL-7B-Instruct \
  --served-model-name qwen2-vl-7b --max-model-len 8192 --port 8000
Environment=HF_HOME=/var/lib/argus-vlm/models
# 에어갭(모델 사전 반입 시): Environment=HF_HUB_OFFLINE=1 + ExecStart 의 모델을 로컬 경로로
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now argus-vlm-server
```

## 방법 4 — shell 직접 실행

```bash
. /opt/vllm-venv/bin/activate
vllm serve Qwen/Qwen2-VL-7B-Instruct --served-model-name qwen2-vl-7b \
  --max-model-len 8192 --port 8000                              # 포그라운드
nohup vllm serve ... > /var/log/argus-vlm.log 2>&1 &            # 백그라운드
```

> 방법 3·4 도 `image_classification.server_url=http://<host>:8000/v1` 을 설정하면
> 프로브로 관측되어 서비스 관리에 MANUAL 행으로 보인다(라이프사이클 제어는 불가).
> `image_classification.model=<served-model-name>` 도 직접 설정할 것.
> 가능하면 방법 1·2(Docker 규약 — 관리형)로 전환을 권장.

## 모델 준비 (수동 배포 서버)

**온라인**: 준비 불필요 — `--model <HF repo id>` 로 기동하면 `HF_HOME` 에 자동 다운로드
(Qwen2-VL-7B 기준 ~16GB, 첫 기동이 오래 걸림). **에어갭**: Model Repository 팩을
**flat 구조**(디렉터리 그대로 — vLLM 로컬 경로 서빙)로 전개한다:

```bash
mc alias set argus http://<minio-host>:9000 <access-key> <secret-key>
mc cp argus/argus-models/vlm/qwen2-vl-7b/main/model.tar.zst .
echo "$(mc cat argus/argus-models/vlm/qwen2-vl-7b/main/manifest.json | jq -r .sha256)  model.tar.zst" | sha256sum -c

# flat 전개 — 모델 파일이 디렉터리에 바로 풀린다(팩 루트 = 스냅샷 내용물)
MODELS=/var/lib/argus-vlm/models          # Docker 면 argus-rag-vlm-models 볼륨의 Mountpoint
mkdir -p $MODELS/qwen2-vl-7b
tar --use-compress-program=unzstd -xf model.tar.zst -C $MODELS/qwen2-vl-7b   # .tar.gz 면 tar xzf

# 로컬 경로 서빙 + 오프라인 강제
HF_HUB_OFFLINE=1 vllm serve $MODELS/qwen2-vl-7b --served-model-name qwen2-vl-7b \
  --max-model-len 8192 --port 8000
```

수동 Docker(방법 2) + 에이전트 호스트라면 전개를 에이전트에 위임 가능:
`POST :4501/api/v1/model/install` (layout=flat, 표준 볼륨 대상 — 플랫폼 배포와 동일 경로).

## 옵션 레퍼런스 (vLLM 주요 인자·env)

**`vllm serve` 인자** (전체는 `vllm serve --help`):

| 인자 | 예시/기본 | 설명 |
|---|---|---|
| `--model` (위치 인자) | `/models/qwen2-vl-7b` 또는 HF repo id | 로컬 경로(에어갭) 또는 HF repo(온라인 다운로드) |
| `--served-model-name` | qwen2-vl-7b | API 가 노출하는 모델 이름 — **백엔드 `image_classification.model` 과 반드시 일치** |
| `--max-model-len` | 8192 | 컨텍스트 길이 상한. 레지스트리 `max_len` 값과 일치 권장 — 클수록 VRAM 소모 증가 |
| `--port` | 8000 | 리슨 포트 |
| `--gpu-memory-utilization` | 0.9 | GPU 메모리 사용 비율(0~1). 같은 GPU 를 다른 서비스와 공유하면 낮춘다(예: 0.5) |
| `--tensor-parallel-size` | 1 | 다중 GPU 텐서 병렬 수 — 대형 모델(32B+)에서 사용 |
| `--dtype` | auto | 가중치 정밀도(auto/bfloat16/float16) — 구형 GPU 호환 문제 시 float16 |
| `--api-key` | (없음=무인증) | OpenAI 호환 API 키 — 설정 시 백엔드 `image_classification.api_key` 도 동일 지정 |

**환경변수**:

| env | 설명 |
|---|---|
| `HF_HOME` | 모델 캐시 루트(플랫폼 배포는 `/models` 볼륨 — 온라인 다운로드도 여기 캐시) |
| `HF_HUB_OFFLINE=1` | HF 접근 차단(에어갭 강제) — 미보유 모델이면 즉시 오류로 드러남 |
| `VLLM_ARGS` | (플랫폼 배포 한정) 서빙 인자 전체를 교체하는 override |

**백엔드 설정(플랫폼 배포)**:

| 키 | 기본값 | 설명 |
|---|---|---|
| `deploy.vlm_image_arm64` | nvcr.io/nvidia/vllm:26.02-py3 | arm64 호스트 자동 선택 이미지 — 에어갭은 zot 미러 주소로 교체 |
| `deploy.image_registry` / `deploy.image_tag` | (빈값) / latest | amd64 기본 이미지(vllm/vllm-openai)의 레지스트리/태그 규약 |

## 검증

```bash
curl -s http://<host>:8000/v1/models | jq '.data[].id'   # served-model-name 확인
# 이미지 분류 E2E: 이미지 포함 문서 인제스천 후 image_types 메타데이터 확인
```
