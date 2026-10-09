# Build: docker build -t mcp-cn-commerce .
# MCP: docker run --rm -i --env-file .env mcp-cn-commerce mcp-cn-commerce start jd
# Tests: docker build --target development -t mcp-cn-commerce-dev .
#        docker run --rm mcp-cn-commerce-dev make test
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md requirements-lock.txt ./
COPY shared/ shared/
COPY servers/ servers/
# All eight platforms are part of the root distribution.
RUN python -m pip install --no-cache-dir -c requirements-lock.txt .

FROM base AS development
RUN apt-get update && \
    apt-get install -y --no-install-recommends make && \
    rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir -c requirements-lock.txt ".[dev]"
COPY . .
CMD ["make", "test"]

FROM base AS runtime
CMD ["mcp-cn-commerce", "list"]
