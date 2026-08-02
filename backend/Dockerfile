# Argus RAG Studio 백엔드 — API/워커 공용 이미지(동일 이미지, command 만 다름).
#   - API   : uvicorn app.main:app   (기본 CMD)
#   - 워커  : python -m app.worker_main  (compose 에서 command override)
# 주의: docling(docai 파서)이 torch/rapidocr 등을 끌어와 이미지가 큼(수 GB). 파싱은 백엔드
#       프로세스(=이 이미지)에서 CPU 로 수행되므로, 워커를 별도 컨테이너로 분리·확장한다.
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# docling/opencv 런타임(libgl/glib/gomp) + 빌드 도구
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# 의존성 먼저(레이어 캐시). docling 설치가 가장 오래 걸린다.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 앱 코드 + 패키징(설정/SQL)
COPY . ./

ENV ARGUS_RAG_STUDIO_SERVER_CONFIG_DIR=/srv/packaging/config

EXPOSE 4700
# 기본은 API. 워커는 compose 에서 command 를 python -m app.worker_main 로 override.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4700"]
