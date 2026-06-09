# CLI Reference

The `mcp-cn-commerce` CLI provides commands to manage and interact with Chinese e-commerce MCP servers.

## Installation

```bash
pip install -e .
```

This installs the `mcp-cn-commerce` command globally.

## Usage

```
mcp-cn-commerce [--verbose] [--config PATH] COMMAND [ARGS]
```

### Global Options

| Option | Description |
|--------|-------------|
| `--version` | Show version and exit |
| `--config PATH` | Path to configuration file (JSON) |
| `--verbose`, `-v` | Enable verbose/debug output |

## Commands

### `start` - Start MCP Servers

Start one or more MCP servers over stdio.

```bash
# Start a single server
mcp-cn-commerce start oceanengine

# Start multiple servers
mcp-cn-commerce start oceanengine jd taobao
```

**Behavior:**
- Single server: runs in foreground (blocking)
- Multiple servers: last server runs in foreground, others in background
- Press `Ctrl+C` to stop all servers

**Environment variables** must be set before starting. See [Platforms](platforms.md) for required variables per platform.

**Example with credentials:**

```bash
export OCEANENGINE_APP_KEY="your_key"
export OCEANENGINE_APP_SECRET="your_secret"
export OCEANENGINE_ACCESS_TOKEN="your_token"
mcp-cn-commerce start oceanengine
```

### `health` - Health Check

Check the health and readiness of MCP servers.

```bash
# Check all servers
mcp-cn-commerce health

# Check specific servers
mcp-cn-commerce health oceanengine jd

# JSON output
mcp-cn-commerce health --json
```

**Status indicators:**
- `[READY]` - Module importable and credentials configured
- `[NO CREDS]` - Module importable but credentials missing
- `[NOT READY]` - Module not importable
- `[ERROR]` - Platform unknown or other error

**JSON output structure:**

```json
[
  {
    "platform": "oceanengine",
    "description": "Ocean Engine advertising platform",
    "module": "mcp_oceanengine.server",
    "status": "ready",
    "env_configured": true,
    "importable": true,
    "env_vars": {
      "OCEANENGINE_APP_KEY": "set",
      "OCEANENGINE_APP_SECRET": "set",
      "OCEANENGINE_ACCESS_TOKEN": "set"
    }
  }
]
```

### `info` - Version and Environment Info

Show detailed version and environment information.

```bash
# Human-readable output
mcp-cn-commerce info

# JSON output
mcp-cn-commerce info --json
```

**Output includes:**
- CLI version
- Python version
- Platform (OS)
- Repository root path
- Available server modules and their status

### `list` - List Available Platforms

List all supported MCP server platforms.

```bash
mcp-cn-commerce list
```

**Output:**

```
Available MCP servers:

Platform         Module                       Description
--------------------------------------------------------------------------------
oceanengine      mcp_oceanengine.server       Ocean Engine advertising platform
doudian          mcp_doudian.server           Douyin Shop e-commerce platform
jd               mcp_jd.server                JD.com e-commerce platform
taobao           mcp_taobao.server            Taobao e-commerce platform
pinduoduo        mcp_pinduoduo.server         Pinduoduo e-commerce platform
kuaishou         mcp_kuaishou.server          Kuaishou e-commerce platform
xiaohongshu      mcp_xiaohongshu.server       Xiaohongshu e-commerce platform
weixin-store     mcp_weixin_store.server      Weixin Store e-commerce platform

Total: 8 platforms
```

## Configuration File

The CLI supports JSON configuration files. Use `--config PATH` to specify a file, or place `mcp-cn-commerce.json` in the current directory or `~/.config/mcp-cn-commerce/config.json`.

```json
{
  "servers": ["oceanengine", "jd"],
  "verbose": false,
  "log_level": "info"
}
```

## Environment Variables

Each platform requires its own set of environment variables. The CLI checks for these during health checks.

| Platform | Required Variables |
|----------|-------------------|
| oceanengine | `OCEANENGINE_APP_KEY`, `OCEANENGINE_APP_SECRET`, `OCEANENGINE_ACCESS_TOKEN` |
| doudian | `DOUDIAN_APP_KEY`, `DOUDIAN_APP_SECRET`, `DOUDIAN_ACCESS_TOKEN` |
| jd | `JD_APP_KEY`, `JD_APP_SECRET`, `JD_ACCESS_TOKEN` |
| taobao | `TAOBAO_APP_KEY`, `TAOBAO_APP_SECRET`, `TAOBAO_ACCESS_TOKEN` |
| pinduoduo | `PINDUODUO_APP_KEY`, `PINDUODUO_APP_SECRET`, `PINDUODUO_ACCESS_TOKEN` |
| kuaishou | `KUAISHOU_APP_KEY`, `KUAISHOU_APP_SECRET`, `KUAISHOU_ACCESS_TOKEN` |
| xiaohongshu | `XIAOHONGSHU_APP_KEY`, `XIAOHONGSHU_APP_SECRET`, `XIAOHONGSHU_ACCESS_TOKEN` |
| weixin-store | `WEIXIN_STORE_APP_KEY`, `WEIXIN_STORE_APP_SECRET`, `WEIXIN_STORE_ACCESS_TOKEN` |

## Running Without Installation

You can also run the CLI directly using Python:

```bash
PYTHONPATH=shared python -m cli list
PYTHONPATH=shared python -m cli start oceanengine
```

## Examples

### Pre-flight Check

Before starting servers, verify everything is configured:

```bash
mcp-cn-commerce health --json | jq '.[] | select(.status != "ready")'
```

### Starting with Docker Compose

```yaml
services:
  oceanengine:
    build: .
    command: mcp-cn-commerce start oceanengine
    environment:
      - OCEANENGINE_APP_KEY=${OCEANENGINE_APP_KEY}
      - OCEANENGINE_APP_SECRET=${OCEANENGINE_APP_SECRET}
      - OCEANENGINE_ACCESS_TOKEN=${OCEANENGINE_ACCESS_TOKEN}
```

### Debugging

Use `--verbose` to see detailed logs:

```bash
mcp-cn-commerce --verbose health oceanengine
```
