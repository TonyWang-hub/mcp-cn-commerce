# mcp-cn-commerce — Chinese E-Commerce Platform MCP Servers

[![Test](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml/badge.svg)](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-MCP-blueviolet)](https://modelcontextprotocol.io/)
[![PyPI version](https://img.shields.io/pypi/v/mcp-cn-commerce)](https://pypi.org/project/mcp-cn-commerce/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> 🛒 **Let AI agents read Chinese e-commerce merchant business data.**
> Not content publishing — **business operations** MCP connectors for AI agents like Claude, ChatGPT, Gemini.
>
> **Keywords**: MCP Server, Model Context Protocol, Chinese e-commerce, AI agent, e-commerce data, 电商 MCP, 抖店, 京东, 巨量引擎, Ocean Engine, Douyin Shop, JD.com, Taobao, Pinduoduo, Python MCP, AI business intelligence, agent tool

**English** | [简体中文](README.md)

---

## Table of Contents

- [What is mcp-cn-commerce?](#what-is-mcp-cn-commerce)
- [Why This Project](#why-this-project)
- [Supported Platforms](#platforms)
- [Quick Start](#quick-start)
  - [Docker](#docker-recommended--no-local-python-setup)
- [Architecture](#architecture)
- [Tools Reference](#tools-per-server)
- [Security](#security)
- [Docker](docs/docker.md) - Docker 部署与配置
- [Examples](docs/examples.md) - 使用示例和场景
- [FAQ](README.md#常见问题)
- [Contributing](CONTRIBUTING.md)
- [Roadmap](#roadmap)

---

## What is mcp-cn-commerce?

A **monorepo of independent MCP (Model Context Protocol) servers** that give AI agents structured, type-safe access to Chinese e-commerce platform business data. Each server wraps one platform's open API:

- **巨量引擎 (Ocean Engine)** — advertising campaign, report, and account data
- **抖店 (Douyin Shop)** — orders, products, refunds, shop management
- **京东 (JD.com)** — orders, products, shop information
- Additional included adapters: **淘宝**, **拼多多**, **快手**, **小红书**, **微信小店**

All tools are **read-only** by default — AI agents can analyze your business data but cannot modify anything.

## Why This Project

This project focuses on authorized merchant operations data, shared request reliability and deterministic reporting.

- Separate stdio services configured with each merchant's granted permissions.
- Shared connection pools, rate limits, retries, metrics and redaction.
- Explicit money and time contracts; reports flag missing data and incomplete pagination.

Official APIs, official MCP services and this third-party adapter are distinct. See [official access evidence](docs/official-access-status.md).

## Platforms

Eight platform adapters are included. Xiaohongshu has nine business tool mappings based on current official schemas; the four retained review, shop, promotion and coupon entry points return an explicit unsupported error without sending a request. Registered tool counts include these retained entry points. Tool registration is not proof of successful merchant API access. App eligibility, authorization, endpoint versions and account permissions require platform-specific verification. See [platform contracts](docs/platforms.md) and [official access evidence](docs/official-access-status.md). CI covers Python 3.11/3.12/3.13; use the workflow result for the exact commit as verification evidence.

## Quick Start

### Docker (recommended — no local Python setup)

```bash
# Build the image
docker build -t mcp-cn-commerce .

# Build the development target to run tests
docker build --target development -t mcp-cn-commerce-dev .
docker run --rm mcp-cn-commerce-dev make test

# Run a platform server (Ocean Engine example)
docker run --rm -i --env-file .env mcp-cn-commerce mcp-cn-oceanengine
```

See [Docker documentation](docs/docker.md) for full usage, MCP client configuration, and Docker Compose shortcuts.

### Installation

#### From PyPI (recommended)

```bash
# One install, all 8 platforms included
pip install mcp-cn-commerce
```

All platform servers are bundled. Choose which to use via your MCP client configuration.

#### From GitHub Releases

```bash
# Visit the latest Release and download the .whl file
# https://github.com/TonyWang-hub/mcp-cn-commerce/releases/latest

# Download the wheel shown on the latest Release page, then install that local file.
python -m pip install /path/to/downloaded.whl
```

#### From Git (always latest)

```bash
pip install git+https://github.com/TonyWang-hub/mcp-cn-commerce.git
```

#### For development

```bash
git clone https://github.com/TonyWang-hub/mcp-cn-commerce.git
cd mcp-cn-commerce
pip install -e ".[dev]"
```

### Configuration

Set credentials via environment variables:

```bash
# 巨量引擎 (Ocean Engine) — Advertising platform
export OCEANENGINE_APP_KEY="your_app_key"
export OCEANENGINE_APP_SECRET="your_app_secret"
export OCEANENGINE_ACCESS_TOKEN="your_access_token"

# 抖店 (Douyin Shop) — Douyin merchant platform
export DOUDIAN_APP_KEY="your_app_key"
export DOUDIAN_APP_SECRET="your_app_secret"
export DOUDIAN_SHOP_ID="your_shop_id"
export DOUDIAN_ACCESS_TOKEN="your_access_token"

# 京东 (JD.com) — Jingdong e-commerce
export JD_APP_KEY="your_app_key"
export JD_APP_SECRET="your_app_secret"
export JD_ACCESS_TOKEN="your_access_token"
```

### Add to Your MCP Client

Works with **Claude Desktop**, **Cherry Studio**, **Kimi Work**, and any MCP-compatible AI client:

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "mcp-cn-oceanengine"
    },
    "doudian": {
      "command": "mcp-cn-doudian"
    },
    "jd": {
      "command": "mcp-cn-jd"
    }
  }
}
```

### Example: AI Agent Querying Your Business

Once connected, you can ask your AI agent questions like:

> "Show me this week's Ocean Engine campaign ROAS, sorted by spend"
> "Which Douyin Shop products are low on stock?"
> "How many JD refunds are pending approval?"
> "Compare my ad performance across Ocean Engine campaigns this month vs last month"

## Architecture

```
mcp-cn-commerce/
├── .github/workflows/test.yml       # CI: pytest on push (3.11/3.12/3.13)
├── shared/                           # Shared auth/signing/pagination
│   └── cn_commerce_base.py           # CommerceMCPBase — extend for new platforms
├── servers/                          # All platform servers (single package, start as needed)
│   ├── oceanengine/server.py         ├── doudian/server.py
│   ├── jd/server.py                  ├── taobao/server.py
│   ├── pinduoduo/server.py           ├── kuaishou/server.py
│   ├── xiaohongshu/server.py         └── weixin_store/server.py
├── docs/platforms.md                 # 8-platform API comparison & auth matrix
├── docs/docker.md                    # Docker deployment guide
├── Dockerfile                        # Multi-platform MCP server image
├── docker-compose.yml                # Local development shortcuts
├── README.md / README_en.md          # 简体中文 / English
└── LICENSE                           # MIT
```

Single-package architecture: `pip install mcp-cn-commerce` installs all 8 platform servers at once. Choose which to use via your MCP client configuration.

## Workflow Templates 🆕

Ready-to-use AI workflow templates with realistic Chinese example data. No API credentials needed to try.

| Template | Purpose | Target User | Demo |
|----------|---------|-------------|------|
| [Daily Report](templates/daily-report/) | Multi-platform GMV/order/refund summary | Operations / Boss | [View Demo](templates/daily-report/demo-output.md) |
| [Bad Review Alert](templates/bad-review-alert/) | Negative review monitoring + root cause | CS / QA | [View Demo](templates/bad-review-alert/demo-output.md) |
| [CS Classify](templates/cs-classify/) | Refund reason analysis + trend | CS Manager | [View Demo](templates/cs-classify/demo-output.md) |
| [Product Select](templates/product-select/) | Category heat + competitor pricing | Product Manager | [Example Data](templates/product-select/example-data.json) |
| [KOL Match](templates/kol-match/) | Influencer matching + ROI estimate | Ad Optimizer | [Example Data](templates/kol-match/example-data.json) |

### 📊 Daily Report Preview

```
┌────────┬──────────────┬──────────────┬────────┐
│ Metric │ Today        │ Yesterday    │ Change │
├────────┼──────────────┼──────────────┼────────┤
│ GMV    │ ¥86,965.00   │ ¥88,900.00   │ -2.2%  │
│ Orders │ 312          │ 309          │ +1.0%  │
│ AOV    │ ¥278.73      │ ¥287.70      │ -3.1%  │
│ Refund │ 5.1%         │ 4.6%         │ +0.5pp │
└────────┴──────────────┴──────────────┴────────┘

Platform Breakdown
┌──────────────────────┬──────────────┬──────┬────────┐
│ Platform             │ GMV          │ Ords │ Refund │
├──────────────────────┼──────────────┼──────┼────────┤
│ Douyin Shop          │ ¥28,950.00   │ 156  │ 5.1%   │
│ JD.com               │ ¥45,670.00   │ 89   │ 3.4%   │
│ Xiaohongshu          │ ¥12,345.00   │ 67   │ 7.5% ⚠️│
└──────────────────────┴──────────────┴──────┴────────┘

⚠️ Alerts:
🔴 Xiaohongshu refund rate 7.5% — exceeds 5% threshold
🔴 Low stock: "Summer T-Shirt White XL" — 32 units left
```

### 🚨 Bad Review Alert Preview

```
Root Cause Distribution
  Quality Issue   ████████████████████  40% (2)
  Color Mismatch  ██████████           20% (1)
  Wrong Size      ██████████           20% (1)
  Poor Craft      ██████████           20% (1)

Analysis:
1. "Faded after one wash" — Douyin Shop ⭐
   → Action: Apologize + resend, check batch quality

2. "Shoes run small" — Pinduoduo ⭐⭐
   → Action: Add "runs small" note to size chart

3. "Color very different from photos" — Xiaohongshu ⭐⭐
   → Action: Retake product photos in natural light
```

See all templates: [`templates/`](templates/)

## Tools Summary

| Server | Tools | Categories |
|---|---|---|
| oceanengine | 23 | Ads, Qianchuan, Star, Creative, Audience, Optimization |
| doudian | 25 | Orders, Products, Refunds, Logistics, Reviews, Live, Traffic, Marketing, Billing, Shop |
| jd | 20 | Orders, Products, After-Sale, Logistics, Reviews, Pricing, Inventory, Marketing, Shop |
| taobao | 18 | Orders, Products, Refunds, Logistics, Reviews, Shop, Marketing, Categories |
| pinduoduo | 18 | Orders, Products, Refunds, Logistics, Reviews, Shop, Marketing, Affiliate |
| kuaishou | 17 | Orders, Products, Refunds, Logistics, Reviews, Shop, Marketing |
| xiaohongshu | 18 | Orders, Products, Refunds, Logistics, Reviews, Shop, Marketing, Inventory, Finance |
| weixin_store | 16 | Orders, Products, Refunds, Logistics, Shop, Marketing, Supply Chain, Categories |
| **Total** | **155** | Platform tools + 5 shared tools each |

Every server also exposes **5 cross-platform shared tools** (counted above): `get_metrics`
(per-endpoint latency / success / error stats), `get_traces` (recent request traces),
`get_alerts` (alert-rule evaluation against live metrics), `export_data` (export records to CSV/JSON), and `build_daily_report`
(deterministic reports with explicit timezone and completeness). Request tracing and metrics are collected automatically on every call.

For full tool details, see the source code in each `servers/<platform>/server.py` file.
| `get_product_list` | Product catalog with pricing and stock | `/product/list` |
| `get_shop_info` | Merchant shop information | `/shop/info` |

## Security

This project handles sensitive e-commerce API credentials. Our security guarantees:

- 🔒 **Runs locally** — credentials are loaded locally; required authentication is sent to the relevant platform API
- 📖 **Open source** — every line of code is auditable
- 👁️ **Read-only by default** — all platform tools only read data; zero write/modify/delete operations
- 📡 **No telemetry** — this project does not report usage to a project-owned service; tool results are returned to your configured MCP/AI client
- 🖥️ **Direct API calls** — connects directly to platform APIs; no intermediate server or proxy
- 🔑 **Env-var config** — credentials are loaded from environment variables, never hardcoded

## 💼 Pro (private beta)

The open-source version is complete and free forever (single shop, manual token management). **Pro** adds what agencies / ISVs / multi-shop merchants need: **automatic OAuth token refresh** (Ocean Engine's 24h expiry handled for you), a local **`auth` wizard** for the authorization-code flow, and **multi-shop management** (`shops.yaml`, alias routing, cross-shop aggregation) — still fully local, offline license, zero telemetry. Phase 1 covers Ocean Engine / Douyin Shop / JD.

> 🎯 Recruiting seed users: free beta access in exchange for real-world feedback.
> [Open a Pro inquiry](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/new?labels=pro-inquiry&title=%5BPro%5D%20Inquiry)

## Roadmap

### Phase 1 — Foundation ✅
- 巨量引擎: Ad campaign & report read APIs
- 巨量千川: E-commerce advertising (shared Ocean Engine auth)
- 抖店: Order, product, after-sale read APIs
- 京东: Order, product, shop read APIs

### Phase 2 — Mid-Tier Expansion ✅
- 淘宝 (Taobao): Full Top API integration — orders, products, logistics
- 拼多多 (Pinduoduo): Orders, products, promotion tools

### Phase 3 — Long-Tail Coverage ✅
- 快手 (Kuaishou): Orders, products, logistics
- 小红书 (Xiaohongshu): Orders, products, inventory
- 微信小店 (WeChat Store): Orders, products, after-sale

### Phase 4 — Exploratory ⬜
- 闲鱼, 美团, 饿了么 (API access pending policy)

## Related Resources

- [Model Context Protocol (MCP) Documentation](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Claude Desktop — MCP Support](https://claude.ai/download)
- [Cherry Studio — Multi-Model MCP Client](https://cherry-ai.com/)
- [Platform API Comparison](docs/platforms.md)

## Citation

If you use mcp-cn-commerce in your research or project:

```bibtex
@software{mcp-cn-commerce,
  title = {mcp-cn-commerce: MCP Servers for Chinese E-Commerce Platforms},
  year = {2026},
  url = {https://github.com/TonyWang-hub/mcp-cn-commerce}
}
```

## License

MIT — see [LICENSE](LICENSE).
