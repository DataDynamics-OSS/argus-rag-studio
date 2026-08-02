# Argus RAG Studio — 이미지 빌드/푸시 (상세: design/image-pipeline.md)
.PHONY: help images images-push image bake-print package packages

VERSION ?= $(shell git describe --tags --always 2>/dev/null || echo dev)
REGISTRY ?=
FLAT_REPO ?=
export VERSION REGISTRY FLAT_REPO

help:
	@echo "make images                         # 로컬 빌드(현재 아키, --load)"
	@echo "make images-push REGISTRY=<r>       # 멀티아키 빌드 + 레지스트리 push"
	@echo "make images-push FLAT_REPO=<ns/repo>  # 단일 리포 모드(Docker Hub) — 태그로 구분"
	@echo "make image KIND=embedding VARIANT=gpu   # 단일 타깃(--load)"
	@echo "make bake-print                     # bake 매트릭스(JSON) 출력"
	@echo "  VERSION=$(VERSION)  REGISTRY=$(REGISTRY)"

images:
	./scripts/build-images.sh load

images-push:
	./scripts/build-images.sh push

# 예: make image KIND=embedding VARIANT=gpu-torch  (VARIANT 기본 cpu)
image:
	@test -n "$(KIND)" || (echo "usage: make image KIND=<backend(worker)|embedding|reranker|detection|hwp_render> [VARIANT=cpu|gpu|gpu-torch]"; exit 1)
	./scripts/build-images.sh one $(KIND) $(or $(VARIANT),cpu)

bake-print:
	docker buildx bake --print

# systemd/shell(비 Docker) production 배포용 패키지(tar/deb/rpm) — 상세: scripts/package.sh 헤더
# 예: make package COMP=backend OPTS="--with-deps --deb --rpm"
package:
	@test -n "$(COMP)" || (echo "usage: make package COMP=<backend|agent|embedding|reranker|detection> [OPTS=\"--with-deps --deb --rpm\"]"; exit 1)
	./scripts/package.sh $(COMP) $(or $(OPTS),$(DEPS))

packages:
	./scripts/package.sh all $(or $(OPTS),$(DEPS))
