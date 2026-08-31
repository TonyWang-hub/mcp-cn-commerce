# 抖店：14 个替代接口的字段级契约（已验证，勿重新调研）

判据：官方文档后端接口（公开无需登录）。每个接口的 `data.article.content` 是内嵌 JSON 字符串，
解析后为 `{request:{publicParam,requestParam}, response:{responseData}, demo, error}`，参数树用
`children` 递归嵌套。`data.article.info` 里的 **`status`/`finalStatus`** 与 **`auths[]`** 是最有价值的
两块元数据；`data.RelevanceFAQs` 才是时间窗、分页上限这类约束的实际出处（接口正文往往不写）。

取数方式见本 mission `quickstart.md` 第 7 条（必须 unset 三个代理变量）。

---

## 0. 通用（官方明文）

公共请求参数（走 query string，所有接口相同）：`method`（点分，如 `order.searchList`）、`app_key`、
`access_token`、`param_json`（业务参数按参数名排序后的标准 JSON）、`timestamp`（`yyyy-MM-dd HH:mm:ss`
GMT+8）、`v`（固定 `2`）、`sign`，以及选填的 `sign_method`。

> **`sign_method`：推荐 `hmac-sha256`，`md5` 将下线，不传默认 md5。** 与此前审计结论一致。

网关 `https://openapi-fxg.jinritemai.com/<path>`；响应外层信封 `{code, msg, sub_code, sub_msg, data}`，
`code == 10000` 为成功。**下文「响应结构」描述的字段都在 `data` 之内**，唯一例外是 `/coupons/list`。

全部 14 个接口 `authSubject=[3]`（店铺级授权）、`status=1`（正式在线）。

---

## 1. 真正的闸门是权限包，不是 status

**14 个接口全部 `status=1`，没有一个是 `status=3` 定向开放。** 但 `status=1` **不等于**「拿到 token
就能调」—— 真正的闸门是 `auths[]` 里的权限包（`packageType=1`）与场景包（`packageType=10`）及其
`categoryList`（可申请的应用类目）。

四个真闸门：

| 接口 | 闸门 |
|---|---|
| `/marketing/queryShopCouponList` | 🔴 **最严**。唯一授权途径是场景包 `商家优惠券查询场景`（packageType=10），categoryList 只有 `服务市场按次订购-微应用`。**无任何普通权限包** → 商家自研/ERP 类应用拿不到，需定向开通 |
| `/marketing/pageQueryActivity` | 🔴 唯一权限包 `营销管理（抖店）` 的 categoryList 只有 `AI售后挽单` |
| `/coupons/list` | 🟡 `商家后台系统` **在**列表内（可自助申请），`电商ERP` **不在** |
| `/shop/reputation` | 🟡 权限包 categoryList **含** `电商ERP`，但 FAQ articleId=3452 明文说「电商ERP 不支持使用也不支持申请」—— **文档自相矛盾，需工单确认** |

其余 10 个对「商家后台系统」类目均有可自助申请的 type=1 权限包。

### ⚠️ 隐性闸门：场景包是**字段级**权限

平台正在把 API 级权限包升级为字段级场景包（articleId=4204 官方明文）。场景包生效时，**同一接口的
响应只返回该应用类目对应的字段子集**。`/order/searchList` 与 `/order/orderDetail` 都挂了多个
packageType=10 的场景包。

**实现含意：不要假设文档里列出的字段一定会返回。** 文档 JSON 里每个出参字段都带 `tagId`
（对应 `tagNameMap`，如 31=订单基础信息、68=买家敏感信息、94=废弃字段），这就是字段分组依据。

---

## 2. 分页范式逐接口不同（不可一概而论）

