# mcp-cn-commerce

Chinese e-commerce platform MCP servers — let AI agents (Claude Cowork, Kimi Work, etc.) read merchant business data.

[![Test](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml/badge.svg)](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml)

## Platforms

| Platform | Phase | Status | Tests |
|---|---|---|---|
| 巨量引擎 (Ocean Engine) — advertising data | 1 | ✅ | 24 |
| 抖店 (Douyin Shop) — orders, products, refunds | 1 | ✅ | 31 |
| 京东 (JD) — orders, products | 1 | ✅ | 19 |
| 淘宝 (Taobao) — orders, products | 2 | ⬜ | - |
| 拼多多 (Pinduoduo) — orders, products | 2 | ⬜ | - |
| 快手 (Kuaishou) — orders, products | 3 | ⬜ | - |
| 小红书 (Xiaohongshu) — orders, products | 3 | ⬜ | - |
| 微信小店 (WeChat Store) — orders, products | 3 | ⬜ | - |

> Phase 4: 闲鱼, 美团, 饿了么 (restricted APIs)
> **77 tests** across all Phase 1 servers

## Quick Start

```bash
# Install a specific server
pip install mcp-cn-commerce[oceanengine]

# Or all Phase 1 servers
pip install mcp-cn-commerce[all]
```

Configure via environment variables:

```bash
# 巨量引擎
export OCEANENGINE_APP_KEY="your_app_key"
export OCEANENGINE_APP_SECRET="your_app_secret"
export OCEANENGINE_ACCESS_TOKEN="your_token"

# 抖店
export DOUDIAN_APP_KEY="your_app_key"
export DOUDIAN_APP_SECRET="your_app_secret"
export DOUDIAN_SHOP_ID="your_shop_id"
export DOUDIAN_ACCESS_TOKEN="your_token"

# 京东
export JD_APP_KEY="your_app_key"
export JD_APP_SECRET="your_app_secret"
export JD_ACCESS_TOKEN="your_token"
```

Add to your MCP client (Claude Desktop, Cherry Studio, etc.):

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "mcp-cn-oceanengine"
    }
  }
}
```

## Architecture

```
mcp-cn-commerce/
├── .github/workflows/test.yml   # CI: pytest on push
├── shared/                       # Shared auth/signing/error handling
├── servers/
│   ├── oceanengine/              # 巨量引擎 MCP (5 tools)
│   │   ├── src/mcp_oceanengine/
│   │   └── tests/
│   ├── doudian/                  # 抖店 MCP (5 tools)
│   │   ├── src/mcp_doudian/
│   │   └── tests/
│   └── jd/                       # 京东 MCP (4 tools)
│       ├── src/mcp_jd/
│       └── tests/
└── docs/
    └── platforms.md              # Platform API comparison
```

Each `servers/<platform>/` is an independent MCP server. Users install only what they need.

## Tools per Server

| Server | Tools |
|---|---|
| oceanengine | `get_advertiser_info`, `get_campaign_report`, `get_ad_detail_report`, `list_campaigns`, `get_account_balance` |
| doudian | `get_order_list`, `get_order_detail`, `get_product_list`, `get_refund_list`, `get_shop_info` |
| jd | `get_order_list`, `get_order_detail`, `get_product_list`, `get_shop_info` |

## Security

- **Runs locally** — API credentials never leave your machine
- **Open source** — audit the code yourself
- **Read-only by default** — all tools only read data, no write operations

## License

MIT
