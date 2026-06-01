.PHONY: help test test-watch test-coverage lint format clean build run stop logs shell scrape scrape-remote deploy report-daily report-daily-dry report-daily-remote install-certs update-amiibo-db update-amiibo-db-dry

# Default target - show help
help:
	@echo "🎮 Amiibo Tracker - Development Commands"
	@echo ""
	@echo "Testing:"
	@echo "  make test              - Run all tests"
	@echo "  make test-watch        - Run tests in watch mode"
	@echo "  make test-coverage     - Run tests with coverage report"
	@echo "  make test-file FILE=path/to/test.py - Run specific test file"
	@echo ""
	@echo "Scraping:"
	@echo "  make scrape            - Run amiibo.life scraper (default)"
	@echo "  make scrape-amiibo     - Run amiibo.life scraper"
	@echo "  make scrape-nintendo   - Run Nintendo.com scraper (deprecated)"
	@echo "  make scrape-force      - Force run scraper (ignore cache)"
	@echo ""
	@echo "Amiibo database:"
	@echo "  make update-amiibo-db      - Sync tracker/data/amiibo_database.json"
	@echo "                               from https://goozamiibo.com/api/amiibo/"
	@echo "                               (writes only when content changes)"
	@echo "  make update-amiibo-db-dry  - Show the diff without writing"
	@echo "  (override endpoint with API_URL=https://...; e.g. for staging)"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint              - Run linting checks (black check)"
	@echo "  make format            - Auto-format code with black"
	@echo "  make check             - Run all checks (lint + test)"
	@echo ""
	@echo "Docker:"
	@echo "  make build             - Build Docker image"
	@echo "  make run               - Run service (Docker + gunicorn)"
	@echo "  make run-dev           - Run dev server (Docker + runserver)"
	@echo "  make run-local         - Run service (local, no Docker)"
	@echo "  make stop              - Stop running containers"
	@echo "  make logs              - View container logs"
	@echo "  make shell             - Open shell in container"
	@echo ""
	@echo "Database:"
	@echo "  make migrate           - Run Django migrations"
	@echo "  make makemigrations    - Create new migrations"
	@echo "  make collectstatic     - Collect static files"
	@echo ""
	@echo "Daily DAU report:"
	@echo "  make report-daily-dry  - Dry run (no email/upload); auto-loads .env"
	@echo "  make report-daily      - Send + archive the report; auto-loads .env"
	@echo "  (override day with DATE=YYYY-MM-DD; default is yesterday UTC)"
	@echo ""
	@echo "  make report-daily-remote  - Hit the public endpoint and fire the email now"
	@echo "  make scrape-remote        - Hit the public endpoint and trigger a scrape"
	@echo "  (override SITE_URL=https://staging.example.com)"
	@echo ""
	@echo "macOS Python TLS fix:"
	@echo "  make install-certs     - Run Python.org's Install Certificates.command"
	@echo "                           (one-time; fixes SSL_CERT_FILE for SMTP/HTTPS)"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean             - Clean up cache and temp files"
	@echo "  make install           - Install dependencies"
	@echo "  make setup             - Initial project setup"
	@echo ""

# Testing
#
# DOCKER_COMPOSE resolves to the best available compose CLI:
#   1. docker-compose (v1)
#   2. docker compose (v2)
#   3. empty string — triggers local fallback
DOCKER_COMPOSE := $(shell \
	if command -v docker-compose >/dev/null 2>&1; then echo docker-compose; \
	elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then echo "docker compose"; \
	fi)

# VENV_DIR picks whichever virtualenv directory already exists; falls back
# to `env` (which `dev-setup` creates) on a fresh checkout.
VENV_DIR := $(shell \
	if [ -d env ]; then echo env; \
	elif [ -d .venv ]; then echo .venv; \
	else echo env; fi)
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip

