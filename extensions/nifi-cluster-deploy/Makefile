INV ?= inventories/sample/hosts.yml
PLAYBOOK ?= site.yml
VAULT ?= --ask-vault-pass

.PHONY: help deps lint syntax ping deploy certs nifi zk facts encrypt-secrets

help: ## 사용 가능한 타깃
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

deps: ## 컬렉션 의존성 설치(없어도 동작)
	ansible-galaxy collection install -r requirements.yml || true

syntax: ## 플레이북 문법 검사
	ansible-playbook -i $(INV) $(PLAYBOOK) --syntax-check

lint: ## ansible-lint(설치된 경우)
	command -v ansible-lint >/dev/null && ansible-lint $(PLAYBOOK) || echo "ansible-lint 미설치 — 건너뜀"

ping: ## SSH 연결 확인
	ansible -i $(INV) all -m ping

deploy: ## 전체 배포(인증서+ZK+NiFi)
	ansible-playbook -i $(INV) $(PLAYBOOK) $(VAULT)

certs: ## 인증서 발급/배포만
	ansible-playbook -i $(INV) $(PLAYBOOK) --tags certs $(VAULT)

zk: ## ZooKeeper 만
	ansible-playbook -i $(INV) $(PLAYBOOK) --tags zookeeper $(VAULT)

nifi: ## NiFi 설치/구성만
	ansible-playbook -i $(INV) $(PLAYBOOK) --tags nifi $(VAULT)

facts: ## 대상 호스트 facts 수집
	ansible -i $(INV) all -m setup

encrypt-secrets: ## group_vars 의 비밀값 vault 암호화 예시
	@echo "예) ansible-vault encrypt_string 'pass' --name 'tls_keystore_password'"
