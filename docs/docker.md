# Docker Support

Run mcp-cn-commerce in Docker for consistent, isolated environments — no local Python setup required.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 20.10+
- [Docker Compose](https://docs.docker.com/compose/) 2.24+ (the Compose file uses optional env_file)

## Quick Start

### Build the Image

```bash
docker build -t mcp-cn-commerce .
```

### Run Tests

```bash
# Build the development image with test dependencies
docker build --target development -t mcp-cn-commerce-dev .
docker run --rm mcp-cn-commerce-dev make test

# With coverage report (output in ./htmlcov/)
docker compose up test-cov
```

### Run a Single Platform Server

Each platform runs as an MCP server via stdin/stdout:

```bash
# Ocean Engine (巨量引擎)
docker run --rm -i \
  -e OCEANENGINE_APP_KEY="your_key" \
  -e OCEANENGINE_APP_SECRET="your_secret" \
  -e OCEANENGINE_ACCESS_TOKEN="your_token" \
  mcp-cn-commerce mcp-cn-oceanengine

# Douyin Shop (抖店)
docker run --rm -i \
  -e DOUDIAN_APP_KEY="your_key" \
  -e DOUDIAN_APP_SECRET="your_secret" \
  -e DOUDIAN_SHOP_ID="your_shop_id" \
  -e DOUDIAN_ACCESS_TOKEN="your_token" \
  mcp-cn-commerce mcp-cn-doudian

# JD.com (京东)
docker run --rm -i \
  -e JD_APP_KEY="your_key" \
  -e JD_APP_SECRET="your_secret" \
  -e JD_ACCESS_TOKEN="your_token" \
  mcp-cn-commerce mcp-cn-jd
```

### Using .env File

Copy the example and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your actual credentials
```

Then run with `--env-file`:

```bash
docker run --rm -i --env-file .env mcp-cn-commerce mcp-cn-oceanengine
```

## Docker Compose

Docker Compose provides convenient shortcuts for common tasks:

```bash
# Run all tests
docker compose up test

# Run tests with coverage (htmlcov/ mounted to host)
docker compose up test-cov

# Run linting
docker compose up lint

# Interactive development shell
docker compose run --rm shell
```

### Individual Platform Servers via Compose

```bash
# Start Ocean Engine server
docker compose run --rm -T oceanengine

# Start Douyin Shop server
docker compose run --rm -T doudian
```

## MCP Client Configuration

### Claude Desktop (Docker)

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "--env-file", "/path/to/.env", "mcp-cn-commerce", "mcp-cn-oceanengine"]
    },
    "doudian": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "--env-file", "/path/to/.env", "mcp-cn-commerce", "mcp-cn-doudian"]
    },
    "jd": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "--env-file", "/path/to/.env", "mcp-cn-commerce", "mcp-cn-jd"]
    }
  }
}
```

### Using Docker Compose with MCP Clients

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "docker",
      "args": ["compose", "run", "--rm", "-T", "oceanengine"]
    }
  }
}
```

## Development

### Interactive Shell

Drop into a bash shell inside the container for debugging:

```bash
# With source mounted (live editing)
docker compose run --rm shell

# Inside the container:
make test                    # Run tests
make lint                    # Check code style
python -c "import servers.oceanengine.server"  # Verify imports
```

### Rebuild After Changes

```bash
# Rebuild image (no cache)
docker build --no-cache -t mcp-cn-commerce .

# Or with Compose
docker compose build --no-cache
```

## Available Platform Commands

| Platform | Command | Description |
|----------|---------|-------------|
| Ocean Engine | `mcp-cn-oceanengine` | 巨量引擎广告投放 |
| Douyin Shop | `mcp-cn-doudian` | 抖店电商 |
| JD.com | `mcp-cn-jd` | 京东电商 |
| Taobao | `mcp-cn-taobao` | 淘宝电商 |
| Pinduoduo | `mcp-cn-pinduoduo` | 拼多多电商 |
| Kuaishou | `mcp-cn-kuaishou` | 快手电商 |
| Xiaohongshu | `mcp-cn-xiaohongshu` | 小红书电商 |
| WeChat Store | `mcp-cn-weixin-store` | 微信小店 |

## Environment Variables

All platform credentials are passed via environment variables. See [`.env.example`](../.env.example) for the full list.

**Never bake credentials into the Docker image.** Always use:
- `docker run -e KEY=VALUE` for one-off runs
- `--env-file .env` for multiple variables
- Docker Compose `env_file` directive

## Troubleshooting

### Build fails with network errors

Builds need access to the Python package registry, and the development target also installs make from the image's OS package registry. Diagnose that network access in your environment; do not remove the dependency constraints to mask a download failure.

### Tests fail inside container but pass locally

Build the development target and run its tests. The project is a single installed package; do not add obsolete servers/<platform>/src directories to PYTHONPATH. Check that the image was rebuilt after source changes.

### MCP connection fails

Use one platform per stdio connection, `docker run -i` without `-t`, or `docker compose run -T`. A detached `docker compose up` does not provide an MCP routing gateway. Missing merchant credentials should permit discovery but cause a clear error on a business query; discovery alone does not prove authorization.
