# mcp-cn-commerce — 中国电商平台 MCP Server

[![Test](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml/badge.svg)](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/Model_Context_Protocol-MCP-blueviolet)](https://modelcontextprotocol.io/)
[![PyPI version](https://img.shields.io/pypi/v/mcp-cn-commerce)](https://pypi.org/project/mcp-cn-commerce/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> 🛒 **让 AI Agent 直接读取中国电商平台的商家经营数据。** 不做内容发布，只做**经营数据**的 MCP 连接器。
>
> 面向中国电商商家经营场景的开源 MCP Server 套件。通过支持 stdio MCP 的客户端接入。
>
> **搜索关键词**: MCP Server, Model Context Protocol, 电商 MCP, AI Agent, 电商数据, 抖店 MCP, 京东 MCP, 巨量引擎 MCP, 淘宝 MCP, 拼多多 MCP, Python MCP, MCP 中国电商, 商家经营数据, 电商经营分析, AI 电商, Claude MCP

[English](README_en.md) | **简体中文**

> **2026-09-11 状态**：修复代码和文档已合入公开 `main`。Core **0.1.6 工程候选**的源码与 main CI 已通过；**PyPI / 公开稳定 Release 仍是 0.1.5**，普通 `pip install` 不会取得本轮全部修复。体验新候选请使用下方固定提交安装。真实店铺验收尚未执行。
>
> [项目与咨询进展](docs/project-status.md) · [工程/发布证据](docs/release-readiness.md) · [更新记录](CHANGELOG.md)

---

## 目录

- [这是什么？](#这是什么)
- [为什么选择这个项目？](#为什么选择这个项目)
- [平台覆盖](#平台覆盖)
- [快速开始](#快速开始)
- [工具参考](#工具汇总)
- [架构](#架构)
- [安全](#安全)
- [使用示例](docs/examples.md) — 使用示例和场景
- [常见问题](#常见问题)
- [参与贡献](CONTRIBUTING.md)
- [路线图](#路线图)

---

## 这是什么？

一个 **MCP (Model Context Protocol) Server 套件**（Monorepo），让 AI Agent 能够结构化地访问中国电商平台的商家经营数据。每个平台是一个独立的 MCP Server，按需安装使用：

- **抖店、淘宝** — 已核订单与售后只读合同，优先进行真店样本核对。
- **京东** — 已核订单、店铺和两项售后专项查询；完整退款采集仍有缺口。
- **快手、小红书、微信小店** — 已核部分订单/售后读操作；主体绑定、采集范围及真实授权分别验收。
- **巨量引擎 / 巨量千川** — 当前 SDK 已核广告主信息和账户余额；广告报表及授权账户树仍待补齐。
- **拼多多** — 已保留平台入口，经营 SDK 查询因完整官方业务 schema 未取得而关闭；其他历史 MCP 入口不属已核支持。

这是 8 个 MCP 平台入口、155 个已注册工具的目录，包含历史兼容及明确不支持的入口。**注册数量不代表已核合同或真店可用数量**；当前 SDK 范围见[逐操作能力表](docs/sdk-integration.md#catalogue-and-evidence-status)，有赞另提供 SDK-only 接入。

所有工具**默认只读** — AI Agent 可以分析你的经营数据，但无法修改任何内容。

## 为什么选择这个项目？

本项目聚焦商家已授权的经营数据，提供平台适配、只读查询和确定性日报汇总。

- 各平台独立 stdio 服务，按店铺已有授权配置。
- 共享连接池、限流、重试、指标与脱敏。
- 统一金额与时间处理；日报明确标记缺失数据和不完整分页。

平台开放 API、平台官方 MCP 与本项目的第三方 MCP 适配器是不同层次；详见[官方接入核查](docs/official-access-status.md)。

**当前可安排验证的场景**：

- 在应用确有权限时读取已核订单/售后接口，并与店铺后台样本核对。
- 对已完成分页和归一化的记录生成确定性日报，明确金额未知与覆盖限制。
- 先用模拟模板确认分析形式，再按操作合同安排真实只读验收。广告 ROAS、库存和评价等模板不证明对应数据源已经可用。

## 平台覆盖

| 平台 | 当前已核 SDK 范围 | 剩余边界（均未真店验收） | 官方入口 |
|---|---|---|---|
| 巨量引擎 / 千川 | 广告主信息、账户余额 | 广告报表迁移与授权账户树；无现成 Pro 广告 provider 承诺 | [巨量开放平台](https://open.oceanengine.com/) |
| 抖店 | 订单列表/详情、售后列表/详情 | 通用店铺信息不支持；支付优惠、实际退款和 90 天创建范围需后台核对 | [抖店开放平台](https://op.jinritemai.com/) |
| 京东 | 订单列表/详情、店铺、售后列表/退款详情 | 售后专项不是全部退款；通用退款及退款 Source 未开放 | [京东零售开放平台](https://open.jd.com/) |
| 淘宝 | 订单列表/增量/详情、退款列表/详情 | 店铺信息仅 transport-only；应用字段权限与 payment 历史口径需核对 | [淘宝开放平台](https://open.taobao.com/) |
| 拼多多 | 暂无可调用的经营 SDK 操作 | 官方完整业务 schema 待取得，经营 SDK 读操作明确不支持 | [拼多多开放平台](https://open.pinduoduo.com/) |
| 快手 | 订单/退款列表及详情、店铺 | Pro 授权 open_id 与店铺主体绑定仍缺证据 | [快手电商开放平台](https://open.kwaixiaodian.com/) |
| 小红书 | 订单/售后列表及详情 | Source 所需订单查询时间与退款完成时间单位未闭合 | [小红书开放平台](https://open.xiaohongshu.com/) |
| 微信小店 | 订单/售后列表及详情、店铺 | 实际应用权限与游标终页需 live；Pro 同组件跨 tenant 委托另有缺口 | [微信开发文档](https://developers.weixin.qq.com/doc/store/) |

本表是 SDK 摘要，不将历史 MCP 商品、库存、物流等入口全部标为当前已核合同。工具注册、合同已读、SDK 可调用、真实店铺通过分别记录；所有 SDK `live_verified` 仍为 false。当前证据见[平台说明](docs/platforms.md)、[官方接入核查](docs/official-access-status.md)与[候选验收状态](docs/release-readiness.md)。CI 配置覆盖 Python 3.11/3.12/3.13，实际结果绑定具体提交。

## 快速开始

### 安装

#### 体验已验证的 0.1.6 候选源码

使用 Python 3.11+；以下以已有 Python 3.12 为例，在项目虚拟环境安装。固定提交
[`c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e)
已经完成工程验收，不代表商家 API live 通过：

```bash
git clone https://github.com/TonyWang-hub/mcp-cn-commerce.git
cd mcp-cn-commerce
git checkout --detach c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements-lock.txt .
mcp-cn-commerce --version
```

预期版本为 `0.1.6`。开发者在上述同一项目环境将安装命令替换为：

```bash
python -m pip install -c requirements-lock.txt -e ".[dev]"
```

这会安装到 `.venv`，不默认改全局 Python。MCP 桌面客户端的 `command` 应填写该项目 `.venv/bin/` 下命令的绝对路径；只在终端激活环境不保证桌面应用能找到它。其他操作系统使用对应的虚拟环境解释器/启动脚本路径。

#### 安装当前 PyPI 稳定版 0.1.5

[PyPI 0.1.5](https://pypi.org/project/mcp-cn-commerce/0.1.5/) 是历史公开版本，**不含上面 0.1.6 候选的全部协议与稳定性修复**。需要该版本时，在单独的项目虚拟环境中安装：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install "mcp-cn-commerce==0.1.5"
```

#### GitHub Releases 与 main

[公开稳定 Release v0.1.5](https://github.com/TonyWang-hub/mcp-cn-commerce/releases/tag/v0.1.5) 与 `releases/latest` 仍指向历史稳定版本。0.1.6 当前按工程候选准备发布草稿，尚未正式发布到 PyPI / MCP Registry；草稿不是公开可下载安装的稳定版。后续发布状态以[项目进展](docs/project-status.md)及实际 Release 为准。

`main` 已包含候选修复和后续文档，但会继续变化。复现实测版本使用上面的完整 SHA；不要把未固定的 Git 安装、最新 main 或旧 PyPI 包称为同一个候选构建。

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

本项目是标准 stdio MCP server，所有支持 MCP 协议的客户端都能直接接入。下面给出主流客户端的配置方式（凭证可在 shell 里 `export`，也可写进客户端配置的 `env` 段，两种都行）。

#### Claude Desktop / Cherry Studio / Cline / Continue / Kimi Work（`mcpServers` JSON）

这类客户端用同一套 `mcpServers` 配置格式（Cline 写在 `cline_mcp_settings.json`，Claude Desktop 写在 `claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "mcp-cn-oceanengine",
      "env": {
        "OCEANENGINE_APP_KEY": "你的 App Key",
        "OCEANENGINE_APP_SECRET": "你的 App Secret",
        "OCEANENGINE_ACCESS_TOKEN": "你的 Access Token"
      }
    },
    "doudian": { "command": "mcp-cn-doudian" },
    "jd": { "command": "mcp-cn-jd" }
  }
}
```

#### Claude Code（CLI）

```bash
claude mcp add oceanengine \
  --env OCEANENGINE_APP_KEY=你的Key \
  --env OCEANENGINE_APP_SECRET=你的Secret \
  --env OCEANENGINE_ACCESS_TOKEN=你的Token \
  -- mcp-cn-oceanengine
```

#### Codex（CLI）

```bash
codex mcp add oceanengine -- mcp-cn-oceanengine
```

或写进 `~/.codex/config.toml`：

```toml
[mcp_servers.oceanengine]
command = "mcp-cn-oceanengine"
env = { OCEANENGINE_APP_KEY = "你的Key", OCEANENGINE_APP_SECRET = "你的Secret", OCEANENGINE_ACCESS_TOKEN = "你的Token" }
```

#### OpenCode / MiMo Code（`mcp` 段）

这两者（MiMo Code 是 OpenCode 的 fork）用 `mcp` 配置格式：

```json
{
  "mcp": {
    "oceanengine": {
      "type": "local",
      "command": ["mcp-cn-oceanengine"],
      "enabled": true,
      "environment": {
        "OCEANENGINE_APP_KEY": "你的Key",
        "OCEANENGINE_APP_SECRET": "你的Secret",
        "OCEANENGINE_ACCESS_TOKEN": "你的Token"
      }
    }
  }
}
```

> MiMo Code 还能直接从 Claude Code 自动导入已配置的 MCP server，无需重复配置。

> 其余平台 server 命令同理：`mcp-cn-doudian`、`mcp-cn-jd`、`mcp-cn-taobao`、`mcp-cn-pinduoduo`、`mcp-cn-kuaishou`、`mcp-cn-xiaohongshu`、`mcp-cn-weixin-store`。按需添加，凭证见上方[配置凭证](#配置凭证)。

### AI Agent 使用示例

确认对应工具合同、平台授权和数据范围后，可以安排以下只读查询；首次真店验收仍需与后台核对：

> “读取抖店这个固定更新时间窗口的订单，告诉我还需要哪些分页和详情”
> “查看淘宝这笔退款的状态、金额和完结时间”
> “查询获准广告主的账户余额”
> “导出我提供的已归一化订单记录，并注明缺失字段”

## 工作流模板 🆕

开箱即用的 AI 工作流模板，**无需 API 凭证即可体验**。以下预览均使用模拟数据，不证明真实平台数据源已接通。示例数据遵循日报输入契约；原始平台返回需先完成分页、字段归一化和完整性声明。

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

此表统计注册入口及其目录类别，包含兼容和未核合同；可调用 SDK 范围另见[能力表](docs/sdk-integration.md#catalogue-and-evidence-status)。

| Server | 工具数 | 覆盖类别 |
|---|---|---|
| oceanengine | 23 | 广告、千川、星图、素材、人群、优化 |
| doudian | 25 | 订单、商品、售后、物流、评价、直播、流量、营销、资金、店铺 |
| jd | 20 | 订单、商品、售后、物流、评价、价格、库存、营销、店铺 |
| taobao | 18 | 订单、商品、售后、物流、评价、店铺、营销、类目 |
| pinduoduo | 18 | 订单、商品、售后、物流、评价、店铺、营销、多多客 |
| kuaishou | 17 | 订单、商品、售后、物流、评价、店铺、营销 |
| xiaohongshu | 18 | 订单、商品、售后、物流、评价、店铺、营销、库存、财务 |
| weixin_store | 16 | 订单、商品、售后、物流、店铺、营销、供货、类目 |
| **合计** | **155** | 平台工具 + 每个 server 5 个公共工具（运维、导出、日报） |

每个 server 还额外暴露 **5 个跨平台公共工具**（已计入上表）：`get_metrics`（各接口延迟/成功/错误统计）、
`get_traces`（最近请求链路）、`get_alerts`（按实时指标评估告警规则）、`export_data`（导出记录为 CSV/JSON）、`build_daily_report`（按时区和数据完整性生成日报）。
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

单一包架构：所选 Core 版本包含 8 个平台 server。先按上方说明选择候选或稳定版本，再按实际已核能力配置 MCP 客户端。

## 安全

本项目处理敏感的电商 API 凭证，安全保障：

- 🔒 **本地运行** — 凭证由本地读取，必要的认证信息发送给对应平台 API
- 📖 **代码开源** — 每一行代码都可审计
- 👁️ **默认只读** — 全部平台工具只读数据，零写入/修改/删除操作
- 📡 **无数据收集** — 本项目不向自建服务上报使用数据；业务查询结果会返回你配置的 MCP/AI 客户端
- 🖥️ **直连平台 API** — 代码直接调用平台 API，无中间服务器或代理
- 🔑 **环境变量配置** — 凭证通过环境变量加载，绝不硬编码

## 常见问题

**问：为什么不做内容发布（发视频/发笔记）？**
答：内容发布（抖音发视频、小红书发笔记）已经有 HuiMei/Astron 等优秀项目覆盖了，没必要重复。商家经营数据（广告报表、订单、售后）才是 MCP 生态的空白地带。

**问：需要企业资质吗？**
答：部分平台需要：抖店需要企业/个体户资质，京东需要企业资质。拼多多个人可接入。详见 [docs/platforms.md](docs/platforms.md)。

**问：MCP 和 CLI 哪个更好？**
答：MCP 给 AI Agent 用（结构化 tool call，让 AI 自动分析），CLI 给人用（终端直接调，快速查数据）。CLI 提供启动和健康诊断；每个 stdio 连接启动一个平台，经营查询通过 MCP 工具完成。

**问：会支持闲鱼/美团/饿了么吗？**
答：在 Phase 4 计划中。这些平台的 API 在 2025 年大幅收紧（ISV 白名单制），等政策明朗后再接入。

**问：和 MCP 官方 Python SDK 的关系？**
答：基于官方 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 构建，遵循 MCP 协议标准。

**问：支持哪些 AI Client？**
答：所有支持 MCP 协议的客户端：Claude Desktop、Cherry Studio、Kimi Work、Cline、Continue 等。

## 💼 Pro 版（内测招募中）

开源版永久免费，MIT 许可和已经公开的能力保持不变：平台适配、显式凭证 SDK、金额/时间归一化，以及 `build_daily_report` 的多店确定性日报计算都属于 Core。多店算法无需 Pro；宿主需提供已采集记录和准确的完整性声明。**代运营公司 / 电商 SaaS / 多店铺商家**可参加 Pro 内测，验证授权治理和持续运行能力；平台范围按当前合同逐操作确认。

| 能力 | 开源版 | Pro 版 |
|---|---|---|
| 平台入口 | 8 个 MCP 平台、155 个注册工具；范围见能力表 | 复用 Core SDK；不等于开放全部历史 MCP 工具 |
| Access Token 管理 | 通常由调用方管理；微信有显式本店 managed 模式 | 已实现相应 provider 的授权与刷新，按平台/应用模式确认；均待真实生命周期验收 |
| OAuth 授权 | 调用方取得获准应用与店铺凭证 | 已登记且获平台允许的 loopback 可用 `auth`；HTTPS 回调需合作方 begin/complete 接入 |
| 店铺数量 | MCP 一进程一套凭证；SDK 由宿主管理多个快照 | 私有配置与加密数据库管理应用、grant、店铺 ACL；同/跨平台聚合按采集能力确认 |
| 归一化与多店日报计算 | 已公开；可传入多店数据生成确定性日报、去重并标记未知金额/覆盖限制 | 复用公开计算能力，增加持久数据仓库和报告历史 |
| 持续采集与治理 | 宿主组织分页、授权生命周期、存储和访问控制 | 租户/店铺权限、持久分页证明、断点恢复、调度、审计；按已实现 Source 验证 |
| 数据流向 | 本地运行，向获准平台发起查询并向 MCP 客户端返回数据 | 由部署方管理；远程合作方 API、平台请求及显式配置通知按实际部署发生，license 离线校验 |
| 支持 | GitHub Issues | 内测场景反馈与交付方支持 |

> 🎯 **正在招募首批种子用户**：免费使用 Pro 内测版，换取你的真实场景反馈。
> 特别欢迎管理多个店铺的代运营 TP / ISV。
> 👉 [提交 Pro 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/new?labels=pro-inquiry&title=%5BPro%5D%20%E5%92%A8%E8%AF%A2&body=%E8%AF%B7%E7%AE%80%E5%8D%95%E4%BB%8B%E7%BB%8D%EF%BC%9A%0A-%20%E4%BD%A0%E7%9A%84%E8%A7%92%E8%89%B2%EF%BC%88%E5%95%86%E5%AE%B6%2F%E4%BB%A3%E8%BF%90%E8%90%A5%2FISV%2F%E5%BC%80%E5%8F%91%E8%80%85%EF%BC%89%EF%BC%9A%0A-%20%E7%AE%A1%E7%90%86%E7%9A%84%E5%BA%97%E9%93%BA%E6%95%B0%E9%87%8F%E5%92%8C%E5%B9%B3%E5%8F%B0%EF%BC%9A%0A-%20%E6%9C%80%E6%83%B3%E8%A7%A3%E5%86%B3%E7%9A%84%E9%97%AE%E9%A2%98%EF%BC%9A)

Pro 版闭源、私有交付。具体 provider、授权模式和采集范围以配套 Pro 文档与 capabilities 为准；当前不承诺巨量/千川自动续期或广告报表。旧 `shops.yaml` 不会自动导入当前配置。免费内测的许可安排由交付方确认，本地试用计时不替代上述免费内测承诺。

Core 安装不需要 Pro 或独立商业 Client。CI 在依赖安装前检查源码，在制品安装/公开上传前检查 wheel 和 sdist，防止意外混入私有代码或依赖。详见 [Core / Pro 边界与检查](docs/core-pro-boundary.md)。Pro 的源码改作、OEM/再分发、正式交付范围和支持安排另行书面确认，不因安装包存在自动授予。

## 路线图

### 已完成的工程阶段

- 8 个平台 MCP 入口、共享工具和显式凭证 SDK；工具目录包含历史兼容项。
- 抖店、TOP、京东、快手、小红书、微信等已核读合同迁移；具体操作见当前能力表。
- 按准确提交完成工程回归、安装和真实 MCP 传输检查，见[验收状态](docs/release-readiness.md)。

### 当前稳定与验收

- 优先抖店/TOP 1–2 平台获准店铺的只读样本、分页、金额日期及授权生命周期核对。
- 补 PDD 业务 schema、XHS Source 时间合同、JD 两类退款资金覆盖，以及 Pro 已知主体/委托缺口。
- 商品、库存、物流、评价、营销、广告和账单等广泛数据域按合同逐项推进，不以历史 Phase 完成标记承诺全部当前可用。

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
mcp-name: io.github.TonyWang-hub/mcp-cn-commerce
