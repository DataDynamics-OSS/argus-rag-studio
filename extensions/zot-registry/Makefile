.PHONY: up down logs ls catalog auth-user

# zot 레지스트리 기동/중지/로그
up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# 저장소 카탈로그 조회(무인증 기준)
catalog:
	curl -s http://localhost:$${ZOT_PORT:-5000}/v2/_catalog | (jq . 2>/dev/null || cat)

# 특정 repo 의 태그 목록 (예: make ls REPO=argus/argus-rag-studio-embedding-server)
ls:
	@test -n "$(REPO)" || (echo "usage: make ls REPO=argus/<image>"; exit 1)
	curl -s http://localhost:$${ZOT_PORT:-5000}/v2/$(REPO)/tags/list | (jq . 2>/dev/null || cat)

# htpasswd 사용자 추가 (config.auth.json 사용 시). 예: make auth-user USER=ci PASS=secret
auth-user:
	@test -n "$(USER)" -a -n "$(PASS)" || (echo "usage: make auth-user USER=<u> PASS=<p>"; exit 1)
	htpasswd -bBn $(USER) $(PASS) >> config/htpasswd
	@echo "added $(USER) to config/htpasswd — restart with ZOT_CONFIG=config.auth.json"
