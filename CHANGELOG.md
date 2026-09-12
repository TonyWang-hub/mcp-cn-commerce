# Changelog

All notable changes to mcp-cn-commerce will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — 0.1.6 engineering candidate

Status as of 2026-09-11: the repairs and documentation are merged into public `main`.
The verified source revision is [`c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e),
with the merged main snapshot at `67c8fc9c0eb0e83cd8f819a686fe8c092f0d9f7c`.
**PyPI and the public stable release remain 0.1.5.** Version 0.1.6 is an engineering
candidate for a release draft, not a completed stable PyPI/Registry publication.
See [installation choices](README.md#安装) and [release evidence](docs/release-readiness.md).

### Added

- A no-network public-package gate rejects accidental Pro/Client imports, dependencies and wheel/sdist payloads before CI installation or public upload. Core's MIT license, normalization and multi-shop report calculations remain unchanged; [Core/Pro guidance](docs/core-pro-boundary.md) explains the separate governance and persistence capabilities.
- An explicit-credential platform SDK: immutable per-authorization snapshots, an operation catalogue, isolated routing, injected/owned HTTP resource handling, and rejection of credential/protocol overrides. Hosts own token refresh, tenant authorization and output privacy.
- Youzan SDK-only order/refund/shop reads, without adding a ninth environment-backed MCP CLI.
- JD `get_aftersale_list` and `get_aftersale_refund_detail` SDK reads with strict native parameters and safe errors. These are after-sale queries, not complete refund collection or new MCP registrations.
- `build_daily_report` and deterministic aggregation with explicit timezone, source coverage, payment/refund event dates, deduplication and conflicts. Missing data cannot become complete zero values.
- Official contract/evidence records, a per-operation capability matrix, [unexecuted merchant acceptance records](docs/release-readiness.md#真店验收与支持边界), and a [public project/inquiry status page](docs/project-status.md).

### Fixed

- Single-package CLI/config priority, health checks, stdio platform startup, shared HTTP lifecycle and credential-free diagnostics. Removed test shims that hid actual MCP SDK behavior.
- Default HTTPX log redaction and safe missing-configuration/tool errors; credential/PII handling, trace retention, repeated alerts, queue cancellation, fail-fast/circuit recovery and pagination/error contracts.
- The Pydantic/core runtime lock mismatch found during real dependency installation; Excel export test dependency, typing and stale test contracts.
- Doudian HMAC-SHA256/canonical JSON, native order/after-sale contracts and parent-order identity. Buyer payment subtracts payment promotions; completed refunds use actual detail amounts and completion time, not requested amounts.
- TOP seller `session`, GMT+8 timestamp and MD5 against the official vector; required fields, native envelopes, pagination and date windows. Historical payment remains unknown where refunds change `trade.payment`.
- JD JOS method names, uppercase MD5, signed form/`360buy_param_json`, flattened native fields, shop identity and response success checks. Unknown after-sale amount units are not normalized as actual money.
- Kuaishou native GET/signing/cursor contracts; Xiaohongshu common gateway, signing, native read parameters and separate after-sale success states; WeChat seconds/cursors, shop GET and payment field paths. Unsupported page numbers or missing contract fields are not converted into successful empty data.
- Exact decimal money handling, explicit timestamp units/timezones, normalized identity, CSV field retention and formula-injection protection. Unknown money/date fields stay unknown.

### Changed

- README and API metadata now distinguish 8 MCP platform entry points / 155 registered tools from SDK support, documented official contracts and merchant live acceptance.
- PDD's identified merchant SDK reads remain unsupported pending complete official business schemas. Xiaohongshu's retained unsupported review/shop/promotion/coupon MCP entries send no request; other historical registrations do not imply a verified current contract.
- Ocean Engine's reviewed SDK scope is advertiser information and balance; report operations remain closed pending current reporting/account-scope contracts.
- SDK metadata keeps `live_verified=false`. Generic JD refunds remain unsupported; XHS Source timestamp units, JD cancellation/after-sale funds coverage, Pro Kuaishou identity and shared WeChat component delegation still have explicit gaps.
- Bilingual installation instructions separate the pinned, tested 0.1.6 source candidate from PyPI 0.1.5 and use project virtual environments. The free Pro seed-user beta commitment is preserved.

### Engineering verification

- [Candidate Core CI](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572407075) and [merged main CI](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572676414) passed on their exact revisions: **2225 tests + 20 subtests** (2245 JUnit cases), with Python matrix, formatting, typing and static checks.
- Actual wheel/sdist installation, locked/latest-supported dependencies, real MCP stdio smoke, manifest validation and hosted container jobs passed. Merchant API contract tests used controlled responses; no merchant live acceptance is claimed.
- Companion Pro and standalone partner-client engineering results are summarized separately in [release readiness](docs/release-readiness.md); they do not change the public Core license or mean every platform/data domain is supported.

### Remaining acceptance

- Authorized merchant apps, actual permissions, at least two pages, cross-day payment/partial-refund samples, back-office comparisons and real refresh/revoke/reauthorize cycles remain unverified.
- Broader product, inventory, logistics, reviews, marketing, ads and billing require operation-specific contracts and acceptance. An inquiry, simulated demo, successful installation or green CI does not establish customer integration or complete financial coverage.

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
