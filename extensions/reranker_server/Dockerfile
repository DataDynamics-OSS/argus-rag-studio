# Argus 리랭커 서버 — FastEmbed cross-encoder 재정렬 서비스
FROM python:3.11-slim

# onnxruntime 런타임 의존(libgomp)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 — 패키지로 임포트되도록 /srv/reranker_server 에 둔다
COPY . ./reranker_server

ENV ARGUS_RERANKER_SERVER_CONFIG_DIR=/srv/reranker_server/packaging/config \
    RERANK_CACHE_DIR=/models \
    RERANK_LOG_DIR=/var/log/argus-reranker-server \
    RERANK_HOST=0.0.0.0 \
    RERANK_PORT=8081
RUN mkdir -p /models /var/log/argus-reranker-server
VOLUME ["/models"]

EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8081/health').status==200 else 1)"

CMD ["python", "-m", "reranker_server"]
