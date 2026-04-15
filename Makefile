.PHONY: help test test-watch test-coverage lint format clean build run stop logs shell scrape deploy

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

# PYTHON resolves to ./env/bin/python when a venv exists, else system python3
PYTHON := $(shell if [ -x env/bin/python ]; then echo ./env/bin/python; else echo python3; fi)

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
		$(PYTHON) -m pytest tracker/tests/ -v --tb=short -f; \
	fi

test-coverage:
	@echo "📊 Running tests with coverage..."
	@if [ -n "$(DOCKER_COMPOSE)" ]; then \
		$(DOCKER_COMPOSE) run --rm test pytest tracker/tests/ --cov=tracker --cov-report=html --cov-report=term; \
	else \
		$(PYTHON) -m pytest tracker/tests/ --cov=tracker --cov-report=html --cov-report=term; \
	fi
	@echo "✅ Coverage report generated in htmlcov/index.html"

test-file:
	@echo "🧪 Running test file: $(FILE)"
	@if [ -n "$(DOCKER_COMPOSE)" ]; then \
		$(DOCKER_COMPOSE) run --rm test pytest $(FILE) -v --tb=short; \
	else \
		$(PYTHON) -m pytest $(FILE) -v --tb=short; \
	fi

test-local:
	@echo "🧪 Running tests locally (no Docker)..."
	$(PYTHON) -m pytest tracker/tests/ -v --tb=short

# Scraping
scrape: scrape-amiibo

scrape-amiibo:
	@echo "🎮 Running amiibo.life scraper..."
	@if [ -d "env" ]; then \
		./env/bin/python manage.py auto_scrape_nintendo --scraper=amiibolife --force; \
	else \
		python manage.py auto_scrape_nintendo --scraper=amiibolife --force; \
	fi

scrape-nintendo:
	@echo "⚠️  Running Nintendo.com scraper (deprecated)..."
	@if [ -d "env" ]; then \
		./env/bin/python manage.py auto_scrape_nintendo --scraper=nintendodotcom --force; \
	else \
		python manage.py auto_scrape_nintendo --scraper=nintendodotcom --force; \
	fi

scrape-force:
	@echo "🎮 Force running amiibo.life scraper..."
	@if [ -d "env" ]; then \
		./env/bin/python manage.py auto_scrape_nintendo --scraper=amiibolife --force; \
	else \
		python manage.py auto_scrape_nintendo --scraper=amiibolife --force; \
	fi

scrape-docker:
	@echo "🎮 Running scraper in Docker..."
	docker-compose run --rm app python manage.py auto_scrape_nintendo --scraper=amiibolife --force

# Code Quality
lint:
	@echo "🔍 Running linting checks..."
	black --check tracker/ amiibo_tracker/
	@echo "✅ Linting passed!"

format:
	@echo "✨ Formatting code..."
	black tracker/ amiibo_tracker/
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
	@if [ -d "env" ]; then \
		./env/bin/python manage.py runserver 8080; \
	else \
		python manage.py runserver 8080; \
	fi

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
	@if [ -d "env" ]; then \
		./env/bin/python manage.py migrate; \
	else \
		python manage.py migrate; \
	fi

makemigrations:
	@echo "🗄️  Creating migrations..."
	@if [ -d "env" ]; then \
		./env/bin/python manage.py makemigrations; \
	else \
		python manage.py makemigrations; \
	fi

collectstatic:
	@echo "📦 Collecting static files..."
	@if [ -d "env" ]; then \
		./env/bin/python manage.py collectstatic --noinput; \
	else \
		python manage.py collectstatic --noinput; \
	fi

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
	@if [ -d "env" ]; then \
		./env/bin/pip install -r requirements.txt; \
	else \
		pip install -r requirements.txt; \
	fi

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
