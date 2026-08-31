# Changelog

All notable changes to mcp-cn-commerce will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- **对 8 个平台全部 115 个 endpoint 做了逐个存在性审计**，结果只有 45 个真实存在。判据是各平台
  **官方文档清单** + **官方公告全文**，而非活体探测 —— 已下线的路由常仍返回鉴权错误而非 404
  （巨量返回 `40105`、淘宝的参数查询接口对 2018 年就下线的 API 仍返回参数、京东目录对「已下线」
  与「从未存在」返回同一个 `API不存在`）。各平台的公开文档清单接口记录在
  `kitty-specs/api-contract-conformance-*/spec.md` §2.3.1。
- **五个平台的调用契约按官方文档修正**：
  - 淘宝 —— 凭证参数名改 `session`（TOP 公共参数里没有 `access_token`）、timestamp 改
    `yyyy-MM-dd HH:mm:ss` GMT+8、网关默认改主接入文档的 `gw.api.taobao.com`、`sign_method`
    改为参与签名、两个已下线 method 改为 `.seller.get` 版本
  - 小红书 —— 改为单一网关 `ark.xiaohongshu.com/.../common_controller` + POST body +
    官方 method 名；签名只覆盖 4 个系统参数且输出小写；判错改 `error_code == 0 && success`
  - 快手 —— path 改为官方 method 点换斜杠导出（原路径中的 `api` 段官方不存在）、业务参数打包进
    单个 `param` JSON、签名末尾追加 `&signSecret=` 且输出小写、判错改 `result == 1`、
    按接口实现各自的分页范式（游标 / 混合 / 页码 / offset）
  - 拼多多 —— timestamp 改 UNIX 秒（此前发毫秒，在秒级语义下读出来是约公元 48000 年，
    每次调用必然超出 10 分钟容差被拒）
  - 微信小店 —— 5 个不存在的路径改为官方形式、4 个编造的请求体按官方字段契约修正、
    token 改用官方推荐的 `stable_token`、错误处理覆盖 HTTP 403（IP 白名单不走 errcode）
- **工具数 147 → 89**。51 个指向不存在 endpoint 的工具已取消注册（函数体与 docstring 保留，
  作为按真实接口重建时的输入）；另有 11 个工具因**平台不对三方开放**该能力而删除。
  逐工具原因见 `docs/platforms.md`。
- 巨量引擎保留注册的 2 个工具按官方契约修正：凭证走 HTTP header `Access-Token`、
  **完全不签名**、host 改 `api.oceanengine.com`、判错读 body 的 `code`/`message`。

### Added

- **契约测试层** `tests/contract/`：以各平台**官方文档**为验收基准，不需要真实凭证。
  含拼多多与京东的官方签名算例（已本地精确复现）、wire 层出网请求断言（位于既有单测的
  mock 边界**之下** —— 那个边界正是全部系统参数缺陷得以隐藏的原因）、以及跨平台不变式
  「签名集合 ≡ 发送集合 − `sign`」。
- `docs/api-contracts/<platform>.md`：每平台一份契约声明，逐项标注**官方出处 URL**，
  并区分「官方明文」与「依据充分的推断」。

### Fixed

- **测试层三类问题**：移除编码了错误契约的断言（要求巨量 query 里出现 `sign`/`app_key`、
  要求按 `error_response` 判错、要求快手签名为大写）；根治 `importlib.reload` 造成的跨文件
  干扰（全量跑 70 条失败 / 隔离跑全绿，且耗时 52s → 19s）；把形同空断言的工具数检查改为
  断言**实际注册**的工具（此前它数的是模块里的 async 函数，对取消注册完全无感）。
- 文档与对外声明改到与事实一致：README 双语工具数与测试数、FAQ 的平台状态表
  （原将跑不通的巨量/抖店/京东标为 "Phase 1 done"、而已可用的淘宝/拼多多标为 "planned"，
  标注与事实正好相反）、巨量资质要求（官方要求企业认证 + 企业打款认证，原文大幅低估）、
  `docs/platforms.md` 的签名方式表（淘宝与京东均被错记为 HMAC-MD5，官方是 MD5；
  巨量是完全不签名；微信小店无签名；快手用独立的 `signSecret`）。

### Known limitations

- **抖店（0/20）、京东（0/15）、巨量引擎（16/18 不可用）** 待按真实接口重建。已验证的替代
  映射保留在 `kitty-specs/api-contract-conformance-*/deferred/`。京东另需先决定网关方向 ——
  官方将 `routerjson` 标注为「历史接口，逐步迁移」，SP-API 为推荐方向且鉴权完全不同。
- 部分接口的**业务参数字段契约未取到**，按「不推测填充」原则保持透传或不发送，逐项记录在
  各平台契约声明的开放项一节。
- 淘宝「订单信息查询」权限包仅开放 20 种特定应用类型，**通用连接器不在其中**；
  `receiver_address` 自 2026-08-31 起全脱敏。拼多多云外解密自 2026-05-12 起限
  1 次/10 秒 + 单应用单日 100 次（只读经营分析不需要收件人明文）。

