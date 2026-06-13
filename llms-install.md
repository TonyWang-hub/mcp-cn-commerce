# LLM 安装引导 / llms-install.md

> This file guides an AI agent (e.g. Cline) through installing and configuring
> **mcp-cn-commerce**. Read it top to bottom and follow the steps in order.

## What this is

`mcp-cn-commerce` is a suite of **read-only** MCP servers for Chinese e-commerce
*merchant operations data* (orders, products, after-sales, ad reports) across 8
platforms. It ships as a single PyPI package; each platform is a separate stdio
server selected via client config.

## Requirements

- Python **3.11+** and `pip` available on PATH.
- Per-platform API credentials, supplied as **environment variables**. The agent
  **cannot** obtain these — they must be requested from the user (see Step 3).

## Step 0 — Check the Python version FIRST

This package requires Python **3.11+**. On macOS the default `python3` is often
3.9, in which case `pip install` fails with a *misleading* error
(`No matching distribution found for mcp-cn-commerce` — it does NOT mention the
Python version). Always check first:

```bash
python3 --version
```

If it is below 3.11, look for a newer interpreter (`python3.11`, `python3.12`,
`python3.13`) and use that explicitly in the next step. If none exists, tell the
user to install Python 3.11+ before continuing.

## Step 1 — Install the package

Use a 3.11+ interpreter (substitute `python3.12` etc. if `python3` is too old):

```bash
python3 -m pip install mcp-cn-commerce
```

Verify:

```bash
mcp-cn-commerce --help
```

The install provides one launch command per platform:

| Platform | Command | Required env vars |
|---|---|---|
| 巨量引擎/千川 Ocean Engine | `mcp-cn-oceanengine` | `OCEANENGINE_APP_KEY`, `OCEANENGINE_APP_SECRET`, `OCEANENGINE_ACCESS_TOKEN` |
| 抖店 Douyin Shop | `mcp-cn-doudian` | `DOUDIAN_APP_KEY`, `DOUDIAN_APP_SECRET`, `DOUDIAN_SHOP_ID`, `DOUDIAN_ACCESS_TOKEN` |
| 京东 JD.com | `mcp-cn-jd` | `JD_APP_KEY`, `JD_APP_SECRET`, `JD_ACCESS_TOKEN` |
| 淘宝 Taobao | `mcp-cn-taobao` | (see project docs/platforms.md) |
| 拼多多 Pinduoduo | `mcp-cn-pinduoduo` | (see docs/platforms.md) |
| 快手 Kuaishou | `mcp-cn-kuaishou` | (see docs/platforms.md) |
| 小红书 Xiaohongshu | `mcp-cn-xiaohongshu` | (see docs/platforms.md) |
| 微信小店 WeChat Store | `mcp-cn-weixin-store` | (see docs/platforms.md) |

## Step 2 — Ask which platforms to enable

Do **not** configure all 8. Ask the user which platform(s) they want (most users
need 1–3). Only configure those servers.

## Step 3 — Ask the user for credentials

The agent must **not** invent or guess credentials. For each chosen platform, ask
the user to paste the required values listed in the table above. Each platform's
credentials come from that platform's open-platform console (links in the project
README "平台覆盖" table). If the user does not have them yet, stop and tell them to
obtain the App Key / App Secret / Access Token first.

## Step 4 — Write the MCP client config

Add an entry per chosen platform. Cline uses `cline_mcp_settings.json`; the shape
is the standard `mcpServers` block. Example for Ocean Engine + Douyin Shop:

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "mcp-cn-oceanengine",
      "env": {
        "OCEANENGINE_APP_KEY": "<from user>",
        "OCEANENGINE_APP_SECRET": "<from user>",
        "OCEANENGINE_ACCESS_TOKEN": "<from user>"
      }
    },
    "doudian": {
      "command": "mcp-cn-doudian",
      "env": {
        "DOUDIAN_APP_KEY": "<from user>",
        "DOUDIAN_APP_SECRET": "<from user>",
        "DOUDIAN_SHOP_ID": "<from user>",
        "DOUDIAN_ACCESS_TOKEN": "<from user>"
      }
    }
  }
}
```

## Step 5 — Verify

Restart/reload the MCP client so it picks up the new server(s). Confirm the
platform's tools appear (e.g. ask the agent to list available tools, or call a
read-only tool like a recent-orders query). All tools are read-only, so a test
call cannot modify any data.

## Notes

- Everything runs **locally**; credentials never leave the user's machine.
- Ocean Engine access tokens expire in ~24h — if calls start failing with auth
  errors, the user must refresh `OCEANENGINE_ACCESS_TOKEN`.
- Full per-platform auth details: `docs/platforms.md` in the repo.
