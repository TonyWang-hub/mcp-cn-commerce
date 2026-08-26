# Frequently Asked Questions

## General

### What is mcp-cn-commerce?
A suite of MCP (Model Context Protocol) servers that let AI agents (Claude, ChatGPT, Gemini) read business data from Chinese e-commerce platforms. Think of it as a universal translator between your AI assistant and your store data on Douyin Shop, JD.com, Ocean Engine, and more.

### What makes this different from other MCP servers?
All existing Chinese-platform MCP servers focus on **content publishing** — posting videos, searching trending topics. mcp-cn-commerce is the first to cover **merchant business operations** — ad reports, orders, refunds, inventory.

### Is this affiliated with the platforms?
No. This is an independent open-source project. It uses each platform's official public API.

### Do I need to be a developer to use this?
Basic familiarity with terminal/command line is helpful. You need to configure environment variables and MCP client settings. If you can follow the Quick Start guide, you can use it.

## Platforms & Compatibility

### Which platforms are supported?
- **Phase 1 (done)**: 巨量引擎 (Ocean Engine), 巨量千川 (Qianchuan), 抖店 (Douyin Shop), 京东 (JD.com)
- **Phase 2 (planned)**: 淘宝 (Taobao), 拼多多 (Pinduoduo)
- **Phase 3 (planned)**: 快手 (Kuaishou), 小红书 (Xiaohongshu), 微信小店 (WeChat Store)

### Do I need a business license?
- **抖店**: Enterprise or individual business license required
- **京东**: Enterprise license required
- **巨量引擎**: Developer account with approved app
- **拼多多**: Individual sellers can access (Phase 2)
- **淘宝**: Enterprise license effectively required for order APIs — see below

### How do I get 淘宝 (Taobao) API credentials?
1. Register a developer account at [open.taobao.com](https://open.taobao.com)
2. Create an app — merchants connecting their own shop should pick 自用型应用 (self-use app)
3. Apply for the API permissions this server uses:
   - Orders: `taobao.trades.sold.get`, `taobao.trade.fullinfo.get`, `taobao.trades.sold.increment.get`
   - Products: `taobao.items.onsale.get`, `taobao.item.get`
   - Refunds: `taobao.refunds.receive.get`, `taobao.refund.get`
   - Logistics / reviews / shop: `taobao.logistics.trace.search`, `taobao.traderates.get`, `taobao.shop.get`
4. Complete the OAuth authorization to obtain an `access_token` (it expires — refresh per the platform's docs for your app type)
5. Set `TAOBAO_APP_KEY`, `TAOBAO_APP_SECRET`, `TAOBAO_ACCESS_TOKEN`

Platform rules change often — the 开发者入驻 page and each API's permission package on open.taobao.com are the source of truth.

### Can an individual shop (个人店) use the Taobao server?
Partly, and probably not for the part you want. Taobao's open platform does let individuals register as developers, but the order APIs (`taobao.trades.sold.get`, `taobao.trade.fullinfo.get`, and friends) expose consumer personal data, so they sit behind a separate high-sensitivity permission review that in practice requires an enterprise entity (business license) plus a signed data-security agreement. An individual C-shop generally can't clear that review.

Net effect for an individual shop: **product and shop data is usually reachable, order data usually isn't.** For full order access, register the app under an enterprise entity.

### Which AI clients are compatible?
Any MCP-compatible client: Claude Desktop, Cherry Studio, Kimi Work, Cline, Continue, and others.

### Can I use this on Windows / macOS / Linux?
Yes. Python 3.11+ on any OS.

## Security

### Where do my API credentials go?
They stay in environment variables on your machine. The code reads them locally and connects directly to platform APIs. No credentials are ever sent to any third-party server.

### Can AI agents modify my store data?
No. All tools are read-only by default. AI agents can analyze your data but cannot create, modify, or delete anything.

### How do I report a security issue?
See [SECURITY.md](../SECURITY.md). Please report vulnerabilities privately — do not open a public issue.

## Development & Contributing

### How do I add a new platform?
1. Create `servers/<platform>/` with the standard structure
2. Extend `CommerceMCPBase` from `shared/cn_commerce_base.py`
3. Set `BASE_URL`, `sign_method`, and define tool functions
4. Add tests and update documentation

See [CONTRIBUTING.md](../CONTRIBUTING.md) for details.

### What's the shared base class?
`CommerceMCPBase` (in `shared/cn_commerce_base.py`) encapsulates the common pattern across all Chinese e-commerce APIs:
- Request signing (MD5 or HMAC-MD5)
- Parameter sorting and serialization
- Pagination handling
- Error parsing and translation

### Will there be CLI support?
Yes — Phase 2 will add CLI entry points that share the same core logic as the MCP servers.

### Can I use this as a library instead of MCP?
The server code is structured so you can import and use the API wrappers directly, outside of MCP. This is not the primary use case but is supported.

## Troubleshooting

### "Sign does not match" errors
Most common cause: timestamp skew. Ensure your system clock is accurate. Some platforms are very strict about time drift.

### "App key not exist" or "Invalid access token"
Verify your credentials: check that environment variables are set correctly and tokens haven't expired. Ocean Engine tokens expire every 24 hours.

### Tests fail locally but pass in CI
Check that you don't have real credentials set — tests use mock responses. If real environment variables are set, tests might attempt real API calls.
