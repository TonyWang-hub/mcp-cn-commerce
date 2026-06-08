# mcp-cn-commerce

[![Test](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml/badge.svg)](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> 让 AI Agent 直接读取中国电商平台的商家经营数据。不做内容发布，只做**经营数据**的 MCP 连接器。

[English](README.md) | **简体中文**

## 平台覆盖

| 平台 | 类型 | Phase | 状态 | 测试 |
|---|---|---|---|---|
| 巨量引擎 | 广告投放 | 1 | ✅ | 24 |
| 巨量千川 | 电商广告 | 1 | ✅ | (同上) |
| 抖店 | 电商店铺 | 1 | ✅ | 31 |
| 京东 | 电商店铺 | 1 | ✅ | 19 |
| 淘宝 | 电商店铺 | 2 | ⬜ | - |
| 拼多多 | 电商店铺 | 2 | ⬜ | - |
| 快手 | 电商店铺 | 3 | ⬜ | - |
| 小红书 | 电商店铺 | 3 | ⬜ | - |
| 微信小店 | 电商店铺 | 3 | ⬜ | - |

> Phase 4: 闲鱼、美团、饿了么（API 受限，待政策明朗）
> **77 个测试**，Phase 1 三平台全部通过

## 为什么选择这个？

国内已有的 MCP Server 全是**内容发布**（发视频、搜热搜），没有一个是**商家经营**（拉广告数据、看订单、管售后）。

| | 现有 MCP（HuiMei/Astron 等） | mcp-cn-commerce |
|---|---|---|
| 做什么 | 发视频、搜热搜 | 拉广告报表、查订单 |
| 目标用户 | 自媒体/创作者 | 电商老板/运营 |
| 数据类型 | 内容数据 | **经营数据** |

## 快速开始

```bash
# 安装单个平台
pip install mcp-cn-commerce[oceanengine]

# 或全部 Phase 1
pip install mcp-cn-commerce[all]
```

### 配置凭证

```bash
# 巨量引擎/千川
export OCEANENGINE_APP_KEY="你的 App Key"
export OCEANENGINE_APP_SECRET="你的 App Secret"
export OCEANENGINE_ACCESS_TOKEN="你的 Access Token"

# 抖店
export DOUDIAN_APP_KEY="你的 App Key"
export DOUDIAN_APP_SECRET="你的 App Secret"
export DOUDIAN_SHOP_ID="你的店铺 ID"
export DOUDIAN_ACCESS_TOKEN="你的 Access Token"

# 京东
export JD_APP_KEY="你的 App Key"
export JD_APP_SECRET="你的 App Secret"
export JD_ACCESS_TOKEN="你的 Access Token"
```

### 接入 AI Agent

在 MCP 客户端中添加（Claude Desktop / Cherry Studio / Kimi Work 等）：

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "mcp-cn-oceanengine"
    }
  }
}
```

## 每个 Server 的工具

| Server | 工具 | 说明 |
|---|---|---|
| oceanengine | `get_advertiser_info` | 广告主账户信息 |
| | `get_campaign_report` | 广告计划报表（曝光/点击/转化/消耗） |
| | `get_ad_detail_report` | 广告创意级报表 |
| | `list_campaigns` | 广告计划列表 |
| | `get_account_balance` | 账户余额 |
| doudian | `get_order_list` | 订单列表 |
| | `get_order_detail` | 订单详情（含物流/售后） |
| | `get_product_list` | 商品列表（库存/价格） |
| | `get_refund_list` | 售后/退款单 |
| | `get_shop_info` | 店铺基本信息 |
| jd | `get_order_list` | 订单列表 |
| | `get_order_detail` | 订单详情 |
| | `get_product_list` | 商品列表 |
| | `get_shop_info` | 店铺信息 |

## 架构

```
mcp-cn-commerce/
├── .github/workflows/test.yml   # CI: 每次 push 自动跑 pytest
├── shared/                       # 共享基类（签名/请求/分页/错误处理）
├── servers/
│   ├── oceanengine/              # 巨量引擎 MCP（5 tools）
│   │   ├── src/mcp_oceanengine/
│   │   └── tests/
│   ├── doudian/                  # 抖店 MCP（5 tools）
│   │   ├── src/mcp_doudian/
│   │   └── tests/
│   └── jd/                       # 京东 MCP（4 tools）
│       ├── src/mcp_jd/
│       └── tests/
└── docs/
    └── platforms.md              # 8 平台 API 对比文档
```

Monorepo 结构：每个平台一个独立 MCP Server，用户只装需要的。共享认证/签名/分页逻辑。

## 安全

- **本地运行** — API 凭证不经过任何服务器，只存在你的电脑上
- **代码开源** — 任何人都可以审计
- **默认只读** — 所有工具只读数据，不执行写操作

## 常见问题

**问：为什么不做内容发布（发视频/发笔记）？**
答：内容发布已经有 HuiMei/Astron 等项目覆盖了，没必要重复。商家经营数据才是空白。

**问：需要企业资质吗？**
答：部分平台（抖店、京东）需要企业/个体户资质。拼多多个人可接入。详见 [docs/platforms.md](docs/platforms.md)。

**问：MCP 和 CLI 哪个更好？**
答：MCP 给 Agent 用（结构化 tool call），CLI 给人用（终端直接调）。Phase 2 会加 CLI 入口，共享同一套核心逻辑。

**问：会支持闲鱼/美团/饿了么吗？**
答：Phase 4。这些平台 API 在 2025 年大幅收紧（ISV 白名单制），等政策明朗后再接入。

## 许可证

MIT
