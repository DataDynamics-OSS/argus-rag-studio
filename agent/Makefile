NAME = argus-rag-studio-agent
# 버전은 락스텝 단일 소스(app/__init__.py)에서 — VERSIONING.md
VERSION ?= $(shell grep -oP '__version__ = "\K[0-9.]+' app/__init__.py)

.PHONY: help install dev run test lint clean rpm deb

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	pip install -e .

dev: ## Install with dev dependencies
	pip install -e ".[dev]"

run: ## Run the server
	uvicorn app.main:app --host 0.0.0.0 --port 4501 --reload

test: ## Run tests
	pytest tests/ -v

lint: ## Run linter
	ruff check app/ tests/
	ruff format --check app/ tests/

format: ## Format code
	ruff format app/ tests/
	ruff check --fix app/ tests/

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# --- Packaging ---

rpm: clean ## Build RPM package
	mkdir -p build/rpm
	tar czf build/rpm/$(NAME)-$(VERSION).tar.gz \
		--transform 's,^,$(NAME)-$(VERSION)/,' \
		app/ scripts/ packaging/ pyproject.toml README.md LICENSE
	rpmbuild -ba packaging/rpm/$(NAME).spec \
		--define "_sourcedir $(CURDIR)/build/rpm" \
		--define "_srcrpmdir $(CURDIR)/dist" \
		--define "_rpmdir $(CURDIR)/dist"

deb: clean ## Build Debian package
	dpkg-buildpackage -us -uc -b