## [0.1.5] - 2026-07-13

### Fixed

- Dependabot 每周对 `/servers/oceanengine`、`/servers/doudian`、`/servers/jd` 三个目录报 update failure：
  这三个目录自 0.1.1 重构为单一包架构后已不再有独立的 `pyproject.toml`，`dependabot.yml`
  却仍在扫描它们，导致每周一持续产生失败噪音（实测 2026-06-29、2026-07-06 两次）。移除这三段配置。
- "Auto-merge Dependabot PRs" workflow 里的 `Approve PR` 步骤持续失败：GitHub 平台层面不允许
  Actions bot 自我批准 PR（`GitHub Actions is not permitted to approve pull requests`）。
  该仓库分支保护本就是 `required_approving_review_count: 0`，这一步从一开始就是多余的，直接移除。

## [0.1.4] - 2026-06-10

### Fixed

- MCP Registry 归属标记大小写修正：`mcp-name: io.github.TonyWang-hub/mcp-cn-commerce`
  （Registry 按 GitHub 用户名原始大小写做精确匹配）；server.json 命名空间同步修正。

## [0.1.3] - 2026-06-10

### Fixed

- **修复 oceanengine / doudian 两个 server 无法启动的问题**：二者使用底层
  `mcp.server.Server` 却调用只有 FastMCP 才有的 `@server.tool()`，在真实
  MCP SDK 下导入即抛 `AttributeError`（`mcp-cn-oceanengine` / `mcp-cn-doudian`
  命令此前从未真正可用）。现已迁移到 FastMCP，与其余 6 个平台一致。
- 移除测试中掩盖该问题的 `Server.tool` monkey-patch 兼容垫片；
  `tests/test_common_tools.py` 统一按 FastMCP 路径校验全部 8 个 server。

## [0.1.2] - 2026-06-10

### Fixed

- **修复 PyPI 安装不可用的问题**：`pyproject.toml` 此前未声明运行时依赖，
  干净环境 `pip install mcp-cn-commerce` 后缺少 `mcp` / `httpx` 无法启动。
  现已声明 `dependencies = ["mcp>=1.2,<2", "httpx>=0.27,<1"]`。

### Added

- `server.json` — MCP 官方 Registry 发布清单
- `docs/registry-submission.md` — 各 Registry / 市场提交操作指南

## [0.1.1] - 2026-06-10

### Added

- **淘宝 (Taobao)** MCP server — 订单、商品、售后、物流查询
- **拼多多 (Pinduoduo)** MCP server — 订单、商品、推广工具
- **快手 (Kuaishou)** MCP server — 订单、商品、物流查询
- **小红书 (Xiaohongshu)** MCP server — 订单、商品、库存管理
- **微信小店 (WeChat Store)** MCP server — 订单、商品、售后处理
- 数据标准化模块 `shared/normalizer.py` — 统一各平台数据格式
- 5 个工作流模板（日报、差评预警、客服分类、KOL 匹配、选品）
- 自动化测试套件（1091 个测试）
- 性能基准测试
- 代码质量检查（mypy、pylint、bandit）
- Dependabot 自动合并配置

### Fixed

- 修复 doudian 测试中的 MagicMock await 问题
- 修复 ruff 和 black 格式检查错误
- 移除个人信息，完成脱敏处理

### Changed

- 更新 CI/CD 配置，支持 Python 3.11/3.12/3.13
- 优化 README 结构，中文版为主入口

## [0.1.0] - 2026-06

### Added

- **巨量引擎 (Ocean Engine)** MCP server — 5 tools for ad campaign management and reporting
  - `get_advertiser_info` — advertiser account details
  - `get_campaign_report` — campaign-level performance reports
  - `get_ad_detail_report` — ad-level creative reports
  - `list_campaigns` — campaign listing
  - `get_account_balance` — account balance query
- **抖店 (Douyin Shop)** MCP server — 5 tools for e-commerce operations
  - `get_order_list` — order listing with filters
  - `get_order_detail` — order details with logistics and after-sale info
  - `get_product_list` — product listing with inventory and pricing
  - `get_refund_list` — refund/after-sale listing
  - `get_shop_info` — shop basic information
- **京东 (JD)** MCP server — 4 tools for order and product management
  - `get_order_list` — order listing
  - `get_order_detail` — order details
  - `get_product_list` — product listing
  - `get_shop_info` — shop information
- Shared base class `CommerceMCPBase` for consistent API patterns
- CI/CD with GitHub Actions (Python 3.11, 3.12, 3.13)
- 77 tests across all Phase 1 servers
- Bilingual documentation (English + 简体中文)
- Platform comparison matrix in `docs/platforms.md`

### Planned (Roadmap)

- **Phase 2**: 淘宝, 拼多多
- **Phase 3**: 快手, 小红书, 微信小店
- **Phase 4**: 闲鱼, 美团, 饿了么
