# Argus 임베딩 서버 — OpenAI 호환 FastEmbed 임베딩 서비스
FROM python:3.11-slim

# onnxruntime 런타임 의존(libgomp)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# 의존성 먼저(레이어 캐시)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 — 패키지로 임포트되도록 /srv/embedding_server 에 둔다
COPY . ./embedding_server

# 설정 디렉터리(config.yml/properties) + 모델 캐시/로그 경로
ENV ARGUS_EMBEDDING_SERVER_CONFIG_DIR=/srv/embedding_server/packaging/config \
    EMBED_CACHE_DIR=/models \
    EMBED_LOG_DIR=/var/log/argus-embedding-server \
    EMBED_HOST=0.0.0.0 \
    EMBED_PORT=8080
RUN mkdir -p /models /var/log/argus-embedding-server
VOLUME ["/models"]

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health').status==200 else 1)"

CMD ["python", "-m", "embedding_server"]
