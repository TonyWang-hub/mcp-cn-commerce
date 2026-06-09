# ─────────────────────────────────────────────────────────────
# mcp-cn-commerce — Multi-platform MCP Server Docker Image
# ─────────────────────────────────────────────────────────────
# Build:
#   docker build -t mcp-cn-commerce .
#
# Run (single platform):
#   docker run --rm -e OCEANENGINE_APP_KEY=... mcp-cn-commerce mcp-cn-oceanengine
#
# Run tests:
#   docker run --rm mcp-cn-commerce make test
# ─────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── System dependencies (minimal) ────────────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends make && \
    rm -rf /var/lib/apt/lists/*

# ── Python dependencies (layer caching) ─────────────────────
COPY pyproject.toml Makefile ./
COPY shared/ shared/

# Install base package (provides the `shared` library) + dev tools
RUN pip install --no-cache-dir -e ".[dev]"

# Install each platform server
COPY servers/oceanengine/   servers/oceanengine/
COPY servers/doudian/       servers/doudian/
COPY servers/jd/            servers/jd/
COPY servers/taobao/        servers/taobao/
COPY servers/pinduoduo/     servers/pinduoduo/
COPY servers/kuaishou/      servers/kuaishou/
COPY servers/xiaohongshu/   servers/xiaohongshu/
COPY servers/weixin-store/  servers/weixin-store/

RUN pip install --no-cache-dir -e servers/oceanengine/ && \
    pip install --no-cache-dir -e servers/doudian/ && \
    pip install --no-cache-dir -e servers/jd/ && \
    pip install --no-cache-dir -e servers/taobao/ && \
    pip install --no-cache-dir -e servers/pinduoduo/ && \
    pip install --no-cache-dir -e servers/kuaishou/ && \
    pip install --no-cache-dir -e servers/xiaohongshu/ && \
    pip install --no-cache-dir -e servers/weixin-store/

# ── PYTHONPATH for all platform source directories ──────────
ENV PYTHONPATH=servers/oceanengine/src:servers/doudian/src:servers/jd/src:servers/taobao/src:servers/pinduoduo/src:servers/kuaishou/src:servers/xiaohongshu/src:servers/weixin-store/src

# ── Copy remaining project files ────────────────────────────
COPY . .

# ── Default: run tests ──────────────────────────────────────
CMD ["make", "test"]