| 接口 | 分页机制 | 起始 | 上限 |
|---|---|---|---|
| `/order/searchList` | `page` + `size` + `total`，**无 `has_more`、无游标** | `page` **从 0 开始** | `size` ≤ 100；总量见 §3 |
| `/order/orderDetail` | 无分页 | — | 一个主订单最多返回 **40 个子订单** |
| `/product/listV2` | `page`+`size`+`total`，**另有独立游标 `cursor_id`**（两套并存） | `page` **从 1 开始** | `page` ≤ 100 且 `page*size` ≤ **10000**；`use_cursor=true` 可突破 |
| `/afterSale/List` | `page`+`size`+`total` + **`has_more`** | `page` 从 0 开始 | `size` ≤ 100；`page*size` ≤ **50000** |
| `/marketing/queryShopCouponList` | `page_no`+`page_size`+`total` | `page_no` 从 0 开始 | `page_size` ≤ **20** |
| `/marketing/pageQueryActivity` | `page`+`page_size`+`total` | — | `page_size` ≤ **20** |
| `/order/getSettleBillDetailV3` | **双参数游标** | — | `size` 1~100 |
| `/order/getShopAccountItem` | **双参数游标** | — | `size` 默认 100，**最大 1000** |
| `/order/logisticsCompanyList`、`/order/queryOrderLogistics`、`/brand/list`、`/shop/getShopCategory`、`/coupons/list`、`/shop/reputation` | 无分页 | — | `brand/list` 的 `total`/`has_more`/`offset`/`size` 官方标注「**已停止使用**」 |

### 双参数游标（两个财务接口）—— 官方明文，必须照做

每次请求把上次返回的 `next_start_index` 写回 `start_index`、**并且**把 `next_start_time` 写回
`start_time`，循环直到 `is_end == 1`。

> **只更新 `start_index` 会导致翻页无效**（FAQ articleId=6273 明文）。

---

## 3. `/order/searchList` 的时间窗与总量

- **最大查询近 90 天**（接口 subtitle + FAQ 4130 + FAQ 3339 三处一致）。接入指南 articleId=468
  另建议「获取半年内的订单」。
- **必须传时间对**（虽然 `mustNeed=false`）：`create_time_start`+`create_time_end` 或
  `update_time_start`+`update_time_end`；开始与结束都必传且不能相等（FAQ 6076）。
- 时间戳必须**秒级**（FAQ 3566：传毫秒会查不到数据）。
- **总量上限官方内部冲突**：FAQ 5638 说「单次最多 5w 单，size=1 时 page 最大 49999」；接入指南 468
  说「page 最多 100 页，一页 100 单，故最多 1 万单」，同篇后文又说 5w。
  → **保守按 `page*size ≤ 10000` 实现**，更多数据用时间窗切分。
- `combine_status` **只支持 1 个元素**，多状态写在**一个元素内**用逗号分隔：
  `[{"order_status":"2,3"}]`；写成 `[{},{"order_status":"2,3"}]` 会报
  `isv.parameter-invalid:20012`（FAQ 7394）。
- 按 `update_time` 轮询时注意：**订单更新时间只跟主订单状态变更有关，与插旗/备注无关**（FAQ 201/1119）。
- 官方推荐架构：**存量用 searchList + 增量用消息推送 + 漏单用接口补偿**；先列表再详情。

---

## 4. 状态枚举（最容易被编造的部分，逐个取实）

### 订单状态 `order_status`（`searchList` 与 `orderDetail` 一致）
`1` 待确认/待支付 · `105` 已支付 · `2` 备货中（待发货）· `101` 部分发货 · `3` 已发货（全部）·
`4` 已取消 · `5` 已完成（已收货）

`main_status` 追加：`103` 部分支付 · `21` 发货前退款完结 · `22` 发货后退款完结 · `39` 收货后退款完结

### 售后状态（`/afterSale/List`）
**入参** `standard_aftersale_status`（推荐用这个，`aftersale_status` 已废弃）：
`6` 待商家同意 · `7` 待买家退货 · `8` 待商家发货 · `11` 待商家二次同意 · `12` 售后成功 ·
`13` 换货/补寄/维修待买家收货 · `14` 换货/补寄/维修成功 · `27` 商家一次拒绝 · `28` 售后失败 ·
`29` 商家二次拒绝

