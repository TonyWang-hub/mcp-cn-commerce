.PHONY: help install test lint format clean

# Default target
help:
	@echo "mcp-cn-commerce Development Commands"
	@echo "====================================="
	@echo ""
	@echo "  make install    - Install all dependencies (dev + all platforms)"
	@echo "  make test       - Run all tests"
	@echo "  make lint       - Check code style (black + ruff)"
	@echo "  make format     - Auto-format code (black + ruff)"
	@echo "  make clean      - Remove cache files"
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
	PYTHONPATH=servers/oceanengine/src:servers/doudian/src:servers/jd/src:servers/taobao/src:servers/pinduoduo/src:servers/kuaishou/src:servers/xiaohongshu/src:servers/weixin-store/src \
	pytest servers/ -v --tb=short

# Run tests with coverage
test-cov:
	PYTHONPATH=servers/oceanengine/src:servers/doudian/src:servers/jd/src:servers/taobao/src:servers/pinduoduo/src:servers/kuaishou/src:servers/xiaohongshu/src:servers/weixin-store/src \
	pytest servers/ -v --tb=short --cov=servers --cov-report=html --cov-report=term

# Lint code
lint:
	black --check .
	ruff check .

# Format code
format:
	black .
	ruff check --fix .

# Clean cache files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage htmlcov/ .mypy_cache/
