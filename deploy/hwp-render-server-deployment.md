# HWP 렌더 서버 배포 가이드

- **역할**: HWP/HWPX 문서 미리보기 렌더링(rhwp WASM 기반 Node 서버)
- **소스**: `extensions/hwp_render_server/`(server.js) · **기본 포트**: 8085(`HWP_RENDER_PORT`)
- **설정 연결**: 전역 `hwp_render.url`
- **관측**: heartbeat 채널은 없지만 백엔드가 `hwp_render.url` 로 `/stats` 를 프로브한다
  — 관리형(규약 Docker)이면 그 행에 버전·엔진(rhwp)·요청 지표가 병합되고,
  systemd/shell 수동 실행도 서비스 관리에 **MANUAL 행**으로 관측된다(제어는 불가).

## 방법 1 — 플랫폼 배포 (권장)

**에이전트 > 서비스/배포**(kind=hwp_render) 또는 `POST /api/v1/deploy`.

## 방법 2 — 수동 Docker

```bash
# 이미지: cd extensions/hwp_render_server && docker build -t argus-rag-studio-hwp-render-server:latest .
docker run -d --name argus-rag-hwp-render-1 --label argus.kind=hwp_render \
  --restart unless-stopped -p 8085:8085 -e HWP_RENDER_PORT=8085 \
  argus-rag-studio-hwp-render-server:latest
```

## 방법 3 — systemd 직접 실행 (비컨테이너)

```bash
# Node 18+ 필요. postinstall 이 rhwp WASM 을 static/으로 복사한다.
cd /opt/argus-ext/extensions/hwp_render_server && npm install
```

```ini
# /etc/systemd/system/argus-hwp-render-server.service
[Unit]
Description=Argus HWP Render Server
After=network-online.target

[Service]
WorkingDirectory=/opt/argus-ext/extensions/hwp_render_server
ExecStart=/usr/bin/node server.js
Environment=HWP_RENDER_PORT=8085
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now argus-hwp-render-server
```

## 방법 4 — shell 직접 실행

```bash
cd /opt/argus-ext/extensions/hwp_render_server
npm install                                   # 최초 1회
HWP_RENDER_PORT=8085 npm start                # 포그라운드 (= node server.js)
nohup node server.js > /var/log/argus-hwp-render.log 2>&1 &   # 백그라운드
```

## 옵션 레퍼런스

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `HWP_RENDER_PORT` | 8085 | 리슨 포트 |
| `HWP_RENDER_HOST` | 0.0.0.0 | 바인드 주소 |
| `CHROMIUM_PATH` | (자동 탐색) | 렌더링에 쓸 chromium 실행 파일 경로 — 시스템 경로에서 못 찾으면 지정(playwright-core 는 브라우저를 내려받지 않음) |

> 인증 옵션 없음(내부망 전용 전제) — 외부 노출 금지. heartbeat 미지원.

## 검증

```bash
curl -s http://<host>:8085/health
# 백엔드 설정 hwp_render.url=http://<host>:8085 후 HWP 문서 미리보기 확인
```
