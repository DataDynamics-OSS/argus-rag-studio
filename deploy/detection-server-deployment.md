# 검출 서버 배포 가이드

- **역할**: 문서 이미지 텍스트 검출/인식(자동 bbox — 어노테이션·이미지 파이프라인이 사용)
- **소스**: `extensions/detection_server/` · **기본 포트**: 8082 · **인증**: `Authorization: Bearer <DETECT_API_KEY>`
- **설정 연결**: 전역 `detection.server_url` + `detection.enabled=true`
- **설정 소스**: `ARGUS_DETECTION_SERVER_CONFIG_DIR`(기본 `/etc/argus-detection-server`), **`DETECT_*` 환경변수 우선**
- **엔진**: `DETECT_ENGINE=paddleocr`(CPU 기본) | `easyocr`(GPU/torch — aarch64 는 paddle-gpu 휠 부재로 이 경로만 GPU 가능)

## 방법 1 — 플랫폼 배포 (권장)

**에이전트 > 서비스/배포**(kind=detection) 또는 `POST /api/v1/deploy`.
모델(Paddle det/rec)은 pack_model 미지원 — 에어갭은 볼륨 수동 반입(아래 "모델 준비" 절 참조).

## 방법 2 — 수동 Docker

```bash
# CPU(paddleocr)
docker run -d --name argus-rag-detection-1 --label argus.kind=detection \
  --restart unless-stopped -p 8082:8082 \
  -v argus-rag-detect-models:/models \
  -e DETECT_PORT=8082 -e DETECT_API_KEY=changeme -e DETECT_PRELOAD=true \
  -e ARGUS_HEARTBEAT_URL=http://<backend>:4700/api/v1/ext-servers/heartbeat \
  -e ARGUS_INSTANCE_URL=http://<this-host>:8082 \
  argus-rag-studio-detection-server:latest

# GPU(easyocr/torch — 예: DGX aarch64)
docker run -d --name argus-rag-detection-1 --label argus.kind=detection \
  --restart unless-stopped --gpus all -p 8082:8082 \
  -v argus-rag-detect-models:/models \
  -e DETECT_PORT=8082 -e DETECT_API_KEY=changeme -e DETECT_PRELOAD=true \
  -e DETECT_ENGINE=easyocr -e DETECT_USE_GPU=true -e DETECT_EASYOCR_LANGS=ko,en \
  argus-rag-studio-detection-server:latest-gpu
```

## 방법 3 — systemd 직접 실행 (비컨테이너)

> 에이전트의 systemd 탐색은 worker 전용 — heartbeat env 로 관측 권장.

```bash
cd /opt/argus-ext/extensions
python3 -m venv detection-venv && . detection-venv/bin/activate
pip install -r detection_server/requirements.txt          # CPU(paddleocr)
# GPU(easyocr/torch): pip install torch --index-url https://download.pytorch.org/whl/cu128
#                     pip install -r detection_server/requirements-gpu-torch.txt
```

```ini
# /etc/systemd/system/argus-detection-server.service
[Unit]
Description=Argus Detection Server
After=network-online.target

[Service]
WorkingDirectory=/opt/argus-ext/extensions
ExecStart=/opt/argus-ext/extensions/detection-venv/bin/python -m detection_server
Environment=DETECT_PORT=8082
Environment=DETECT_API_KEY=changeme
Environment=DETECT_PRELOAD=true
# GPU 시: Environment=DETECT_ENGINE=easyocr / DETECT_USE_GPU=true / DETECT_EASYOCR_LANGS=ko,en
Environment=ARGUS_HEARTBEAT_URL=http://<backend>:4700/api/v1/ext-servers/heartbeat
Environment=ARGUS_INSTANCE_URL=http://<this-host>:8082
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now argus-detection-server
```

## 방법 4 — shell 직접 실행

```bash
cd /opt/argus-ext/extensions && . detection-venv/bin/activate
export DETECT_PORT=8082 DETECT_API_KEY=changeme DETECT_PRELOAD=true

python -m detection_server                                             # 포그라운드
nohup python -m detection_server > /var/log/argus-detection.log 2>&1 & # 백그라운드
```

## 모델 준비 (수동 배포 서버)