**出参** `aftersale_info.aftersale_status` 与入参**略有差异**：`3` 换货待买家收货（入参是 13）、
其余同上。

`refund_status`：1 待退款 · 2 退款中 · 3 退款成功 · 4 退款失败 · 5 追缴成功

⚠️ `arbitrate_status` 的**入参与出参枚举文案不一致**（入参：0 未介入 / 1 客服处理中 / 2 仲裁结束-支持买家…；
出参：0 无仲裁记录 / 1 仲裁中 / 2 客服同意…）—— 这是文档原文的差异，不是推断。

### 商品（`/product/listV2`）
`status`：0 在线 · 1 下线 · 2 删除
`check_status`：1 未提交 · 2 待审核 · 3 审核通过 · 4 审核未通过 · 5 封禁 · 7 审核通过待上架

### 卡券（`/coupons/list`）—— 双枚举，最容易踩
- **平台卡券**（入参 `cert_type=1`）：`1` 未使用 · `2` 已使用 · `3` 已失效
- **商家（三方）卡券**（`cert_type=0`）：`1` 未激活 · `2` 未使用 · `3` 已使用 · `4` 已废弃 ·
  `5` 已过期 · `6` 已完成

出参字段 description 只写了三方那套；两套差异写在接口 description/subtitle 里。

### 优惠券（`/marketing/queryShopCouponList`）
`status`：1 未生效 · 2 生效中 · 3 已过期 · 4 已作废
`sub_type`：1 满减 · 2 直减 · 3 折扣（`discount` 字段 8.5 折记作 `85`）

### 营销玩法（`/marketing/pageQueryActivity`）
`activity_info.status`：1 未开始 · 2 进行中 · 6 处理中 · 3 已失效 · 4 已结束
`activity_code`：`LimitTimeTimeBuy`/`LegacyTimeBuy` 限时抢购 · `LimitQuantityTimeBuy` 限量抢购 ·
`OrdinaryTimeBuy` 普通降价促销

### 金额与时间的统一约定
**所有金额单位为分；所有时间戳为秒级。**

---

## 5. 两组「不能合并」的接口

### `/coupons/list` vs `/marketing/queryShopCouponList`

**完全不同的两个业务对象，中文都叫「券」但无交集。**

| | `/coupons/list` | `/marketing/queryShopCouponList` |
|---|---|---|
| 对象 | **虚拟商品的卡券券码/核销码**（消费者手里的一张具体券码） | **店铺营销优惠券的配置与投放**（商家创建的券活动/规则） |
| 官方定性 | FAQ 7336 明文：「查询**虚拟商品的卡券券码信息**，**不涉及**获取平台与店铺的优惠券」 | description：「与商家工作台优惠券管理模块功能一致」 |
| 语义关键词 | **核销** | **发放/配置** |

原代码只有一个 `coupon/list` 工具。**两个都做的话必须拆成两个工具、两个名字** —— 入参、分页、
状态枚举全都不同，合并会产生语义混乱的工具。

**优先级**：`/coupons/list` 权限门槛低（`商家后台系统` 可自助申请），先做；
`/marketing/queryShopCouponList` 只有场景包且类目受限（见 §1），**大概率调不通，投入前先确认权限**。

### `/order/getSettleBillDetailV3` vs `/order/getShopAccountItem`

**财务上两张不同的表。**

