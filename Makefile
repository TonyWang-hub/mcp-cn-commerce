.PHONY: help install test test-cov lint format clean type-check pylint bandit quality

# PYTHONPATH for all platform server source directories
PYTHONPATH_SOURCES := servers/oceanengine/src:servers/doudian/src:servers/jd/src:servers/taobao/src:servers/pinduoduo/src:servers/kuaishou/src:servers/xiaohongshu/src:servers/weixin-store/src

# Default target
help:
	@echo "mcp-cn-commerce Development Commands"
	@echo "====================================="
	@echo ""
	@echo "  make install    - Install all dependencies (dev + all platforms)"
	@echo "  make test       - Run all tests (servers/ + tests/)"
	@echo "  make test-cov   - Run tests with coverage report (HTML + terminal)"
	@echo "  make lint       - Check code style (black --check + ruff check)"
	@echo "  make format     - Auto-format code (black + ruff fix)"
	@echo "  make type-check - Run type checking with mypy"
	@echo "  make pylint     - Run pylint code quality check"
	@echo "  make bandit     - Run bandit security check"
	@echo "  make quality    - Run all quality checks (lint + type-check + pylint + bandit)"
	@echo "  make clean      - Remove __pycache__, .pytest_cache, .egg-info, .coverage, htmlcov"
	@echo ""

# Install dependencies
install:
	pip install -e ".[dev]"
	pip install -e servers/oceanengine/
	pip install -e servers/doudian/
	pip install -e servers/jd/
	pip install -e servers/taobao/
	pip install -e servers/pinduoduo/
	pip install -e servers/kuaishou/
	pip install -e servers/xiaohongshu/
	pip install -e servers/weixin-store/

# Run tests
test:
	PYTHONPATH=$(PYTHONPATH_SOURCES) \
	pytest servers/ tests/ -v --tb=short

# Run tests with coverage
test-cov:
	PYTHONPATH=$(PYTHONPATH_SOURCES) \
	pytest servers/ tests/ -v --tb=short --cov=servers --cov=shared --cov-report=html --cov-report=term

# Lint code
lint:
	black --check .
	ruff check .

# Format code
format:
	black .
	ruff check --fix .

# Type checking with mypy
type-check:
	mypy servers/ shared/ tests/ --config-file=pyproject.toml

# Pylint code quality check
pylint:
	pylint --rcfile=pyproject.toml --disable=import-error servers/ shared/

# Bandit security check
bandit:
	bandit -c pyproject.toml -r servers/ shared/

# Run all quality checks
quality: lint type-check pylint bandit

# Clean cache files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ .mypy_cache/