검출 모델(Paddle det/rec·EasyOCR)은 HF 팩 규약(pack_model) **미지원** — 엔진이 자체
저장소에서 내려받는 방식이라 준비 절차가 다르다:

**온라인**: 준비 불필요 — 첫 검출 요청(또는 `DETECT_PRELOAD=true` 기동) 시 엔진이 자동
다운로드한다(paddleocr → `~/.paddleocr`, easyocr → `~/.EasyOCR`).

**에어갭**: 온라인 머신에서 같은 엔진 설정으로 1회 기동해 캐시를 채운 뒤 통째로 복사한다:

```bash
# [온라인 머신] 캐시 채우기 — 컨테이너로 하는 것이 가장 간단
docker run --rm -v detect-cache:/models -e DETECT_PRELOAD=true \
  -e DETECT_ENGINE=paddleocr argus-rag-studio-detection-server:latest \
  sh -c "python -m detection_server & sleep 60"    # PRELOAD 완료까지 대기 후 종료
docker run --rm -v detect-cache:/models alpine tar czf - -C /models . > detect-models.tar.gz

# [에어갭 서버] 캐시 전개 — Docker 는 argus-rag-detect-models 볼륨, systemd/shell 은 홈 캐시 경로
docker run --rm -v argus-rag-detect-models:/models -v $PWD:/in alpine \
  tar xzf /in/detect-models.tar.gz -C /models
# (systemd/shell 실행이면 서비스 계정 홈의 ~/.paddleocr / ~/.EasyOCR 로 전개)
```

캐시 위치는 엔진·버전에 따라 다를 수 있으니, 채운 뒤 `find` 로 실제 생성 경로를 확인해
같은 경로로 복사하는 것이 안전하다.

## 옵션 레퍼런스 (`DETECT_*` env — config.yml 값보다 항상 우선, 빈값도 유효)

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `DETECT_HOST` | 0.0.0.0 | 바인드 주소 |
| `DETECT_PORT` | 8082 | 리슨 포트 |
| `DETECT_API_KEY` | changeme | Bearer 인증 키. **빈값이면 무인증** — 반드시 변경 |
| `DETECT_ENGINE` | paddleocr | `paddleocr`(CPU 안정) \| `easyocr`(torch — GPU 경로). aarch64 는 paddle-gpu 휠 부재로 GPU=easyocr 만 가능 |
| `DETECT_USE_GPU` | false | GPU 사용(engine 이 지원할 때). 로딩 실패 시 CPU 폴백 |
| `DETECT_LANG` | korean | paddleocr 인식 언어 |
| `DETECT_EASYOCR_LANGS` | ko,en | easyocr 언어 목록(콤마) |
| `DETECT_MIN_SCORE` | 0.5 | 검출 결과 최소 신뢰도 — 이 값 미만 bbox 는 응답에서 제외 |
| `DETECT_MAX_IMAGE_MB` | 20 | 요청 이미지 크기 상한(MB) — 초과 시 거부 |
| `DETECT_PRELOAD` | false | 기동 시 모델 즉시 로드(true 권장 — paddle 최초 로드가 십수 초) |
| `DETECT_LOG_LEVEL` / `DETECT_LOG_DIR` | INFO / logs | 로그 레벨·디렉터리 |
| `ARGUS_DETECTION_SERVER_CONFIG_DIR` | /etc/argus-detection-server | config.yml/properties 디렉터리 |

**자기 등록(heartbeat, 선택)**: `ARGUS_HEARTBEAT_URL`(빈값=비활성) · `ARGUS_INSTANCE_URL` ·
`ARGUS_HEARTBEAT_TOKEN`(백엔드 `monitoring.heartbeat_token` 일치, 선택) ·
`ARGUS_HEARTBEAT_INTERVAL`(기본 10초).

## 탐색·모니터링

방법 1·2(규약 Docker)만 서비스 관리 탭에 보인다. 방법 3·4는 heartbeat env +
전역 `detection.server_url` 폴링(잡 모니터링 > 외부 서버)으로 관측.

## 검증

```bash
curl -s http://<host>:8082/health
curl -s -H "Authorization: Bearer changeme" http://<host>:8082/stats
# 어노테이션 화면의 "자동 인식" 버튼으로 실검출 확인(backend detection.enabled=true 필요)
```
