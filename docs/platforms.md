# 平台协议与验证边界

本项目是第三方 MCP 适配器，连接商家授权的官方接口。平台开放 API、官方 SDK、官方 MCP 服务是不同的交付形式；官网存在不代表当前账号自动拥有订单、账单或广告权限。

2026-09-10 的来源核查见 [official-access-status.md](official-access-status.md)。这里记录代码接入方式和需要验证的接口契约，不承诺未经真实账号验证的可用率、token 固定有效期或资质政策。

| 平台 | 代码凭证 | 协议实现及验证要求 |
|---|---|---|
| 巨量引擎 | `OCEANENGINE_ACCESS_TOKEN` | 官方 SDK 使用 `Access-Token` 请求头；广告主、广告、千川和星图分别需要对应授权。应用 key/secret 用于授权管理时才配置。 |
| 抖店 | `DOUDIAN_APP_KEY`、`DOUDIAN_APP_SECRET`、`DOUDIAN_ACCESS_TOKEN`；部分接口需要 shop id | 已按官方指南实现 HMAC-SHA256，规范化 JSON 与实际发送正文一致；业务方法、权限和响应仍需授权店铺逐项验证。不能把 token 当永久有效。 |
| 京东 | `JD_APP_KEY`、`JD_APP_SECRET`、`JD_ACCESS_TOKEN` | JOS 参数封装、签名参与字段和各金额单位需逐接口验证。 |
| 淘宝 | `TAOBAO_APP_KEY`、`TAOBAO_APP_SECRET`、`TAOBAO_ACCESS_TOKEN` | TOP session 映射、timestamp 格式、签名方式和店铺权限需逐项核对。 |
| 拼多多 | `PINDUODUO_CLIENT_ID`、`PINDUODUO_CLIENT_SECRET`、`PINDUODUO_ACCESS_TOKEN` | 商家数据权限与多多进宝推广权限分别核实；时间类型、窗口和复杂参数编码需契约样例。 |
| 快手 | `KUAISHOU_APP_KEY`、`KUAISHOU_APP_SECRET`、`KUAISHOU_SIGN_SECRET`、`KUAISHOU_ACCESS_TOKEN` | 签名密钥单独保留；修复配置传参后仍需官方签名向量和接口样例。 |
| 小红书 | `XHS_CLIENT_ID`、`XHS_CLIENT_SECRET`、`XHS_ACCESS_TOKEN` | 已按官方统一网关、签名和 schema 迁移 9 个业务工具；评论、店铺信息、活动、优惠券 4 个旧入口明确返回不支持，不发送请求。须使用商家应用及对应接口权限；真实店铺联调待完成。 |
| 微信小店 | 静态：`WX_ACCESS_TOKEN`；自动管理：`WX_APP_ID`、`WX_APP_SECRET` | 默认有 token 时使用静态模式；`WX_TOKEN_MODE=managed` 明确启用刷新。业务请求无需套通用 MD5；订单时间、游标/页码需按当前接口核对。 |

## 小红书当前映射

公共请求使用官方统一 POST JSON 网关；业务字段与公共字段进入同一正文，签名仅覆盖官方规定的系统字段。签名和网关来源：[官方签名指南](https://open.xiaohongshu.com/document/developer/file/39)、[系统参数](https://open.xiaohongshu.com/document/developer/file/40)。

| 本项目工具 | 当前官方方法 / 状态 |
|---|---|
| `get_order_list` | `order.getOrderList`，创建时间窗口不超过 24 小时 |
| `get_order_detail` | `order.getOrderDetail` |
| `get_product_list` | `product.searchItemList` |
| `get_product_detail` | `product.getItemInfo` |
| `get_refund_list` | `afterSale.listAfterSaleInfos` |
| `get_refund_detail` | `afterSale.getAfterSaleInfo` |
| `get_logistics_tracking` | `order.getOrderTracking` |
| `get_inventory` | `inventory.getSkuStockV2`，必须提供 `sku_id` |
| `get_bill_list` | `finance.querySellerAccountRecords`，仅接受官方枚举 |
| `get_review_list`、`get_shop_info`、`list_promotions`、`list_coupons` | 未取得对应官方接口合同，明确不支持，不发送 HTTP |

以上是源码中的协议映射，不代表已通过真实店铺授权调用。原先按月查询订单/退款、只传商品 ID 查询库存、传旧数字账单类型的调用，需要按新的参数约束调整。

## 共享 transport 的边界

平台适配器构造最终 URL、参数、请求头、签名和响应解析器；共享 transport 负责连接复用、HTTP 状态、重试、限流、指标和 trace。不能假设所有平台都有同样的 app_key/sign/access_token 系统参数，也不能用一种 error_response 包装推断所有平台业务成功。

查询接口即使使用 POST，也只有在适配器明确其只读语义后才配置重试。动态签名在每次尝试前重新生成。请求监控记录实际尝试结果，业务错误也计为失败。

## 接入验收记录

每个已承诺接口应有以下记录，缺失证据时维持“待验证”状态：

1. 官方文档/SDK 链接、接口名与版本、查询日期。
2. 应用类型、商家授权、权限包、店铺类型限制。
3. 最终请求的签名向量、URL、header、query/body 编码。
4. 脱敏的成功、业务失败、权限不足响应。
5. 时间单位/时区、金额单位、分页方式、最大窗口和配额。
6. 两页以上数据的去重、终止条件和完整性验证。
7. 真实只读联调日期、环境与后台核对结果；不得保存真实凭证。

“代码已实现”“本地契约通过”“真实店铺通过”分别记录。注册工具数量、模拟响应和官网首页均不能替代真实店铺验收。

## 数据输出

平台工具保留原始响应契约。使用 build_daily_report 时，应先提取订单/退款列表，完成事件日期窗口内的全部分页，再提交 raw 或 normalized 记录和明确的 coverage。金额、时间、质量错误与日报口径见 [data-contracts.md](data-contracts.md) 和 [template-guide.md](template-guide.md)。

## 本地续验补充（2026-09-10）

- 淘宝 TOP 已使用 `session`、GMT+8 格式 timestamp，签名包含 `sign_method`，官方固定向量通过。系统字段放 query；错误由 MCP 报错传播，避免把请求失败呈现成成功数据。
- 微信订单列表 `get_order_list` 新增 `next_key` 与 `time_type=create|update`；只保留 `page=1` 兼容参数，后续页必须传原响应游标。时间窗口最多7天，page_size为1–100，时间转换为秒。返回 `order_id_list` 时仍须查询订单详情。订单状态以官方枚举为准，100=完成、250=取消。
- 京东、拼多多和快手的当前协议仍需确认；已发现的旧官方文档与现实现差异见 [官方证据](official-access-status.md#本地续验2026-09-10)。模拟测试通过不能消除这些接入卡点。