# Bootstrap snippet — create the virtualenv if missing, (re)install
# requirements when requirements.txt is newer than our stamp file, then
# continue the shell chain. Prepended to every recipe that touches Python
# so `make <anything>` works on a fresh checkout without manual setup.
# Stamp file gates pip install on the common no-op path.
ENSURE_VENV := \
	if [ ! -x $(PYTHON) ]; then \
		echo "🐍 Creating virtualenv in $(VENV_DIR)/..."; \
		python3 -m venv $(VENV_DIR); \
	fi; \
	if [ ! -f $(VENV_DIR)/.deps-installed ] || [ requirements.txt -nt $(VENV_DIR)/.deps-installed ]; then \
		echo "📦 Installing dependencies into $(VENV_DIR)/..."; \
		$(PIP) install -q -r requirements.txt && touch $(VENV_DIR)/.deps-installed; \
	fi;

# Shell snippet that exports every var in .env to the child process. The
# `set -a` flag auto-exports anything assigned until `set +a`. The leading
# `-` on the file test is a no-op shim so the command stays a single
# semicolon-joined chain inside make recipes (one shell invocation = one
# environment).
ENV_LOAD := set -a; [ -f .env ] && . ./.env; set +a;

test:
	@echo "🧪 Running tests..."
	@if [ -n "$(DOCKER_COMPOSE)" ]; then \
		$(DOCKER_COMPOSE) run --rm test; \
	else \
		echo "⚠️  Docker Compose not found — running tests locally."; \
		$(MAKE) test-local; \
	fi

test-watch:
	@echo "🧪 Running tests in watch mode..."
	@if [ -n "$(DOCKER_COMPOSE)" ]; then \
		$(DOCKER_COMPOSE) run --rm test pytest tracker/tests/ -v --tb=short -f; \
	else \
		$(ENSURE_VENV) \
		$(PYTHON) -m pytest tracker/tests/ -v --tb=short -f; \
	fi

test-coverage:
	@echo "📊 Running tests with coverage..."
	@if [ -n "$(DOCKER_COMPOSE)" ]; then \
		$(DOCKER_COMPOSE) run --rm test pytest tracker/tests/ --cov=tracker --cov-report=html --cov-report=term; \
	else \
		$(ENSURE_VENV) \
		$(PYTHON) -m pytest tracker/tests/ --cov=tracker --cov-report=html --cov-report=term; \
	fi
	@echo "✅ Coverage report generated in htmlcov/index.html"

test-file:
	@echo "🧪 Running test file: $(FILE)"
	@if [ -n "$(DOCKER_COMPOSE)" ]; then \
		$(DOCKER_COMPOSE) run --rm test pytest $(FILE) -v --tb=short; \
	else \
		$(ENSURE_VENV) \
		$(PYTHON) -m pytest $(FILE) -v --tb=short; \
	fi

test-local:
	@echo "🧪 Running tests locally (no Docker)..."
	@$(ENSURE_VENV) \
	$(PYTHON) -m pytest tracker/tests/ -v --tb=short

# Scraping
scrape: scrape-amiibo

scrape-amiibo:
	@echo "🎮 Running amiibo.life scraper..."
	@$(ENSURE_VENV) \
	$(PYTHON) manage.py auto_scrape_nintendo --scraper=amiibolife --force

scrape-nintendo:
	@echo "⚠️  Running Nintendo.com scraper (deprecated)..."
	@$(ENSURE_VENV) \
	$(PYTHON) manage.py auto_scrape_nintendo --scraper=nintendodotcom --force

scrape-force:
	@echo "🎮 Force running amiibo.life scraper..."
	@$(ENSURE_VENV) \
	$(PYTHON) manage.py auto_scrape_nintendo --scraper=amiibolife --force

scrape-docker:
	@echo "🎮 Running scraper in Docker..."
	docker-compose run --rm app python manage.py auto_scrape_nintendo --scraper=amiibolife --force

