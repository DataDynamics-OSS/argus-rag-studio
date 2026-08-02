.PHONY: up down logs ls buckets

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f minio

# 버킷 목록(컨테이너 내 mc)
ls:
	docker compose run --rm createbuckets sh -c \
	  "mc alias set local http://minio:9000 $${MINIO_ROOT_USER:-minioadmin} $${MINIO_ROOT_PASSWORD:-minioadmin} >/dev/null && mc ls local"

# 버킷 재생성(멱등)
buckets:
	docker compose up createbuckets
