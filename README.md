# mcp-cn-commerce

Chinese e-commerce platform MCP servers — let AI agents (Claude Cowork, Kimi Work, etc.) read merchant business data.

## Platforms

| Platform | Phase | Status |
|---|---|---|
| 巨量引擎 (Ocean Engine) — advertising data | 1 | ⬜ |
| 抖店 (Douyin Shop) — orders, products, refunds | 1 | ⬜ |
| 京东 (JD) — orders, products | 1 | ⬜ |
| 淘宝 (Taobao) — orders, products | 2 | ⬜ |
| 拼多多 (Pinduoduo) — orders, products | 2 | ⬜ |
| 快手 (Kuaishou) — orders, products | 3 | ⬜ |
| 小红书 (Xiaohongshu) — orders, products | 3 | ⬜ |
| 微信小店 (WeChat Store) — orders, products | 3 | ⬜ |

> Phase 4: 闲鱼, 美团, 饿了么 (restricted APIs)

## Architecture

```
mcp-cn-commerce/
├── shared/                     # Shared auth/signing/error handling
├── servers/
│   ├── oceanengine/            # 巨量引擎 MCP

│   ├── doudian/                # 抖店 MCP
│   └── jd/                     # 京东 MCP
└── docs/
```

Each `servers/<platform>/` is an independent MCP server. Users install only what they need:
```bash
pip install mcp-cn-commerce[oceanengine]
```

## Security

- Runs locally — API credentials never leave your machine
- Open source — audit the code yourself
- Read-only by default — advertising reports, order queries, product info
- No write operations unless you explicitly configure them

## License

MIT