# Amiibo DB sync
#
# Hits the live API (default: https://goozamiibo.com/api/amiibo/), diffs
# against tracker/data/amiibo_database.json keyed by (head, tail), and only
# writes when the content changed — so no-op runs leave a clean git status.
#
# Usage:
#   make update-amiibo-db
#   make update-amiibo-db-dry
#   make update-amiibo-db API_URL=https://staging.example.com/api/amiibo/
update-amiibo-db:
	@echo "🔄 Syncing amiibo database from $(if $(API_URL),$(API_URL),the live API)..."
	@$(ENSURE_VENV) \
	$(PYTHON) manage.py update_amiibo_db $(if $(API_URL),--api-url $(API_URL),)

update-amiibo-db-dry:
	@echo "🔍 Previewing amiibo database diff (dry-run)..."
	@$(ENSURE_VENV) \
	$(PYTHON) manage.py update_amiibo_db --dry-run $(if $(API_URL),--api-url $(API_URL),)

# Daily DAU report
#
# Auto-loads .env so LOKI_QUERY_*, EMAIL_*, GCS_REPORTS_BUCKET, etc. are
# in the environment without manual exports. Copy .env.example to .env
# and fill in the secrets before running.
#
# Usage:
#   make report-daily-dry           # yesterday UTC, no email/upload
#   make report-daily-dry DATE=2026-05-27
#   make report-daily               # actually email + archive
report-daily-dry:
	@echo "📨 Generating dry-run daily DAU report$(if $(DATE), for $(DATE),)..."
	@$(ENSURE_VENV) \
	$(ENV_LOAD) \
	$(PYTHON) manage.py report_daily_users $(if $(DATE),--date $(DATE),) --dry-run

report-daily:
	@echo "📨 Sending daily DAU report$(if $(DATE), for $(DATE),)..."
	@$(ENSURE_VENV) \
	$(ENV_LOAD) \
	$(PYTHON) manage.py report_daily_users $(if $(DATE),--date $(DATE),)

# Remote triggers — public endpoints, plain curl. Override SITE_URL for staging.
SITE_URL ?= https://goozamiibo.com

scrape-remote:
	@echo "🎮 Triggering remote scrape at $(SITE_URL)/api/scrape-nintendo/"
	@curl -sS -X POST -w "\nHTTP %{http_code}\n" $(SITE_URL)/api/scrape-nintendo/

report-daily-remote:
	@echo "📨 Triggering remote daily report at $(SITE_URL)/api/run-daily-report/"
	@curl -sS -X POST -w "\nHTTP %{http_code}\n" $(SITE_URL)/api/run-daily-report/

# macOS Python TLS fix
#
# Python.org's installer ships an "Install Certificates.command" that pip
# installs `certifi` and symlinks the CA bundle so the stdlib `ssl` module
# can verify HTTPS / SMTP TLS handshakes. Runs once per Python minor version.
# Picks the newest Python.framework version it finds under /Applications.
install-certs:
	@echo "🔐 Installing TLS certificates for Python.org Python..."
	@SCRIPT=$$(ls -d "/Applications/Python "* 2>/dev/null \
		| sort -V | tail -1)/"Install Certificates.command"; \
	if [ ! -f "$$SCRIPT" ]; then \
		echo "❌ Could not find an Install Certificates.command under /Applications/Python*."; \
		echo "   If you're on Homebrew Python instead, certs are usually already wired."; \
		echo "   Fallback: pip install certifi && set SSL_CERT_FILE in .env."; \
		exit 1; \
	fi; \
	echo "   Using: $$SCRIPT"; \
	"$$SCRIPT"
	@echo "✅ TLS certs installed. Retry 'make report-daily'."

# Code Quality
lint:
	@echo "🔍 Running linting checks..."
	@$(ENSURE_VENV) \
	$(PYTHON) -m black --check tracker/ amiibo_tracker/
	@echo "✅ Linting passed!"

