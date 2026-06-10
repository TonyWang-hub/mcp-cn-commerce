# mcp-cn-commerce — 中国电商平台 MCP Server

[![Test](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml/badge.svg)](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-MCP-blueviolet)](https://modelcontextprotocol.io/)
[![PyPI version](https://img.shields.io/pypi/v/mcp-cn-commerce)](https://pypi.org/project/mcp-cn-commerce/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> 🛒 **让 AI Agent 直接读取中国电商平台的商家经营数据。** 不做内容发布，只做**经营数据**的 MCP 连接器。
>
> 国内首个面向中国电商商家经营场景的开源 MCP Server 套件。支持 Claude、ChatGPT、Gemini 等 AI Agent 接入。
>
> **搜索关键词**: MCP Server, Model Context Protocol, 电商 MCP, AI Agent, 电商数据, 抖店 MCP, 京东 MCP, 巨量引擎 MCP, 淘宝 MCP, 拼多多 MCP, Python MCP, MCP 中国电商, 商家经营数据, 电商经营分析, AI 电商, Claude MCP

[English](README_en.md) | **简体中文**

---

## 目录

- [这是什么？](#这是什么)
- [为什么选择这个项目？](#为什么选择这个项目)
- [平台覆盖](#平台覆盖)
- [快速开始](#快速开始)
- [工具参考](#每个-server-的工具)
- [架构](#架构)
- [安全](#安全)
- [使用示例](docs/examples.md) — 使用示例和场景
- [常见问题](#常见问题)
- [参与贡献](CONTRIBUTING.md)
- [路线图](#路线图)

---

## 这是什么？

一个 **MCP (Model Context Protocol) Server 套件**（Monorepo），让 AI Agent 能够结构化地访问中国电商平台的商家经营数据。每个平台是一个独立的 MCP Server，按需安装使用：

- **巨量引擎 / 巨量千川** — 广告投放数据（广告计划、报表、账户余额）
- **抖店** — TikTok 电商店铺经营数据（订单、商品、售后、退款）
- **京东** — 京东商家后台数据（订单、商品、店铺信息）
- **淘宝 / 拼多多** — 订单、商品、物流
- **快手 / 小红书 / 微信小店** — 订单、商品、库存

所有工具**默认只读** — AI Agent 可以分析你的经营数据，但无法修改任何内容。

## 为什么选择这个项目？

国内已有的 MCP Server 全是**内容发布**（发视频、搜热搜），没有一个是**商家经营**（拉广告数据、看订单、管售后）。

| | 内容侧 MCP（HuiMei/Astron 等） | mcp-cn-commerce |
|---|---|---|
| **做什么** | 发视频、搜热点 | 拉广告报表、查订单 |
| **目标用户** | 自媒体/创作者 | **电商老板/运营/数据分析师** |
| **数据类型** | 内容数据（播放量、点赞、热搜） | **经营数据**（收入、订单、退款、ROAS） |
| **覆盖平台** | 内容平台 | 电商+广告平台 |
| **操作** | 发布/写入 | 只读分析 & 监控 |

**这是国内首个面向电商商家经营场景的开源 MCP Server 套件。**

**典型使用场景**：
- AI Agent 每日自动拉取广告 ROAS 和消耗，生成投放优化建议
- 多平台订单数据汇总，用自然语言提问即可分析
- 库存预警：AI 监控商品库存，低库存自动提醒
- 售后分析：定期拉取退款数据，发现商品质量问题趋势

## 平台覆盖

| 平台 | 类型 | Phase | 状态 | 测试 | 开放平台 |
|---|---|---|---|---|---|
| 巨量引擎 (Ocean Engine) | 广告投放 | 1 | ✅ | 24 | [open.oceanengine.com](https://open.oceanengine.com) |
| 巨量千川 (Qianchuan) | 电商广告 | 1 | ✅ | (同上) | [qianchuan.jinritemai.com](https://qianchuan.jinritemai.com) |
| 抖店 (Douyin Shop) | 电商店铺 | 1 | ✅ | 31 | [op.jinritemai.com](https://op.jinritemai.com) |
| 京东 (JD.com) | 电商店铺 | 1 | ✅ | 19 | [jos.jd.com](https://jos.jd.com) |
| 淘宝 (Taobao) | 电商店铺 | 2 | ✅ | 36 | [open.taobao.com](https://open.taobao.com) |
| 拼多多 (Pinduoduo) | 电商店铺 | 2 | ✅ | 30 | [open.pinduoduo.com](https://open.pinduoduo.com) |
| 快手 (Kuaishou) | 电商店铺 | 3 | ✅ | 33 | [open.kuaixiaodian.com](https://open.kuaixiaodian.com) |
| 小红书 (Xiaohongshu) | 电商店铺 | 3 | ✅ | 33 | [open.xiaohongshu.com](https://open.xiaohongshu.com) |
| 微信小店 (WeChat Store) | 电商店铺 | 3 | ✅ | 25 | [developers.weixin.qq.com](https://developers.weixin.qq.com) |

> Phase 4: 闲鱼、美团、饿了么（API 受限，待政策明朗）
>
> **358 个测试**，所有 8 个平台全部通过。CI 覆盖 Python 3.11/3.12/3.13。

## 快速开始

### 安装

#### 从 PyPI 安装（推荐）

```bash
# 一次安装，包含所有 8 个平台
pip install mcp-cn-commerce
```

所有平台 server 都在包内，通过 MCP 客户端配置选择使用哪些。

#### 从 GitHub Releases 下载

```bash
# 下载最新 Release 的 .whl 文件安装
# https://github.com/TonyWang-hub/mcp-cn-commerce/releases/latest

# 或直接安装：
pip install https://github.com/TonyWang-hub/mcp-cn-commerce/releases/latest/download/mcp_cn_commerce-0.1.0-py3-none-any.whl
```

#### 从 Git 安装（始终最新）

```bash
pip install git+https://github.com/TonyWang-hub/mcp-cn-commerce.git
```

#### 开发模式

```bash
git clone https://github.com/TonyWang-hub/mcp-cn-commerce.git
cd mcp-cn-commerce
pip install -e ".[dev]"
```

### 配置凭证

```bash
# 巨量引擎 / 千川
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

支持 **Claude Desktop**、**Cherry Studio**、**Kimi Work** 等所有 MCP 兼容客户端：

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

### AI Agent 使用示例

配置完成后，你可以用自然语言问 AI Agent：

> "帮我看看本周巨量引擎消耗最高的三个广告计划"
> "抖店哪些商品库存低于 10 件？"
> "京东待处理的退款单有哪些？"
> "对比巨量引擎上个月和这个月的 ROAS 趋势"
> "导出今天所有平台的订单汇总"

## 工作流模板 🆕

开箱即用的 AI 工作流模板，**无需 API 凭证即可体验**。模拟数据格式与真实 API 完全一致。

| 模板 | 用途 | 适用角色 | Demo |
|------|------|----------|------|
| [电商日报](templates/daily-report/) | 多平台 GMV/订单/退款汇总 | 运营/老板 | [查看 Demo](templates/daily-report/demo-output.md) |
| [差评预警](templates/bad-review-alert/) | 差评监控 + 原因分析 | 客服/品控 | [查看 Demo](templates/bad-review-alert/demo-output.md) |
| [客服分类](templates/cs-classify/) | 退款原因分析 + 趋势 | 客服主管 | [查看 Demo](templates/cs-classify/demo-output.md) |
| [选品分析](templates/product-select/) | 品类热度 + 竞品价格 | 选品经理 | [示例数据](templates/product-select/example-data.json) |
| [达人匹配](templates/kol-match/) | KOL 匹配 + ROI 预估 | 投放优化师 | [示例数据](templates/kol-match/example-data.json) |

### 📊 日报预览

```
┌────────┬──────────────┬──────────────┬────────┐
│ 指标   │ 今日         │ 昨日         │ 环比   │
├────────┼──────────────┼──────────────┼────────┤
│ GMV    │ ¥86,965.00   │ ¥88,900.00   │ -2.2%  │
│ 订单量 │ 312          │ 309          │ +1.0%  │
│ 客单价 │ ¥278.73      │ ¥287.70      │ -3.1%  │
│ 退款率 │ 5.1%         │ 4.6%         │ +0.5pp │
└────────┴──────────────┴──────────────┴────────┘

平台对比
┌──────────────────────┬──────────────┬──────┬────────┐
│ 平台                 │ GMV          │ 订单 │ 退款率 │
├──────────────────────┼──────────────┼──────┼────────┤
│ 抖店                 │ ¥28,950.00   │ 156  │ 5.1%   │
│ 京东                 │ ¥45,670.00   │ 89   │ 3.4%   │
│ 小红书               │ ¥12,345.00   │ 67   │ 7.5% ⚠️│
└──────────────────────┴──────────────┴──────┴────────┘

⚠️ 异常预警：
🔴 小红书退款率 7.5% — 超过 5% 阈值
🔴 库存预警：「夏季新款男士短袖T恤 白色 XL」仅剩 32 件
```

### 🚨 差评预警预览

```
原因分布
  质量问题     ████████████████████  40%
  色差         ██████████           20%
  尺码不合适   ██████████           20%
  做工粗糙     ██████████           20%

逐条分析：
1. 「洗了一次就掉色」— 抖店 ⭐
   → 建议：联系买家道歉 + 检查同批次库存

2. 「鞋码偏小，穿着挤脚」— 拼多多 ⭐⭐
   → 建议：尺码表加注「建议拍大一码」

3. 「颜色跟图片差太多」— 小红书 ⭐⭐
   → 建议：重新拍摄商品图
```

全部模板：[`templates/`](templates/) | 接入文档：[`docs/template-guide.md`](docs/template-guide.md)

## 工具汇总

| Server | 工具数 | 覆盖类别 |
|---|---|---|
| oceanengine | 22 | 广告、千川、星图、素材、人群、优化 |
| doudian | 24 | 订单、商品、售后、物流、评价、直播、流量、营销、资金、店铺 |
| jd | 19 | 订单、商品、售后、物流、评价、价格、库存、营销、店铺 |
| taobao | 17 | 订单、商品、售后、物流、评价、店铺、营销、类目 |
| pinduoduo | 17 | 订单、商品、售后、物流、评价、店铺、营销、多多客 |
| kuaishou | 16 | 订单、商品、售后、物流、评价、店铺、营销 |
| xiaohongshu | 17 | 订单、商品、售后、物流、评价、店铺、营销、库存、财务 |
| weixin_store | 15 | 订单、商品、售后、物流、店铺、营销、供货、类目 |
| **合计** | **147** | 平台工具 + 每个 server 额外 4 个通用运维工具 |

每个 server 还额外暴露 **4 个跨平台运维工具**（已计入上表）：`get_metrics`（各接口延迟/成功/错误统计）、
`get_traces`（最近请求链路）、`get_alerts`（按实时指标评估告警规则）、`export_data`（导出记录为 CSV/JSON）。
请求链路追踪与指标在每次调用时自动采集。

每个工具的具体用法见各 `servers/<平台>/server.py` 源码。

## 架构

```
mcp-cn-commerce/
├── .github/workflows/test.yml       # CI: push 自动跑 pytest
├── shared/                           # 共享基类：签名/请求/分页
│   └── cn_commerce_base.py           # 继承此基类即可新建平台
├── servers/                          # 所有平台 server（单一包，按需启动）
│   ├── oceanengine/server.py         ├── doudian/server.py
│   ├── jd/server.py                  ├── taobao/server.py
│   ├── pinduoduo/server.py           ├── kuaishou/server.py
│   ├── xiaohongshu/server.py         └── weixin_store/server.py
├── docs/platforms.md                 # 8 平台 API 对比 & 认证方式矩阵
├── README.md / README_en.md          # 简体中文 / English
└── LICENSE                           # MIT
```

单一包架构：`pip install mcp-cn-commerce` 一次安装，8 个平台 server 都在包内，通过 MCP 客户端配置选择使用哪些。

## 安全

本项目处理敏感的电商 API 凭证，安全保障：

- 🔒 **本地运行** — API 密钥和凭证存在你的电脑上，不经过任何服务器
- 📖 **代码开源** — 每一行代码都可审计
- 👁️ **默认只读** — 全部平台工具只读数据，零写入/修改/删除操作
- 📡 **无数据收集** — 不收集、不追踪、不上传任何使用数据
- 🖥️ **直连平台 API** — 代码直接调用平台 API，无中间服务器或代理
- 🔑 **环境变量配置** — 凭证通过环境变量加载，绝不硬编码

## 常见问题

**问：为什么不做内容发布（发视频/发笔记）？**
答：内容发布（抖音发视频、小红书发笔记）已经有 HuiMei/Astron 等优秀项目覆盖了，没必要重复。商家经营数据（广告报表、订单、售后）才是 MCP 生态的空白地带。

**问：需要企业资质吗？**
答：部分平台需要：抖店需要企业/个体户资质，京东需要企业资质。拼多多个人可接入。详见 [docs/platforms.md](docs/platforms.md)。

**问：MCP 和 CLI 哪个更好？**
答：MCP 给 AI Agent 用（结构化 tool call，让 AI 自动分析），CLI 给人用（终端直接调，快速查数据）。Phase 2 会加 CLI 入口，共享同一套核心逻辑。

**问：会支持闲鱼/美团/饿了么吗？**
答：在 Phase 4 计划中。这些平台的 API 在 2025 年大幅收紧（ISV 白名单制），等政策明朗后再接入。

**问：和 MCP 官方 Python SDK 的关系？**
答：基于官方 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 构建，遵循 MCP 协议标准。

**问：支持哪些 AI Client？**
答：所有支持 MCP 协议的客户端：Claude Desktop、Cherry Studio、Kimi Work、Cline、Continue 等。

## 路线图

### Phase 1 — 基础 ✅
- 巨量引擎: 广告报表/计划读取
- 巨量千川: 电商广告（共用巨量引擎认证）
- 抖店: 订单/商品/售后读取
- 京东: 订单/商品/店铺读取

### Phase 2 — 主力扩展 ✅
- 淘宝: 完整 Top API — 订单/商品/物流
- 拼多多: 订单/商品/推广工具

### Phase 3 — 长尾覆盖 ✅
- 快手: 订单/商品/物流
- 小红书: 订单/商品/库存
- 微信小店: 订单/商品/售后

### Phase 4 — 探索 ⬜
- 闲鱼、美团、饿了么（等 API 政策）

## 相关资源

- [Model Context Protocol (MCP) 官方文档](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Claude Desktop — MCP 支持](https://claude.ai/download)
- [Cherry Studio — 多模型 MCP 客户端](https://cherry-ai.com/)
- [平台 API 对比文档](docs/platforms.md)

## 引用

如果在研究或项目中使用 mcp-cn-commerce：

```bibtex
@software{mcp-cn-commerce,
  title = {mcp-cn-commerce: MCP Servers for Chinese E-Commerce Platforms},
  year = {2026},
  url = {https://github.com/TonyWang-hub/mcp-cn-commerce}
}
```

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

<!-- MCP Registry ownership marker, do not remove -->
mcp-name: io.github.tonywang-hub/mcp-cn-commerce
