# Changelog

All notable changes to mcp-cn-commerce will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2025-06

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
