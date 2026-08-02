# Argus HWP 렌더 서비스

헤드리스 브라우저에서 **@rhwp/core(WASM)** 로 HWP/HWPX 를 페이지별 이미지/텍스트로 렌더하는
독립 서비스. **LibreOffice 가 못 여는 HWP/HWPX 를 서버사이드로 렌더**한다(검색 결과의 근거
페이지 보기 등). RAG 백엔드와 분리 배포이며, 임베딩/리랭커 서버처럼 HTTP 로만 연동한다.

## 왜 헤드리스 브라우저인가
LibreOffice(soffice)는 이 환경에서 HWP 5.0·HWPX 를 `source file could not be loaded` 로 거부한다
(HWPX 는 원래 미지원). argus 프런트가 HWP 미리보기에 쓰는 `@rhwp/core` 가 가장 충실도가 높고,
이 엔진은 브라우저(DOM·canvas) 위에서 동작하므로 **헤드리스 브라우저로 서버에서 그대로 구동**한다.

## 엔드포인트 (JSON)
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 헬스체크 |
| GET | `/stats` | 요청 수·렌더 수·브라우저 상태 |
| POST | `/pages-text` | `{data_b64}` → `{page_count, page_texts[]}` (매칭용, 래스터화 없음) |
| POST | `/render` | `{data_b64, page, scale}` → `{page, page_count, image_b64, width, height}` |

`page` 는 0-base. `image_b64` 는 PNG(base64).

## 실행
```bash
cd extensions/hwp_render_server
npm install               # playwright-core + @rhwp/core (postinstall 이 rhwp 자산을 static/ 으로 복사)
# 시스템 chromium 사용(번들 chromium 다운로드 없음) — 자동 탐색 또는 CHROMIUM_PATH 지정
CHROMIUM_PATH=/usr/bin/chromium node server.js     # 포트 8085

# 또는 Docker (chromium·한국어 폰트 포함)
docker compose up -d --build
```

## 배포 (이미지 파이프라인 · 에이전트)

배포 이미지 이름은 `argus-rag-studio-<kind>-server:<tag>[-variant]` 규약을 따른다(이 서비스는 kind=`hwp_render`).
이 서비스는 CPU 렌더 단일 이미지이며 GPU/변형(variant)이 없다(태그 접미사 없음).

- **이미지 빌드(로컬)**: `make image KIND=hwp_render` (리포 루트에서 실행).
- **멀티아키 빌드·푸시**: `VERSION=<v> REGISTRY=<zot>/argus make images-push`.
  - 예) `argus-rag-studio-hwp-render-server:latest`.
- **레지스트리**: zot(`extensions/zot-registry/`). 에어갭(폐쇄망) 반입 절차는 `extensions/zot-registry/README.md` 참고.
- **원격 배포**: RAG Studio "에이전트" 화면 → 서비스/배포에서 kind=`hwp_render` 선택 → 각 호스트의 Argus RAG Studio Agent(:4501)가 Docker 로 컨테이너를 기동한다.
  배포가 완료되면 해당 서비스의 URL 이 RAG Studio 설정 `hwp_render.url` 에 자동 주입된다.

## RAG 백엔드 연결
백엔드 설정 `hwp_render.url`(또는 env `ARGUS_HWP_RENDER_URL`)을 이 서비스로 지정하면,
검색 결과 hit 의 "원본 페이지 보기"가 동작한다:
- `GET /api/v1/documents/by-chunk/{chunk_id}/evidence` → 청크 텍스트를 페이지 텍스트와 매칭해 페이지 추정
- `GET /api/v1/documents/{uuid}/page/{n}` → 해당 페이지 PNG

## 메모
- 헤드리스 chromium 은 메모리를 많이 쓴다. 브라우저는 1개를 워밋업해 재사용하고 렌더 호출을
  직렬화한다(rhwp WASM 단일 컨텍스트). 처리량이 필요하면 인스턴스를 늘려 LB 뒤에 둔다.
- 한국어 렌더를 위해 컨테이너에 `fonts-nanum`·`fonts-noto-cjk` 를 설치한다(Dockerfile 포함).
- GPU 불필요(CPU 렌더).