| | `getSettleBillDetailV3` | `getShopAccountItem` |
|---|---|---|
| 行的含义 | 一个子订单的一次**结算**，主键 `request_no`（结算单号） | 一笔**资金动账**，主键 `account_trade_no`（动账流水号，唯一） |
| 数据前提 | **只有已结算的订单才有数据** | 任何资金进出：结算、提现、退票、保证金、保费扣除、小额打款、佣金退款… |
| `time_type` | 0 结算时间 / 1 下单时间 | 0 **动账**时间 / 1 下单时间 |
| 方向 | 无方向字段，用 `trade_type` | **`fund_flow`：0 入账 / 1 出账** |
| 独有 | **`settle_amount`（商家实收）** | **`trans_scene`/`trans_scene_tag`（动账场景）** |
| 时间窗 | 间隔**建议 ≤ 7 天** | 无窗口限制，**支持查任意历史区间**（FAQ 4834 可查 2022-10 数据） |
| `order_id` 语义 | **SKU 单/子订单号**，逗号分隔，建议 ≤5 个 | 订单号；传主订单号会返回其下多个子订单的多条记录（FAQ 5696） |
| size | 1~100 | 默认 100，**最大 1000** |

两者**都是 T+1**：建议第二天 10 点后查询，积压导致延迟时重试。

原代码只有一个 `finance/getBillList`。**不能合成一个** —— 行主键不同（去重/幂等逻辑不同）、覆盖范围
不同（后者是「钱的进出」的超集，前者只覆盖「订单结算」）、且 `settle_amount`（商家实收）只有前者有。

**建议拆成两个**：`finance/settleBillDetail` 与 `finance/shopAccountItem`。
若必须只留一个，**选 `getShopAccountItem`** —— 无 7 天窗口限制、支持任意历史区间、size 上限 1000、
覆盖全部资金动账，作为通用「账单列表」语义更贴近 `getBillList` 这个名字。

---

## 6. 各接口的必填参数与 articleId 速查

| 接口 | articleId | 必填参数 | 备注 |
|---|---|---|---|
| `/order/searchList` | 1342 | `size`、`page` + 时间对（见 §3） | dirId=15 |
| `/order/orderDetail` | 1343 | `shop_order_id`（父订单号） | **无时间限制**（FAQ 4130/3339 明文） |
| `/product/listV2` | 633 | `page`、`size` | `update_*_time` 查询范围**不含入参时间点**（开区间） |
| `/afterSale/List` | 1295 | `page`、`size` | 默认只查近 6 个月，超过需指定时间；`update_*` 必须配 `order_by=update_time` 否则轮询会漏 |
| `/order/logisticsCompanyList` | 541 | **无参数** | 返回 `id`/`name`/`code` |
| `/order/queryOrderLogistics` | 7170 | `order_id`（**父订单号**） | 物流状态枚举**取不到**（见 §7） |
| `/brand/list` | 1267 | `category_id`（正文标必填，JSON `mustNeed=false`，错误码证实实际必填） | 过半入出参标「已停止使用」 |
| `/shop/getShopCategory` | 1820 | `cid`（首次传 **0** 取一级类目） | 需递归到 `is_leaf=true`；**必须用叶子类目 id 发布商品**；先判 `enable=true` |
| `/coupons/list` | 369 | 三个入参全 `mustNeed=false`，是否至少传一个**未记载** | **响应异形**：实际路径是 `resp.data.data[]` |
| `/marketing/queryShopCouponList` | 4257 | `page_no`、`page_size` | 字段名官方拼错：**`conpon_name`** 不是 `coupon_name` |
| `/order/getSettleBillDetailV3` | 7226 | `order_id` 未传时 `start_time`+`end_time` 必传 | 另有 articleId=1753 指向同一接口 |
| `/order/getShopAccountItem` | 1430 | `order_id` 未传时时间必传 | |
| `/shop/reputation` | 2658 | **无参数** | 返回四项体验分（string，如 "4.90"） |
| `/marketing/pageQueryActivity` | 7777 | 无字段标 `mustNeed` | 状态查询**需搭配活动时间索引条件**（官方明文） |

