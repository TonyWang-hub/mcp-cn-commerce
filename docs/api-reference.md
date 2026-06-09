# API Reference

mcp-cn-commerce provides MCP (Model Context Protocol) servers for 8 Chinese e-commerce platforms. All servers expose read-only tools over stdio transport.

## Table of Contents

- [Common Concepts](#common-concepts)
- [1. Ocean Engine (巨量引擎)](#1-ocean-engine-巨量引擎)
- [2. Doudian (抖店)](#2-doudian-抖店)
- [3. JD (京东)](#3-jd-京东)
- [4. Taobao (淘宝)](#4-taobao-淘宝)
- [5. Pinduoduo (拼多多)](#5-pinduoduo-拼多多)
- [6. Kuaishou (快手)](#6-kuaishou-快手)
- [7. Xiaohongshu (小红书)](#7-xiaohongshu-小红书)
- [8. WeChat Store (微信小店)](#8-wechat-store-微信小店)
- [Error Handling](#error-handling)

---

## Common Concepts

### Authentication

Each platform uses environment variables for authentication. All servers require at minimum an app key (or client ID), app secret, and access token.

### Signing Methods

| Method | Platforms |
|--------|-----------|
| MD5 | Ocean Engine, Taobao, Pinduoduo, Xiaohongshu |
| HMAC-MD5 | JD |
| MD5 (sign_secret) | Kuaishou |
| MD5 (custom) | Doudian |
| OAuth 2.0 (no signing) | WeChat Store |

### Response Format

All tools return JSON strings (via `json.dumps` with `ensure_ascii=False, indent=2`) or platform-specific dict objects. Successful responses contain the platform's data payload. Errors are returned as:

```json
{
  "error": {
    "code": 10001,
    "message": "Error description"
  }
}
```

### Pagination

Most list tools support pagination with these common parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 1 (or 0 for Doudian) | Page number |
| `page_size` | int | 10-20 | Items per page (max 100-200 depending on platform) |

---

## 1. Ocean Engine (巨量引擎)

**Server name:** `mcp-cn-oceanengine`
**Base URL:** `https://ad.oceanengine.com/open_api/`
**Sign method:** MD5

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OCEANENGINE_APP_KEY` | Yes | App Key from Ocean Engine Open Platform |
| `OCEANENGINE_APP_SECRET` | Yes | App Secret |
| `OCEANENGINE_ACCESS_TOKEN` | Yes | OAuth access token |

### Tools

#### `get_advertiser_info`

Get basic advertiser account information including name, balance, and status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `advertiser_ids` | str | Yes | Comma-separated advertiser IDs (e.g. `"123456,789012"`) |

#### `get_account_balance`

Get the account balance for an advertiser.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `advertiser_id` | str | Yes | The advertiser account ID |

#### `get_campaign_report`

Get campaign-level advertising report with impressions, clicks, cost, conversions, CTR, CPC, etc.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `start_date` | str | Yes | - | Start date in `YYYY-MM-DD` format |
| `end_date` | str | Yes | - | End date in `YYYY-MM-DD` format |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `get_ad_detail_report`

Get ad-level detail report with per-ad performance metrics.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `start_date` | str | Yes | - | Start date in `YYYY-MM-DD` format |
| `end_date` | str | Yes | - | End date in `YYYY-MM-DD` format |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `list_campaigns`

List campaigns under an advertiser account with optional status filtering.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |
| `filtering` | str | No | `""` | JSON string for filtering (e.g. `'{"status": "CAMPAIGN_STATUS_ENABLE"}'`) |

#### `get_campaign_detail`

Get detailed information about a specific advertising campaign (budget, targeting, status, creative settings).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `advertiser_id` | str | Yes | The advertiser account ID |
| `campaign_id` | str | Yes | The campaign ID to query |

#### `list_ads`

List ad creatives under an advertiser account, optionally filtered by campaign.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `campaign_id` | str | No | `""` | Filter ads by campaign ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `get_ad_detail`

Get detailed information about a specific ad creative (content, delivery status, performance settings).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `advertiser_id` | str | Yes | The advertiser account ID |
| `ad_id` | str | Yes | The ad creative ID to query |

#### `get_qianchuan_report`

Qianchuan (千川) ecommerce ad report with impressions, clicks, cost, conversions, GMV, ROI, etc.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `start_date` | str | Yes | - | Start date in `YYYY-MM-DD` format |
| `end_date` | str | Yes | - | End date in `YYYY-MM-DD` format |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `get_qianchuan_campaign_list`

List Qianchuan (千川) ecommerce ad campaigns.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `get_star_report`

Star (星图) influencer marketing report with reach, engagement, conversions, cost per engagement, and ROI.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `start_date` | str | Yes | - | Start date in `YYYY-MM-DD` format |
| `end_date` | str | Yes | - | End date in `YYYY-MM-DD` format |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `list_star_tasks`

List Star (星图) influencer marketing tasks, optionally filtered by status.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `status` | str | No | `""` | Status filter: `IN_PROGRESS`, `COMPLETED`, `CANCELLED` |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `get_creative_report`

Creative/materials level performance report.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `start_date` | str | Yes | - | Start date in `YYYY-MM-DD` format |
| `end_date` | str | Yes | - | End date in `YYYY-MM-DD` format |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `list_materials`

List materials in the creative library, optionally filtered by type.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |
| `material_type` | str | No | `""` | Type filter: `IMAGE`, `VIDEO`, `TITLE` |

#### `list_audience_packages`

List DMP audience packages (audience size, type, status).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `get_audience_report`

Audience analysis report with demographic breakdown, interest tags, device and geographic distribution.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `advertiser_id` | str | Yes | - | The advertiser account ID |
| `start_date` | str | Yes | - | Start date in `YYYY-MM-DD` format |
| `end_date` | str | Yes | - | End date in `YYYY-MM-DD` format |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Records per page (max 100) |

#### `get_bid_suggestion`

Get bid optimization suggestions for a campaign (recommended bid range based on historical performance).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `advertiser_id` | str | Yes | The advertiser account ID |
| `campaign_id` | str | Yes | The campaign ID |

#### `get_diagnosis`

Get diagnostic analysis for a campaign (delivery issues, budget constraints, audience saturation, optimization recommendations).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `advertiser_id` | str | Yes | The advertiser account ID |
| `campaign_id` | str | Yes | The campaign ID |

---

## 2. Doudian (抖店)

**Server name:** `mcp-cn-doudian`
**Base URL:** `https://openapi-fxg.jinritemai.com/`
**Sign method:** MD5 (custom: `MD5(app_key + sorted_json_params + app_secret)`)

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DOUDIAN_APP_KEY` | Yes | App Key from Douyin Open Platform |
| `DOUDIAN_APP_SECRET` | Yes | App Secret |
| `DOUDIAN_SHOP_ID` | Yes | Shop ID |
| `DOUDIAN_ACCESS_TOKEN` | Yes | OAuth access token |

### Tools

#### `get_order_list`

Get order list. Returns `dict` with keys: `total`, `page`, `page_size`, `orders`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | No | `""` | Start time, e.g. `"2024-01-01 00:00:00"` |
| `end_time` | str | No | `""` | End time |
| `order_status` | str | No | `""` | Status: `1`(待确认), `2`(备货中), `3`(已发货), `4`(已收货), `5`(已完成), `101`(已取消) |
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 10 | Items per page (max 100) |

#### `get_order_detail`

Get single order detail with logistics, refund status, products, and buyer info. Returns `dict` with key: `order`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | No* | Order ID |
| `shop_order_id` | str | No* | Shop order ID |

*At least one of `order_id` or `shop_order_id` is required.

#### `get_product_list`

Get product list. Returns `dict` with keys: `total`, `page`, `page_size`, `products`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 10 | Items per page (max 100) |
| `status` | str | No | `""` | Status: `on_sale`, `off_sale`, or empty for all |

#### `get_refund_list`

Get after-sale/refund list. Returns `dict` with keys: `total`, `page`, `page_size`, `refunds`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | No | `""` | Start time |
| `end_time` | str | No | `""` | End time |
| `refund_type` | str | No | `""` | Type: `0`(仅退款), `1`(退货退款), `2`(换货), `3`(维修) |
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 10 | Items per page (max 100) |

#### `get_shop_info`

Get shop basic info (name, logo, rating, status, certification). Returns `dict` with key: `shop`.

No parameters.

#### `get_logistics_tracking`

Get logistics tracking for an order. Returns `dict` with key: `tracking`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | Yes | Order ID |

#### `list_logistics_companies`

Get list of supported logistics companies. Returns `dict` with keys: `total`, `companies`.

No parameters.

#### `get_review_list`

Get product review list. Returns `dict` with keys: `total`, `page`, `page_size`, `reviews`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | No | `""` | Start time |
| `end_time` | str | No | `""` | End time |
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 10 | Items per page (max 100) |

#### `get_review_detail`

Get single review detail. Returns `dict` with key: `review`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `review_id` | str | Yes | Review/comment ID |

#### `get_feige_messages`

Get Feige (飞鸽) customer service chat messages. Returns `dict` with keys: `total`, `page`, `page_size`, `messages`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `user_id` | str | Yes | - | User ID |
| `start_time` | str | No | `""` | Start time |
| `end_time` | str | No | `""` | End time |
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_live_data`

Get live streaming room data (viewers, interactions, conversions). Returns `dict` with key: `live_data`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `room_id` | str | Yes | Live room ID |
| `start_time` | str | No | Start time |
| `end_time` | str | No | End time |

#### `list_live_rooms`

Get live streaming session list. Returns `dict` with keys: `total`, `page`, `page_size`, `rooms`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | No | `""` | Start time |
| `end_time` | str | No | `""` | End time |
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 10 | Items per page (max 100) |

#### `get_traffic_data`

Get traffic source analysis data. Returns `dict` with key: `traffic`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_date` | str | No | `""` | Start date, e.g. `"2024-01-01"` |
| `end_date` | str | No | `""` | End date |

#### `get_short_video_data`

Get short video traffic and conversion data. Returns `dict` with key: `video_data`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `video_id` | str | Yes | Short video ID |
| `start_date` | str | No | Start date |
| `end_date` | str | No | End date |

#### `list_promotions`

Get promotion activity list. Returns `dict` with keys: `total`, `page`, `page_size`, `promotions`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | str | No | `""` | Status: `1`(进行中), `2`(未开始), `3`(已结束), `4`(已终止) |
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 10 | Items per page (max 100) |

#### `list_coupons`

Get coupon list. Returns `dict` with keys: `total`, `page`, `page_size`, `coupons`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | str | No | `""` | Status: `1`(生效中), `2`(已失效), `3`(已过期) |
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 10 | Items per page (max 100) |

#### `get_bill_list`

Get fund transaction list. Returns `dict` with keys: `total`, `page`, `page_size`, `bills`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_date` | str | No | `""` | Start date |
| `end_date` | str | No | `""` | End date |
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 10 | Items per page (max 100) |

#### `get_shop_score`

Get shop DSR scores (product, service, logistics). Returns `dict` with key: `shop_score`.

No parameters.

#### `list_categories`

Get product category tree. Returns `dict` with keys: `total`, `parent_id`, `categories`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `parent_id` | str | No | `"0"` | Parent category ID (`"0"` = root) |

#### `list_brands`

Get brand list. Returns `dict` with keys: `total`, `page`, `page_size`, `brands`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `category_id` | str | No | `""` | Filter by category |
| `page` | int | No | 0 | Page number (starts from 0) |
| `page_size` | int | No | 10 | Items per page (max 100) |

---

## 3. JD (京东)

**Server name:** `mcp-cn-jd`
**Base URL:** `https://api.jd.com/routerjson`
**Sign method:** HMAC-MD5

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `JD_APP_KEY` | Yes | App Key from JD Open Platform |
| `JD_APP_SECRET` | Yes | App Secret |
| `JD_ACCESS_TOKEN` | Yes | OAuth access token |

### Tools

#### `get_order_list`

Query order list by time range and optional status.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | e.g. `"2024-01-01 00:00:00"` |
| `end_time` | str | Yes | - | e.g. `"2024-01-31 23:59:59"` |
| `order_status` | str | No | `""` | `WAIT_SELLER_STOCK_OUT`, `WAIT_GOODS_RECEIVE_CONFIRM`, `FINISHED_L`, `TRADE_CANCELED` |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_order_detail`

Get full details of a single order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | Yes | JD order ID |

#### `get_product_list`

Get product (ware) list with stock and price info.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |
| `ware_status` | str | No | `""` | `"0"`(draft), `"1"(never-on-sale)`, `"2"(on-sale)`, `"3"(off-shelf)` |

#### `get_shop_info`

Get shop basic information.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `shop_id` | str | No | `""` | JD shop ID. Empty = authenticated shop |

#### `get_after_sale_list`

Query after-sale (return/refund/exchange) list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | e.g. `"2024-01-01 00:00:00"` |
| `end_time` | str | Yes | - | e.g. `"2024-01-31 23:59:59"` |
| `status` | str | No | `""` | `WAIT_SELLER_AGREE`, `WAIT_BUYER_RETURN_GOODS`, `WAIT_SELLER_RECEIVE_GOODS`, `COMPLETE`, `CLOSED` |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_after_sale_detail`

Get full details of a single after-sale record.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `after_sale_id` | str | Yes | After-sale record ID |

#### `get_logistics_tracking`

Get logistics tracking for an order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | Yes | JD order ID |

#### `get_review_list`

Query product review (comment) list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `product_id` | str | Yes | - | Product/ware ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_review_detail`

Get full details of a single review.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `review_id` | str | Yes | Review/comment ID |

#### `get_price_info`

Get real-time price information for SKUs, including promotion overlay.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sku_ids` | str | Yes | Comma-separated SKU IDs (max 100) |

#### `get_inventory`

Query current inventory/stock levels for given ware IDs.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `ware_ids` | str | Yes | Comma-separated ware IDs (max 100) |

#### `list_promotions`

List promotion activities.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | str | No | `""` | `"1"(ongoing)`, `"2"(ended)`, `"3"(not started)` |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `list_coupons`

List coupon templates.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | str | No | `""` | `"1"(active)`, `"2"(expired)`, `"3"(not started)` |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `list_categories`

List product categories under a given parent.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `parent_id` | str | No | `"0"` | Parent category ID (`"0"` = top-level) |

#### `get_shop_score`

Get shop DSR scores (product description, service attitude, delivery speed).

No parameters.

---

## 4. Taobao (淘宝)

**Server name:** `mcp-cn-taobao`
**Base URL:** `https://eco.taobao.com/router/rest`
**Sign method:** MD5

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TAOBAO_APP_KEY` | Yes | App Key from Taobao Open Platform (TOP) |
| `TAOBAO_APP_SECRET` | Yes | App Secret |
| `TAOBAO_ACCESS_TOKEN` | Yes | OAuth access token |

### Tools

#### `get_order_list`

Query order list by time range and optional status.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | e.g. `"2024-01-01 00:00:00"` |
| `end_time` | str | Yes | - | e.g. `"2024-01-31 23:59:59"` |
| `status` | str | No | `""` | `WAIT_BUYER_PAY`, `WAIT_SELLER_SEND_GOODS`, `WAIT_BUYER_CONFIRM_GOODS`, `TRADE_FINISHED`, `TRADE_CLOSED` |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_order_detail`

Get full details of a single order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tid` | str | Yes | Taobao trade ID |

#### `get_increment_orders`

Query incrementally modified orders (for syncing status changes).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | Modification start time |
| `end_time` | str | Yes | - | Modification end time |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_product_list`

Get on-sale product list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 200) |
| `status` | str | No | `""` | `"onsale"`, `"instock"`, or empty for all |

#### `get_product_detail`

Get full details of a single product.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `num_iid` | str | Yes | Taobao item ID |

#### `get_refund_list`

Query refund/return list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | Query start time |
| `end_time` | str | Yes | - | Query end time |
| `status` | str | No | `""` | `WAIT_SELLER_AGREE`, `WAIT_BUYER_RETURN_GOODS`, `WAIT_SELLER_CONFIRM_GOODS`, `SUCCESS`, `CLOSED` |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_refund_detail`

Get full details of a single refund record.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `refund_id` | str | Yes | Refund record ID |

#### `get_logistics_tracking`

Get logistics tracking for an order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tid` | str | Yes | Taobao trade ID |

#### `get_review_list`

Query product review (rate/comment) list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `num_iid` | str | Yes | - | Taobao item ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 200) |

#### `get_shop_info`

Get shop basic information.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `nick` | str | No | `""` | Seller nick. Empty = authenticated shop |

#### `get_seller_info`

Get authenticated seller information (credit, profile).

No parameters.

#### `list_promotions`

List promotion activities.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | str | No | `""` | `"1"(ongoing)`, `"2"(ended)`, `"3"(not started)` |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `list_categories`

List product categories under a given parent.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `parent_cid` | str | No | `"0"` | Parent category ID (`"0"` = top-level) |

---

## 5. Pinduoduo (拼多多)

**Server name:** `mcp-cn-pinduoduo`
**Base URL:** `https://gw-api.pinduoduo.com/api/router`
**Sign method:** MD5

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PINDUODUO_CLIENT_ID` | Yes | Client ID from PDD Open Platform |
| `PINDUODUO_CLIENT_SECRET` | Yes | Client Secret |
| `PINDUODUO_ACCESS_TOKEN` | Yes | OAuth access token |

### Tools

#### `get_order_list`

Query order list by time range and optional status.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | e.g. `"2024-01-01 00:00:00"` |
| `end_time` | str | Yes | - | e.g. `"2024-01-31 23:59:59"` |
| `order_status` | str | No | `""` | `1`(待发货), `2`(已发货), `3`(已签收), `4`(退款中), `5`(已退款) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_order_detail`

Get full details of a single order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_sn` | str | Yes | PDD order serial number |

#### `get_product_list`

Get product (goods) list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_product_detail`

Get full details of a single product.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `goods_id` | str | Yes | PDD goods ID |

#### `search_products`

Search products by keyword.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `keyword` | str | Yes | - | Search keyword |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_refund_list`

Query refund (after-sale) list by time range.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | Start time |
| `end_time` | str | Yes | - | End time |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_refund_detail`

Get full details of a single refund record.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `refund_id` | str | Yes | Refund record ID |

#### `get_logistics_tracking`

Get logistics tracking for an order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_sn` | str | Yes | PDD order serial number |

#### `list_logistics_companies`

List all available logistics companies on PDD.

No parameters.

#### `get_review_list`

Query product review list by goods ID.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `goods_id` | str | Yes | - | PDD goods ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_shop_info`

Get mall/shop basic information for the authenticated merchant.

No parameters.

#### `list_promotions`

List promotion activities.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `search_affiliate_goods`

Search affiliate (多多客) goods by keyword.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `keyword` | str | Yes | - | Search keyword |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

---

## 6. Kuaishou (快手)

**Server name:** `mcp-cn-kuaishou`
**Base URL:** `https://openapi.kwaixiaodian.com`
**Sign method:** MD5 (uses `sign_secret` instead of `app_secret` for signing)

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KUAISHOU_APP_KEY` | Yes | App Key from Kuaishou Open Platform |
| `KUAISHOU_APP_SECRET` | Yes | App Secret |
| `KUAISHOU_SIGN_SECRET` | Yes | Sign Secret (used for request signing) |
| `KUAISHOU_ACCESS_TOKEN` | Yes | OAuth access token |

### Tools

#### `get_order_list`

Query order list by time range and optional status.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | e.g. `"2024-01-01 00:00:00"` |
| `end_time` | str | Yes | - | e.g. `"2024-01-31 23:59:59"` |
| `order_status` | str | No | `""` | `1`(待发货), `2`(已发货), `3`(已签收), `4`(退款中), `5`(已退款) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_order_detail`

Get full details of a single order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | Yes | Kuaishou order ID |

#### `get_product_list`

Get product (item) list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_product_detail`

Get full details of a single product.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `item_id` | str | Yes | Kuaishou item ID |

#### `get_refund_list`

Query refund (after-sale) list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | Start time |
| `end_time` | str | Yes | - | End time |
| `refund_status` | str | No | `""` | `1`(退款中), `2`(退款成功), `3`(退款失败) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_refund_detail`

Get full details of a single refund record.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `refund_id` | str | Yes | Refund record ID |

#### `get_logistics_tracking`

Get logistics tracking for an order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | Yes | Kuaishou order ID |

#### `list_logistics_companies`

List all available logistics companies.

No parameters.

#### `get_review_list`

Query product review list by item ID.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `item_id` | str | Yes | - | Kuaishou item ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_shop_info`

Get shop basic information for the authenticated merchant.

No parameters.

#### `list_promotions`

List promotion activities.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `list_coupons`

List coupon activities.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |
| `status` | str | No | `""` | `1`(未生效), `2`(生效中), `3`(已过期), `4`(已停止) |

---

## 7. Xiaohongshu (小红书)

**Server name:** `mcp-cn-xiaohongshu`
**Base URL:** `https://open.xiaohongshu.com`
**Sign method:** MD5

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `XHS_CLIENT_ID` | Yes | Client ID from XHS Open Platform |
| `XHS_CLIENT_SECRET` | Yes | Client Secret |
| `XHS_ACCESS_TOKEN` | Yes | OAuth access token |

### Tools

#### `get_order_list`

Query order list by time range and optional status.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | e.g. `"2024-01-01 00:00:00"` |
| `end_time` | str | Yes | - | e.g. `"2024-01-31 23:59:59"` |
| `order_status` | str | No | `""` | `1`(待发货), `2`(已发货), `3`(已签收), `4`(退款中), `5`(已退款) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_order_detail`

Get full details of a single order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | Yes | XHS order ID |

#### `get_product_list`

Get product (goods) list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_product_detail`

Get full details of a single product.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `product_id` | str | Yes | XHS product ID |

#### `get_refund_list`

Query refund (after-sale) list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | Start time |
| `end_time` | str | Yes | - | End time |
| `refund_status` | str | No | `""` | `1`(待处理), `2`(处理中), `3`(已退款), `4`(已拒绝) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_refund_detail`

Get full details of a single refund record.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `refund_id` | str | Yes | Refund record ID |

#### `get_logistics_tracking`

Get logistics tracking for an order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | Yes | XHS order ID |

#### `get_review_list`

Query product review list by product ID.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `product_id` | str | Yes | - | XHS product ID |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_shop_info`

Get shop basic information.

No parameters.

#### `list_promotions`

List promotion activities.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `list_coupons`

List coupon templates.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | str | No | `""` | `1`(进行中), `2`(已结束), `3`(未开始) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_inventory`

Query inventory information for products.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `product_id` | str | No | `""` | Product ID filter |
| `sku_id` | str | No | `""` | SKU ID filter |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_bill_list`

Query bill list by time range.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | e.g. `"2024-01-01 00:00:00"` |
| `end_time` | str | Yes | - | e.g. `"2024-01-31 23:59:59"` |
| `bill_type` | str | No | `""` | `1`(订单结算), `2`(退款), `3`(佣金), `4`(保证金) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

---

## 8. WeChat Store (微信小店)

**Server name:** `mcp-cn-weixin-store`
**Base URL:** `https://api.weixin.qq.com`
**Sign method:** None (OAuth 2.0 access_token in query string)

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WX_APP_ID` | Yes* | WeChat App ID |
| `WX_APP_SECRET` | Yes* | WeChat App Secret |
| `WX_ACCESS_TOKEN` | No** | Static access token |

*Either `WX_ACCESS_TOKEN` alone, or `WX_APP_ID` + `WX_APP_SECRET` (server auto-fetches and caches token for ~2 hours).

### Tools

#### `get_order_list`

Query WeChat Store order list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | e.g. `"2024-01-01 00:00:00"` |
| `end_time` | str | Yes | - | e.g. `"2024-01-31 23:59:59"` |
| `order_status` | str | No | `""` | `10`(待付款), `20`(待发货), `30`(已发货), `50`(已完成), `100`(已关闭) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_order_detail`

Get full details of a single WeChat Store order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | Yes | WeChat Store order ID |

#### `get_product_list`

Get product list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | int | No | 0 | `0`(all), `1`(上架), `2`(下架), `3`(审核中), `4`(审核失败) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 200) |

#### `get_product_detail`

Get full details of a single product.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `product_id` | str | Yes | WeChat Store product ID |

#### `get_refund_list`

Query after-sale record list.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | Start time |
| `end_time` | str | Yes | - | End time |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_refund_detail`

Get full details of a single after-sale record.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `after_sale_order_id` | str | Yes | After-sale order ID |

#### `get_logistics_tracking`

Get logistics tracking for an order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | str | Yes | WeChat Store order ID |

#### `get_shop_info`

Get basic shop information.

No parameters.

#### `list_coupons`

List coupon activities.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | int | No | 0 | `0`(all), `1`(进行中), `2`(未开始), `3`(已结束), `4`(已停止) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `get_supply_order_list`

Query supply chain order list (unique to WeChat Store).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `start_time` | str | Yes | - | Start time |
| `end_time` | str | Yes | - | End time |
| `status` | int | No | 0 | `0`(all), `1`(待发货), `2`(已发货), `3`(已完成), `4`(已取消) |
| `page` | int | No | 1 | Page number |
| `page_size` | int | No | 20 | Items per page (max 100) |

#### `list_categories`

List available product categories.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `parent_id` | int | No | 0 | Parent category ID (0 = top-level) |

---

## Error Handling

### Common Error Types

| Exception | Description |
|-----------|-------------|
| `CommerceAPIError` | Platform API returned an error response. Has `code` (int) and `msg` (str) attributes. |
| `ConfigValidationError` | Required environment variables are missing. Has `platform` and `missing_vars` attributes. |
| `DouDianAPIError` | Doudian-specific error. Has `code`, `msg`, `sub_code`, `sub_msg` attributes. |

### Error Response Formats

**Ocean Engine, JD, Taobao, Pinduoduo, Kuaishou, Xiaohongshu:**

Tools return a JSON string:
```json
{"error": {"code": 10001, "message": "Invalid access token"}}
```

**Doudian:**

Tools return a dict:
```json
{"error": "[10001] Invalid access token", "code": 10001, "orders": []}
```

The empty list key matches the tool's primary data key (e.g., `orders`, `products`, `refunds`).

**WeChat Store:**

WeChat errors use `errcode` (0 = success):
```json
{"errcode": 40001, "errmsg": "invalid credential"}
```

### Common Error Codes by Platform

| Platform | Code | Meaning |
|----------|------|---------|
| All | -1 | Network/JSON parse error |
| Doudian | 10000 | Success |
| Doudian | != 10000 | API error (check `msg` and `sub_code`) |
| WeChat | 0 | Success |
| WeChat | 40001 | Invalid credential |
| WeChat | 40002 | Invalid grant_type |
| WeChat | 42001 | Token expired |
| WeChat | 45009 | API call limit reached |
| Taobao/PDD/XHS | 0 or absent | Success |
| Taobao/PDD/XHS | Present in `error_response` | API error |

### Handling Errors in Code

```python
# For tools returning JSON strings (Ocean Engine, JD, Taobao, PDD, KS, XHS)
result = json.loads(tool_output)
if "error" in result:
    print(f"Error {result['error']['code']}: {result['error']['message']}")

# For Doudian tools returning dicts
if "error" in result:
    print(f"Error {result['code']}: {result['error']}")

# For WeChat Store
if "errcode" in result and result["errcode"] != 0:
    print(f"Error {result['errcode']}: {result['errmsg']}")
```

---

## Tool Count Summary

| Platform | Server Name | Tool Count |
|----------|-------------|------------|
| Ocean Engine | mcp-cn-oceanengine | 18 |
| Doudian | mcp-cn-doudian | 22 |
| JD | mcp-cn-jd | 14 |
| Taobao | mcp-cn-taobao | 12 |
| Pinduoduo | mcp-cn-pinduoduo | 13 |
| Kuaishou | mcp-cn-kuaishou | 12 |
| Xiaohongshu | mcp-cn-xiaohongshu | 13 |
| WeChat Store | mcp-cn-weixin-store | 10 |
| **Total** | | **114** |
