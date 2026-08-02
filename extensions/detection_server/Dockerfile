# Argus 검출 서버 — PaddleOCR 텍스트 bbox 검출 서비스
FROM python:3.11-slim

# PaddleOCR/OpenCV 런타임 의존(libgomp, libgl, glib 등)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# 의존성 먼저(레이어 캐시)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 — 패키지로 임포트되도록 /srv/detection_server 에 둔다
COPY . ./detection_server

# 설정 디렉터리(config.yml/properties) + 모델 캐시/로그 경로
ENV ARGUS_DETECTION_SERVER_CONFIG_DIR=/srv/detection_server/packaging/config \
    DETECT_LOG_DIR=/var/log/argus-detection-server \
    DETECT_HOST=0.0.0.0 \
    DETECT_PORT=8082
# PaddleOCR 모델 캐시 — 볼륨으로 영속(재시작 시 재다운로드 방지)
ENV HOME=/models
RUN mkdir -p /models /var/log/argus-detection-server
VOLUME ["/models"]

EXPOSE 8082
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8082/health').status==200 else 1)"

CMD ["python", "-m", "detection_server"]
