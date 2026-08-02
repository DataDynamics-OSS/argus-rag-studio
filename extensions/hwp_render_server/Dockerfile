# Argus HWP 렌더 서비스 — 헤드리스 chromium + @rhwp/core(WASM)로 HWP/HWPX 페이지 렌더.
# LibreOffice 가 못 여는 HWP/HWPX 를 서버사이드로 렌더(검색 근거 페이지 등).
FROM node:20-slim

ENV DEBIAN_FRONTEND=noninteractive \
    HWP_RENDER_PORT=8085 \
    CHROMIUM_PATH=/usr/bin/chromium

# chromium + 헤드리스 렌더 런타임 의존(폰트 포함 — 한국어 렌더 위해 fonts-nanum)
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium fonts-nanum fonts-noto-cjk libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY package.json package-lock.json ./
# playwright-core 만 설치(브라우저 다운로드 없음). chromium 은 위 apt 로 제공.
# --ignore-scripts: postinstall(copy-rhwp)은 scripts/ 가 아직 복사 전이라 실패 → 아래에서 명시 실행.
# npm ci: 락파일 고정 설치 — @rhwp/core 버전이 조용히 앞서가는 드리프트 방지(버전 정합 규약).
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY . ./
RUN node scripts/copy-rhwp.js

EXPOSE 8085
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:8085/health',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
