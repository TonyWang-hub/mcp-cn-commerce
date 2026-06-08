# Chinese E-Commerce Platform Comparison

## Platform Overview

| 平台 | 开放平台地址 | API 端点 | 认证方式 | 签名方法 | 主要能力 | Phase |
|---|---|---|---|---|---|---|
| 巨量引擎 | [open.oceanengine.com](https://open.oceanengine.com) | `ad.oceanengine.com/open_api/` | OAuth 2.0 | MD5 | 广告报表/计划管理 | 1 |
| 抖店 | [op.jinritemai.com](https://op.jinritemai.com) | `openapi-fxg.jinritemai.com` | AppID+Secret | MD5 | 订单/商品/售后 | 1 |
| 京东 | [jos.jd.com](https://jos.jd.com) | `api.jd.com/routerjson` | OAuth 2.0 | HMAC-MD5 | 订单/商品 | 1 |
| 淘宝 | [open.taobao.com](https://open.taobao.com) | `eco.taobao.com/router/rest` | OAuth 2.0 | HMAC-MD5 | 订单/商品/物流 | 2 |
| 拼多多 | [open.pinduoduo.com](https://open.pinduoduo.com) | `gw-api.pinduoduo.com/api/router` | OAuth 2.0 | MD5 | 订单/商品/推广 | 2 |
| 快手 | [open.kuaixiaodian.com](https://open.kuaixiaodian.com) | `openapi.kwaixiaodian.com` | OAuth 2.0 | MD5 | 订单/商品/物流 | 3 |
| 小红书 | [open.xiaohongshu.com](https://open.xiaohongshu.com) | (开放平台) | OAuth 2.0 | MD5 | 订单/商品/库存 | 3 |
| 微信小店 | [developers.weixin.qq.com](https://developers.weixin.qq.com) | `api.weixin.qq.com` | OAuth 2.0 | MD5 | 订单/商品/售后 | 3 |

## Auth Mechanisms

| 平台 | Auth Type | Token Source | Token Refresh | Notes |
|---|---|---|---|---|
| 巨量引擎 | OAuth 2.0 (Authorization Code) | `/oauth2/access_token` | Refresh token (long-lived) | Access token expires in 24h |
| 抖店 | App Key + App Secret | Manual in developer console | N/A (permanent) | No OAuth flow — key/secret directly |
| 京东 | OAuth 2.0 (Authorization Code) | `/oauth2/access_token` | Refresh token | Access token expires; refresh before expiry |
| 淘宝 | OAuth 2.0 (Authorization Code) | `/token` | Refresh token (48h validity, 30d refresh window) | Access token 48h, refreshable within 30d |
| 拼多多 | OAuth 2.0 (Authorization Code) | `/oauth2/access_token` | Refresh token | Standard OAuth 2.0 flow |
| 快手 | OAuth 2.0 (Authorization Code) | `/oauth2/access_token` | Refresh token | Access token expires in 7d |
| 小红书 | OAuth 2.0 (Authorization Code) | Token via authorization callback | Refresh token | Standard OAuth 2.0 flow |
| 微信小店 | OAuth 2.0 (Authorization Code) | `/cgi-bin/token` | Refresh via `/cgi-bin/stable_token` | WeChat-style OAuth, not full OAuth 2.0 |

## Signing Methods

| 平台 | Sign Method | Algorithm | Input Construction |
|---|---|---|---|
| 巨量引擎 | MD5 | `md5(app_secret + sorted_kv_string + app_secret)` | All params sorted alphabetically |
| 抖店 | MD5 | `md5(app_secret + sorted_kv_string + app_secret)` | All params sorted alphabetically |
| 京东 | HMAC-MD5 | `hmac_md5(key=app_secret, msg=app_secret + sorted_kv_string + app_secret)` | System params only |
| 淘宝 | HMAC-MD5 | `hmac_md5(key=app_secret, msg=app_secret + sorted_kv_string + app_secret)` | All params sorted alphabetically |
| 拼多多 | MD5 | `md5(app_secret + sorted_kv_string + app_secret)` | All params, JSON values serialized |
| 快手 | MD5 | `md5(app_secret + sorted_kv_string + app_secret)` | System + biz params combined |
| 小红书 | MD5 | `md5(app_secret + sorted_kv_string + app_secret)` | All params sorted alphabetically |
| 微信小店 | MD5 | `md5(app_secret + sorted_kv_string + app_secret)` | All params sorted alphabetically |

## API Capability Matrix

| 平台 | 订单查询 | 商品管理 | 售后/退款 | 物流查询 | 库存管理 | 广告报表 | 推广工具 | 店铺管理 |
|---|---|---|---|---|---|---|---|---|
| 巨量引擎 | -- | -- | -- | -- | -- | Yes | Yes | Yes |
| 抖店 | Yes | Yes | Yes | Yes | Yes | -- | -- | Yes |
| 京东 | Yes | Yes | -- | -- | -- | -- | -- | Yes |
| 淘宝 | Yes | Yes | Yes | Yes | Yes | -- | Yes | Yes |
| 拼多多 | Yes | Yes | Yes | -- | -- | -- | Yes | Yes |
| 快手 | Yes | Yes | Yes | Yes | -- | -- | -- | Yes |
| 小红书 | Yes | Yes | -- | -- | Yes | -- | -- | Yes |
| 微信小店 | Yes | Yes | Yes | Yes | Yes | -- | -- | Yes |

## Phase Roadmap

### Phase 1 — Foundation (Read-only MVP)
- **巨量引擎**: Ad campaign & report read APIs
- **抖店**: Order, product, after-sale read APIs
- **京东**: Order, product, shop read APIs

### Phase 2 — Mid-tier Expansion
- **淘宝**: Full Top API integration — orders, products, logistics
- **拼多多**: Orders, products, promotion tools

### Phase 3 — Long-tail Coverage
- **快手**: Orders, products, logistics
- **小红书**: Orders, products, inventory
- **微信小店**: Orders, products, after-sale

## Common Patterns

All platforms share a similar request pattern:

1. **Base URL** + router/endpoint path
2. **System params**: `app_key`, `timestamp`, `sign_method`, `sign`, `access_token`
3. **Business params**: method-specific parameters (in query string or body)
4. **Signing**: `app_secret` sandwich around alphabetically-sorted KV pairs, then hash
5. **Response**: unified `{ error_response, result }` envelope (naming varies by platform)

The shared base class `CommerceMCPBase` in `shared/cn_commerce_base.py` encapsulates this pattern so each platform server only needs to:
- Set `BASE_URL` and `sign_method`
- Override `_sign()` if non-MD5 signing is needed
- Define tools that call `self._request()` or a platform-specific `_call()` wrapper