限流（官方表 articleId=2158，单应用维度 QPS）：`searchList` 600 · `orderDetail` 900 ·
`product/listV2` 180 · `afterSale/List` 500 · `logisticsCompanyList` 500 · `brand/list` **50** ·
`getShopCategory` 300 · `getShopAccountItem` 100。
其余接口**未收录于该表** —— 官方明文：表外接口「没有应用维度限流，但有总限流规则（总限流值不对外）」。
注意该表本身已过期（只有 `getSettleBillDetailV2`，没有 V3）。

---

## 7. 取不到 / 官方矛盾（按 spec §8，不填充推测）

1. **`/order/queryOrderLogistics` 的物流状态枚举** —— `track_state` 与 `track_info[].state` 的取值，
   文档 description 只有「物流状态」四字，example 是占位 `1`。**取不到。**
2. **`getShopAccountItem` 的 `trans_scene_tag` 枚举表** —— 官方指向站外飞书文档，开放平台文档内
   没有这张表。旧的 `account_bill_desc_tag`（0~23）官方已标「已废弃」，可作过渡参考。
3. **`pageQueryActivity` 的时间索引 key 名** —— 官方 description 里 `start_time_before` 出现两次且
   描述错位（把「活动结束时间下限」也写成它），`limit_type` 取值完全没列。**需实测。**
4. **`queryShopCouponList` 的时间参数格式** —— 类型标 number 但 example 是 `2023-07-01 00:00:00`
   字符串日期。**文档自相矛盾。** 同接口错误码的「PageNo ≤ 20」与参数表的「page_size 最大 20」也不一致。
5. **`getSettleBillDetailV3` 内层 `data.code` 的成功值** —— description 写 `100000`，example 写
   `1000001`。**不一致。**
6. **`searchList` 总量上限** —— FAQ 说 5 万，接入指南说 1 万（同篇又说 5 万）。**官方内部冲突。**
7. **`/shop/reputation` 对「电商ERP」类目是否开放** —— FAQ 3452 说不支持不可申请，实时 `auths`
   说包含。**冲突，需工单。**
8. **`/coupons/list` 是否必须至少传一个参数** —— 三个入参全 `mustNeed=false`，文档未说明。**未记载。**
9. **`apiChargeType` / `apiLimitValue` / `apiLimitLevel` / `defaultApiAndAppLimitValue`** 这几个接口
   metadata 字段官方无公开定义表，且 `apiLimitValue` 与公开限流表数值不吻合（searchList: 5500 vs 600）。
   **不推断其含义**，限流以 articleId=2158 的公开表为准。
10. **`status` 字段的枚举**（1/0/3）平台无公开定义。`0=已下线` 有铁证
    （`getSettleBillDetailV2` 是 status=0 且 userSceneDesc 写「【已下线】」+ 有下线公告 6507）；
    `3=定向开放` 属**推断**（依据是这些接口有「为什么文档里找不到」的 FAQ 且无可自助申请的权限包）。

## 8. 已废弃字段（实现时不要依赖）

- `searchList`/`orderDetail` 顶层 `trade_type`/`trade_type_desc`/`send_pay` 标【已废弃】→
  改用 `sku_order_list.trade_type`
- `afterSale/List` 入参 `aftersale_status` 已废弃 → 用 `standard_aftersale_status`；
  出参 `main_status` 亦标废弃
- `product/listV2`：`market_price`/`discount_price`/`pay_type`/`cos_ratio`/`description`/`mobile`/
  `recommend_remark` 已废弃；`out_product_id` 标【即将废弃】→ 用 `outer_product_id`
- `brand/list`：`categories`/`offset`/`size`/`sort`/`status`/`full_brand_info` 入参与
  `brand_ids`/`brand_infos`/`total`/`has_more` 出参**全部标注「已停止使用」**
- `getShopAccountItem`：`account_bill_desc_tag` 枚举已废弃 → 用 `trans_scene_tag`
