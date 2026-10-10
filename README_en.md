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

> **Core 0.1.6 release notes:** Check the [v0.1.6 GitHub Release](https://github.com/TonyWang-hub/mcp-cn-commerce/releases/tag/v0.1.6), [PyPI 0.1.6](https://pypi.org/project/mcp-cn-commerce/0.1.6/) and [release-readiness record](docs/release-readiness.md) for artifact availability and the corresponding source commit. Every SDK in Core 0.1.6 has `live_verified=false`; real merchant acceptance and back-office reconciliation have not been completed.
>
> [Project and inquiry status](docs/project-status.md) · [Engineering/release evidence](docs/release-readiness.md) · [Changelog](CHANGELOG.md)

---

## Table of Contents

- [What is mcp-cn-commerce?](#what-is-mcp-cn-commerce)
- [Why This Project](#why-this-project)
- [Supported Platforms](#platforms)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Tools Reference](#tools-summary)
- [Security](#security)
- [Docker](docs/docker.md) - Docker 部署与配置
- [Examples](docs/examples.md) - 使用示例和场景
- [FAQ](README.md#常见问题)
- [Contributing](CONTRIBUTING.md)
- [Roadmap](#roadmap)

---

## What is mcp-cn-commerce?

A **monorepo of independent MCP (Model Context Protocol) servers** that give AI agents structured, type-safe access to Chinese e-commerce platform business data. Each server wraps one platform's open API:

- **Douyin Shop and Taobao** — documented order/refund queries, ready for scoped merchant acceptance once authorized inputs are available.
- **JD** — documented orders, shop information and two after-sale queries; complete refund collection remains unsupported.
- **Kuaishou, Xiaohongshu and WeChat Store** — documented subsets of order/refund reads; authorization identity and collection boundaries differ.
- **Ocean Engine / Qianchuan** — the reviewed SDK scope is advertiser information and balance; reports and the authorization account tree remain incomplete.
- **Pinduoduo** — platform entry points exist, but merchant SDK reads are disabled pending complete official business schemas. Legacy MCP names do not establish verified support.

Eight MCP platform entry points expose **155 registered tools**, including compatibility and unsupported entries. Youzan is an additional SDK-only platform. Registration, a documented contract, an SDK callable mapping and merchant live acceptance are separate states.

All tools are **read-only** by default — AI agents can analyze your business data but cannot modify anything.

## Why This Project

This project focuses on authorized merchant operations data, shared request reliability and deterministic reporting.

- Separate stdio services configured with each merchant's granted permissions.
- Shared connection pools, rate limits, retries, metrics and redaction.
- Explicit money and time contracts; reports flag missing data and incomplete pagination.

Official APIs, official MCP services and this third-party adapter are distinct. See [official access evidence](docs/official-access-status.md).

## Platforms

The [current SDK operation table](docs/sdk-integration.md#catalogue-and-evidence-status) is the source for per-operation support. All SDK `live_verified` values remain false.

| Platform | Documented SDK scope | Remaining boundary |
| --- | --- | --- |
| Douyin Shop | Orders list/detail; refunds list/detail | General shop info unsupported; payment discounts, actual refunds and 90-day creation scope need merchant checks |
| Taobao | Orders list/increment/detail; refunds list/detail | Shop info is transport-only; app fields and historical payment basis require verification |
| JD | Orders list/detail, shop info, after-sale list/refund detail | Two after-sale queries do not cover all refunds; generic refunds and Pro refund Source remain unavailable |
| Pinduoduo | No callable merchant SDK reads | Complete official business schemas are missing |
| Kuaishou | Orders/refunds list/detail; shop info | Pro open_id-to-shop authorization binding remains unresolved |
| Xiaohongshu | Orders/refunds list/detail | Query/completed-refund time units needed by Source remain unresolved |
| WeChat Store | Orders/refunds list/detail; shop info | Actual permissions/live cursor checks pending; Pro cross-tenant delegation for one shared component remains a gap |
| Ocean Engine | Advertiser info; account balance | Report migration and account-tree authorization are incomplete |

Product, inventory, logistics, reviews, marketing and billing registrations are not a claim of complete current API support. See [platform contracts](docs/platforms.md), [official evidence](docs/official-access-status.md) and [release readiness](docs/release-readiness.md).

Core provides `contract_status`, `supported` and `live_verified` in each platform business tool's MCP `tools/list` description. Operations marked `supported=false` reject before any platform request. Retained historical tools are labelled `unverified`; `supported=true` only denotes a retained callable mapping, with permissions, contract scope and merchant acceptance checked separately. The five shared tools keep their existing descriptions, and all 155 tool names and input/output schemas remain compatible.

## Quick Start

### Install Core 0.1.6

Use Python 3.11+; the commands below use Python 3.12 and a project virtual environment:

```bash
mkdir -p mcp-cn-commerce-0.1.6
cd mcp-cn-commerce-0.1.6
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install "mcp-cn-commerce==0.1.6"
mcp-cn-commerce --version
```

To install from source, first confirm that the `v0.1.6` tag exists in the repository (the verification command must succeed), then check out that tag:

```bash
git clone https://github.com/TonyWang-hub/mcp-cn-commerce.git
cd mcp-cn-commerce
set -e
git rev-parse --verify 'refs/tags/v0.1.6^{commit}' >/dev/null
git checkout --detach v0.1.6
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements-lock.txt .
```

For development, use an editable install in the same project virtual environment:

```bash
python -m pip install -c requirements-lock.txt -e ".[dev]"
```

The install stays in `.venv` and does not default to changing global Python. Set a desktop MCP client's `command` to the executable's absolute path under the project `.venv/bin/`; activating a terminal environment alone does not change a desktop application's PATH. Use the equivalent virtual-environment paths on other operating systems. Check the [v0.1.6 GitHub Release](https://github.com/TonyWang-hub/mcp-cn-commerce/releases/tag/v0.1.6), [PyPI 0.1.6](https://pypi.org/project/mcp-cn-commerce/0.1.6/) and [release-readiness record](docs/release-readiness.md) for artifact availability and the corresponding source commit. For container deployment, see the [deployment guide](docs/docker.md); containers are not required for source installation.

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

Replace `/absolute/path/to/mcp-cn-commerce` with the absolute path to your selected installation directory. Configure merchant credentials in the desktop client's `env` settings; shell exports apply only to processes that inherit that environment.

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "/absolute/path/to/mcp-cn-commerce/.venv/bin/mcp-cn-oceanengine"
    },
    "doudian": {
      "command": "/absolute/path/to/mcp-cn-commerce/.venv/bin/mcp-cn-doudian"
    },
    "jd": {
      "command": "/absolute/path/to/mcp-cn-commerce/.venv/bin/mcp-cn-jd"
    }
  }
}
```

### Example: AI Agent Querying Your Business

After confirming the operation contract and the app's actual permissions, scoped read-only examples include:

> “Read Douyin Shop orders in this fixed update window and identify the remaining pages and details.”
> “Show the state, amount and completion time of this Taobao refund.”
> “Read the balance of this authorized advertiser account.”
> “Export the normalized records I supplied and flag missing fields.”

First merchant calls still require comparison with the platform's back office.

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

Single-package architecture: the selected Core version bundles all 8 platform servers. Choose the version and verified operation scope first, then configure your MCP client.

## Workflow Templates 🆕

Templates and previews use simulated data. No API credentials are needed, and these demos do not prove that a platform data source is connected. Raw platform records require pagination, normalization and explicit coverage before reporting.

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

This is a registration count, including legacy/unverified and unsupported entries. It is not the number of documented SDK operations or live merchant APIs.

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

## Security

This project handles sensitive e-commerce API credentials. Our security guarantees:

- 🔒 **Runs locally** — credentials are loaded locally; required authentication is sent to the relevant platform API
- 📖 **Open source** — every line of code is auditable
- 👁️ **Read-only by default** — all platform tools only read data; zero write/modify/delete operations
- 📡 **No telemetry** — this project does not report usage to a project-owned service; tool results are returned to your configured MCP/AI client
- 🖥️ **Direct API calls** — connects directly to platform APIs; no intermediate server or proxy
- 🔑 **Env-var config** — credentials are loaded from environment variables, never hardcoded

## 💼 Pro (private beta)

Core remains free under the unchanged MIT license. Platform adapters, explicit-credential clients, money/time normalization and deterministic multi-shop `build_daily_report` calculations are already public Core features. Multi-shop calculation does not require Pro; the host supplies collected records and truthful completeness declarations. MCP processes use one credential configuration per platform process, while SDK hosts can manage multiple explicit snapshots.

Pro reuses those public capabilities and adds authorization lifecycle governance, encrypted application/grant storage, tenant/shop ACLs, persistent collection with page evidence and restart recovery, report history, scheduling and audit. It does not make the public multi-shop algorithm exclusive or imply support for every historical MCP registration. Supported providers and collection sources remain subject to their documented limits and merchant acceptance.

Pro is maintained, validated and released separately from Core as a private offering; its version, capabilities and acceptance status are not established by a Core version or CI run. Core 0.1.6 contains no private Pro source or artifacts. Real merchant `live_verified` remains false; business acceptance and back-office reconciliation have not been completed.

A permitted, registered loopback callback can use the CLI authorization flow; HTTPS partner callbacks and user identity require server integration. Pro does not currently promise Ocean Engine/Qianchuan automatic renewal or reports. Old `shops.yaml` files are not automatically imported. Data flow depends on deployment: platform requests, remote partner APIs and explicitly configured notifications are separate from local storage and offline licensing.

> 🎯 Recruiting seed users: free beta access in exchange for real-world feedback.
> [Open a Pro inquiry](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/new?labels=pro-inquiry&title=%5BPro%5D%20Inquiry)

Pro remains privately delivered. The free seed-user beta commitment above is preserved; local trial timing does not replace arrangements already offered to beta participants. Commercial integration and redistribution rights require the applicable Pro terms, not the existence of an installable package.

Core installation requires neither Pro nor the separate commercial Client. CI checks source boundaries before dependency installation and inspects both wheel and sdist before installation/public upload to catch accidental private imports, dependencies and payloads. See [Core/Pro boundaries and checks](docs/core-pro-boundary.md). This packaging gate preserves public features; it is not a claim of merchant API acceptance or absolute source-code secrecy.

## Roadmap

### Completed engineering

- Eight MCP platform entry points, common tools and an explicit-credential platform SDK; compatibility registrations remain in the catalogue.
- Documented read-contract migrations for the specific operations in the current SDK table.
- Exact-revision regression, installation and real MCP transport checks; see [engineering evidence](docs/release-readiness.md).

### Current acceptance and contract work

- Start with authorized Douyin Shop/Taobao samples on 1–2 platforms: pagination, money/time fields, back-office comparison and authorization lifecycle.
- Obtain PDD business schemas, XHS Source time contracts, JD refund coverage and outstanding Pro identity/delegation contracts.
- Verify broad product/inventory/logistics/review/marketing/ad/billing domains individually. Historical phase completion does not establish current support for every domain.
- Xianyu, Meituan and Ele.me remain exploratory.

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