format:
	@echo "✨ Formatting code..."
	@$(ENSURE_VENV) \
	$(PYTHON) -m black tracker/ amiibo_tracker/
	@echo "✅ Code formatted!"

check: lint test
	@echo "✅ All checks passed!"

# Docker
build:
	@echo "🏗️  Building Docker image..."
	docker-compose build

run:
	@echo "🚀 Starting service in Docker (gunicorn)..."
	@echo "   → Open http://localhost:8080 (home) or http://localhost:8080/demo/"
	@if [ -n "$(DOCKER_COMPOSE)" ]; then \
		$(DOCKER_COMPOSE) up app; \
	else \
		echo "❌ Docker Compose not found — try 'make run-local'"; exit 1; \
	fi

run-dev:
	@echo "🚀 Starting Django dev server in Docker..."
	@echo "   → Open http://localhost:8080 (home) or http://localhost:8080/demo/"
	@if [ -n "$(DOCKER_COMPOSE)" ]; then \
		$(DOCKER_COMPOSE) up dev; \
	else \
		echo "❌ Docker Compose not found — try 'make run-local'"; exit 1; \
	fi

run-local:
	@echo "🚀 Starting Django dev server..."
	@$(ENSURE_VENV) \
	$(PYTHON) manage.py runserver 8080

stop:
	@echo "🛑 Stopping containers..."
	docker-compose down

logs:
	@echo "📋 Viewing logs..."
	docker-compose logs -f app

shell:
	@echo "🐚 Opening shell in container..."
	docker-compose run --rm app /bin/bash

shell-python:
	@echo "🐍 Opening Django shell..."
	docker-compose run --rm app python manage.py shell

# Database
migrate:
	@echo "🗄️  Running migrations..."
	@$(ENSURE_VENV) \
	$(PYTHON) manage.py migrate

makemigrations:
	@echo "🗄️  Creating migrations..."
	@$(ENSURE_VENV) \
	$(PYTHON) manage.py makemigrations

collectstatic:
	@echo "📦 Collecting static files..."
	@$(ENSURE_VENV) \
	$(PYTHON) manage.py collectstatic --noinput

# Utilities
clean:
	@echo "🧹 Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleaned up cache and temp files"

install:
	@echo "📦 Installing dependencies..."
	@$(ENSURE_VENV)
	@$(PIP) install -r requirements.txt
	@touch $(VENV_DIR)/.deps-installed

setup: dev-setup
	@echo "✅ Setup complete! Run 'make run-local' to start the dev server"

# Git helpers
branch-status:
	@echo "📊 Current branch status:"
	@git status --short
	@echo ""
	@echo "📝 Current branch:"
	@git branch --show-current

commit-staged:
	@echo "💾 Committing staged changes..."
	@git status --short
	@echo ""
	@read -p "Commit message: " msg; \
	git commit -m "$$msg"

# Deployment
deploy-check:
	@echo "🔍 Running pre-deployment checks..."
	@echo "1. Running tests..."
	@make test
	@echo "2. Running linting..."
	@make lint
	@echo "✅ Ready to deploy!"

# Development helpers
dev-setup:
	@echo "🔧 Setting up development environment..."
	@echo "1. Creating virtual environment..."
	python3 -m venv env
	@echo "2. Installing dependencies..."
	./env/bin/pip install -r requirements.txt
	@touch env/.deps-installed
	@echo "3. Running migrations..."
	./env/bin/python manage.py migrate
	@echo "✅ Development environment ready!"
	@echo "💡 Activate with: source env/bin/activate"

dev-reset:
	@echo "⚠️  Resetting development environment..."
	@echo "This will delete the virtual environment and rebuild it."
	@read -p "Are you sure? (y/N) " confirm; \
	if [ "$$confirm" = "y" ]; then \
		rm -rf env; \
		make dev-setup; \
	else \
		echo "Cancelled."; \
	fi
