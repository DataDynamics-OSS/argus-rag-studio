# Argus 임베딩 모델 파인튜닝 트레이너
# GPU 학습은 CUDA 런타임 베이스(예: pytorch/pytorch:*-cuda)로 교체하여 사용한다.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# 데이터셋·출력은 볼륨으로 마운트해서 사용한다.
#   docker run --rm -v $PWD/samples/dataset:/data -v $PWD/out:/out argus-retrieval-finetune:latest \
#     train --dataset /data --output /out/model
ENTRYPOINT ["python", "-m", "finetune"]
CMD ["--help"]
