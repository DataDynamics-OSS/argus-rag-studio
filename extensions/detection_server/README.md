# Argus 검출 서버 (Detection Server)

어노테이션 편집기의 **자동 bbox 인식**을 담당하는 독립 마이크로서비스입니다.
[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)(det+rec)로 이미지에서 텍스트
영역의 bbox 와 인식 텍스트를 검출해, RAG Studio 백엔드를 통해 편집기에 **후보 박스**로
전달합니다. 자동 결과는 확정이 아니라 초안이며, 사람이 검수·수정합니다(human-in-the-loop).

`embedding_server` / `reranker_server` 와 동일한 패키징·설정·로깅 패턴을 따릅니다.

## 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/v1/detect` | 이미지(멀티파트) → 텍스트 bbox + 텍스트 + 신뢰도 |
| `GET`  | `/health`   | 헬스체크 |

### `POST /v1/detect`

멀티파트 폼:

| 필드 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `file` | file | (필수) | 이미지 바이트(png/jpg/webp/bmp/tiff) |
| `lang` | str | 서버 설정 | PaddleOCR 언어 코드(`korean`/`en`/`ch`/`japan` ...) |
| `min_score` | float | 서버 설정 | 신뢰도 임계값(이 미만 박스 제외). `<0` 이면 서버 기본 |
| `with_text` | bool | `true` | `false` 면 검출만(텍스트 빈 문자열) |

응답:

```json
{
  "boxes": [
    {"x1": 10, "y1": 20, "x2": 120, "y2": 60, "text": "안녕하세요", "score": 0.97}
  ],
  "width": 640,
  "height": 480
}
```

좌표는 **원본 이미지 픽셀 기준 축정렬(AABB)** 사각형이며, 읽기 순서(위→아래, 좌→우)로 정렬됩니다.

## 실행

### 로컬(개발)

```bash
cd detection_server
make dev          # 의존성 설치(paddleocr/paddlepaddle 포함 — 다소 무겁습니다)
make run-uvicorn  # http://localhost:8082 (자동 리로드)
```

### Docker

```bash
cd detection_server
docker compose up -d --build
```

최초 요청 시 PaddleOCR 모델을 자동 다운로드합니다(`/models` 볼륨에 캐시).
`DETECT_PRELOAD=true` 면 기동 시 기본 언어 모델을 미리 로딩합니다.

## 배포 (이미지 파이프라인 · 에이전트)

배포 이미지 이름은 `argus-rag-studio-<kind>-server:<tag>[-variant]` 규약을 따른다(이 서버는 kind=`detection`).
변형(variant)은 태그 접미사로 표현한다: CPU=접미사 없음, GPU=`-gpu`. (검출 서버는 GPU 변형이 `gpu` 단일이며 `gpu-torch` 는 없다.)

- **이미지 빌드(로컬)**: `make image KIND=detection [VARIANT=gpu]` (리포 루트에서 실행).
- **멀티아키 빌드·푸시**: `VERSION=<v> REGISTRY=<zot>/argus make images-push`.
  - 예) `argus-rag-studio-detection-server:latest`(CPU), `:latest-gpu`(GPU).
- **레지스트리**: zot(`extensions/zot-registry/`). 에어갭(폐쇄망) 반입 절차는 `extensions/zot-registry/README.md` 참고.
- **원격 배포**: RAG Studio "에이전트" 화면 → 서비스/배포에서 kind=`detection` 선택 → 각 호스트의 Argus RAG Studio Agent(:4501)가 Docker 로 컨테이너를 기동한다.
  배포가 완료되면 해당 서버의 URL 이 RAG Studio 설정 `detection.server_url` 에 자동 주입된다.

## 설정

`packaging/config/config.yml` + `config.properties`(변수 치환) 또는 `DETECT_*` 환경변수로 설정합니다.
환경변수가 config 값보다 우선합니다.

| 환경변수 | config 키 | 기본 | 설명 |
|----------|-----------|------|------|
| `DETECT_HOST` | `server.host` | `0.0.0.0` | 바인드 호스트 |
| `DETECT_PORT` | `server.port` | `8082` | 바인드 포트 |
| `DETECT_API_KEY` | `detection.api_key` | `changeme` | 인증 키(빈값=무인증) |
| `DETECT_LANG` | `detection.lang` | `korean` | 기본 PaddleOCR 언어 |
| `DETECT_USE_GPU` | `detection.use_gpu` | `false` | GPU 사용(별도 `paddlepaddle-gpu` 필요) |
| `DETECT_MIN_SCORE` | `detection.min_score` | `0.5` | 신뢰도 임계값 |
| `DETECT_MAX_IMAGE_MB` | `detection.max_image_mb` | `20` | 입력 이미지 최대 크기(MB) |
| `DETECT_PRELOAD` | `detection.preload` | `false` | 기동 시 모델 프리로드 |

## RAG Studio 연결

백엔드 `config`(`app/core/config.py` → `config.yml`)의 `detection` 섹션에서 이 서버를 가리킵니다.

```yaml
detection:
  enabled: true
  server_url: http://localhost:8082
  api_key: changeme        # 이 서버의 DETECT_API_KEY 와 동일
  lang: korean
  min_score: 0.5
```

활성화하면 어노테이션 편집기에 **자동 인식** 버튼이 동작합니다.

## 손글씨 정확도 참고

PaddleOCR 기본 모델은 **인쇄체에 강하고 손글씨는 정확도가 낮을 수 있습니다.** 손글씨
데이터셋(AI-Hub)이 주 대상이라면:

- `with_text=false`(검출 전용)로 bbox 만 자동 채우고 텍스트는 사람이 입력하거나,
- 손글씨 도메인에 맞춰 파인튜닝한 PaddleOCR det/rec 모델로 교체하거나(엔진의 `_load` 에서
  `rec_model_dir`/`det_model_dir` 지정),
- 사내 VLM 검출 모델을 동일한 `/v1/detect` 계약으로 감싸 이 서버를 대체할 수 있습니다.

자동 결과는 항상 편집기에서 **후보**로만 들어가며 저장 전 사람이 검수합니다.
## 메트릭 (원격 모니터링)

| 엔드포인트 | 형식 | 용도 |
|---|---|---|
| `GET /stats` | JSON | 시스템(CPU/RAM/디스크)·GPU·요청·모델 스냅샷 — Argus '잡 모니터링 > 외부 서버' 탭이 폴링 |
| `GET /metrics` | Prometheus 텍스트 | Prometheus/Grafana 스크레이프 |

- 시스템 메트릭은 `psutil`(requirements 포함), **GPU 메트릭은 `nvidia-ml-py`**(requirements-gpu 포함)로 수집한다.
  미설치/CPU 환경에서는 해당 항목만 생략하고 엔드포인트는 항상 200을 반환한다(graceful).
- 값은 1.5초 캐시(스크레이프 폭주 방지), 요청 카운터는 항상 최신.
