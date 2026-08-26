# 小红书电商开放平台契约声明

对象：`servers/xiaohongshu/server.py`（`XiaohongshuMCP`）
wire 层断言：`tests/contract/test_wire_xiaohongshu.py`
工具层断言：`servers/xiaohongshu/tests/test_xiaohongshu.py`
审计依据：`kitty-specs/api-contract-conformance-01M0ZHQN/spec.md` §2.2 / §2.3.1 / §2.3.2 / §8、`tasks/WP07-小红书重写.md`（FR-008 / IC-07）
最后核对：2026-08-27（本 WP **联网取到了官方机器可读文档**，见 §0）

> 本 server 的旧实现与官方契约**无一处吻合**（网关、HTTP 动词、传输位置、参数名、
> timestamp 单位、签名算法、判错信封、endpoint 全部错），所以这不是"修契约"，是重写。

## 0. 出处标注规则与本文的证据来源

每条结论标注「**官方明文**」（官方文档/机器可读 spec 里逐字写着）或「**推断**」（由官方
示例值、schema 类型、字段名语义推出，官方正文未明确写）。**不得用推测填充**（spec §8）。

与本仓其他契约文档不同，小红书的官方文档后端是**公开可读、无鉴权**的，本次实施直接取到了
原始 spec。以下 5 个 oracle 可原地复现，是本文所有「官方明文」的出处：

| # | oracle | 取法 | 内容 |
|---|---|---|---|
| O1 | 一级分组清单 | `GET https://open.xiaohongshu.com/api/doc/listNew` | 11 个分组（公共/订单/售后/商品/库存/素材中心/物流/财务/即时零售/会员通/供货商） |
| O2 | 分组内 method 清单 | `GET https://open.xiaohongshu.com/api/doc/second/listNew?apiNavigationId=<id>` | 每条记录自带 `path`（= method 名）、`apiId`、**`gatewayId`/`gatewayVersionId`**、`method`（HTTP 动词，全部 `post`） |
| O3 | 单接口 OpenAPI spec | `GET https://open.xiaohongshu.com/api/doc/infoNew?apiId=<apiId>&gatewayId=<gw>&gatewayVersionId=<gv>` | 入参/出参 schema、required 列表、字段中文描述、example 值 |
| O4 | 公共参数 spec | `GET https://open.xiaohongshu.com/api/doc/common/paramNew` | 系统参数表（`CommonParametersV3`，schema id 217610，updateTime 2025-12-08） |
| O5 | 开发者文档正文 | `POST https://open.xiaohongshu.com/api/developer/doc/getDocDetailNew`，body `{"docDetailId":39}`（签名算法）/ `{"docDetailId":40}`（系统参数说明）/ `{"docDetailId":292}`（接口限流说明） | 签名算法正文 + Java/Python/Go 示例代码；网关 URL、Content-Type、返回信封 |

人读入口（SPA，内容同上）：`https://open.xiaohongshu.com/document/developer`（开发者文档
→ 签名算法 / 系统参数说明）、`https://open.xiaohongshu.com/document/api`（API 文档）。

**不作为依据的来源**：第三方 apifox 镜像（spec 明令；其订单入参仍是 `packageType`/
`packageStatus`，现行 O3 里是 `orderType`/`orderStatus`，已过期）；官方文档里的两处
**已下线 method 示例**（见 §3.5）。

## 1. 网关与传输

| 项 | 结论 | 类别 | 出处 |
|---|---|---|---|
| 网关 | **单一网关** `https://ark.xiaohongshu.com/ark/open_api/v3/common_controller`，所有业务接口共用 | 官方明文 | O5(40) 注2「所有业务接口url如下」；O4 的 `path` 字段亦为 `/ark/open_api/v3/common_controller` |
| HTTP 动词 | **只有 POST** | 官方明文 | O5(39)「Method: post」；O2 中 106 条记录的 `method` 字段全部为 `post` |
| 传输位置 | 系统参数与业务参数**全部扁平放 POST body（JSON）**，同一层级，无 query string | 官方明文 | O5(40)「系统参数通过post形式的http请求的body传入」；O5(39) 的 body 示例把系统参数与业务参数写在同一个 JSON object 里 |
| Content-Type | `application/json;charset=utf-8` | 官方明文 | O5(40) 注1 |
| 域名易错点 | `open.xiaohongshu.com` 是**文档站/控制台**，不是调用网关；`ark.` 才是 | 官方明文 | O5(40) 注2 与本文 oracle 域名对比 |
| `"path":"/ark/order.getOrderList"` | 那是**文档系统内部注册路径**，不是调用地址 | 推断（强） | O3 的每条记录都有该字段，但 O5(40)/O5(39) 明文说业务 URL 恒为 `common_controller`；两者只能这样自洽 |
| 旧实现的 `/api/order/list` 等 REST path | **任何版本的官方文档/机器可读 spec 中均不存在** | 官方明文 | O1+O2 全量 106 条 method，无一条是 REST path 形态（spec §2.2「模式三：通用 REST 模板」） |

## 2. 系统参数

O4 的 `CommonParametersV3` schema 逐字如下（`required` = `[appId, method, sign, timestamp, version]`，
全部 `"type":"string"`）：

| 参数 | 必填 | 类型 | 说明 | 类别 |
|---|---|---|---|---|
| `appId` | 必须 | string | 创建应用的 appId | 官方明文 |
| `method` | 必须 | string | 具体调用方法（如 `order.getOrderList`） | 官方明文 |
| `version` | 必须 | string | API 协议版本号，**`"2.0"`** | 官方明文 |
| `timestamp` | 必须 | string | 「UNIX时间戳，**单位秒**」，example `"1612518379"`（10 位） | 官方明文 |
| `sign` | 必须 | string | 签名结果 | 官方明文 |
| `accessToken` | 非必须，**调用商家业务接口必须** | string | 「该字段**不参与sign签名运算**」 | 官方明文 |

命名全部 **lowerCamelCase**。旧实现发的 `client_id` / `sign_method` / `access_token` /
`app_key` 在官方参数表里**都不存在**，wire 测试已把这四个名字钉成负向断言。

### 2.1 时间单位（入出参不一致，最易错）

| 位置 | 单位 | 类别 | 出处 |
|---|---|---|---|
| 系统参数 `timestamp` | **秒**（10 位字符串） | 官方明文 | O4「单位秒」 |
| `order.getOrderList` 入参 `startTime`/`endTime` | **秒** | 推断（强）：官方描述只写「时间范围起点/终点」未写单位，但 example 值 `1612518379` 是 10 位，且与 O4 的 timestamp example 同值 | O3 apiId=27241 |
| 订单出参 `createdTime`/`paidTime`/`updateTime`/`deliveryTime`/`finishTime` … | **毫秒** | 官方明文（描述逐字「单位ms」，example `1612518379000`） | O3 apiId=27241 / 27242 |
| `afterSale.listAfterSaleInfos` 入参 `startTime`/`endTime` | **毫秒** | 官方明文（描述「时间起点（毫秒，包含）」） | O3 apiId=30115 |
| `finance.querySellerAccountRecords` 入参 | **毫秒** | 官方明文（「开始时间，毫秒」） | O3 apiId=29893 |
| `finance.pageQueryTransaction` / `pageQueryExpense` 入参 | **毫秒** | 推断（强）：描述写「unix时间戳」未写单位，但同句给出的窗口上限是 `24*60*60*1000` ⇒ 只有毫秒能自洽 | O3 apiId=29896 / 29894 |
| `order.getOrderTracking` 出参 `eventAt` | **`yyyy-MM-dd HH:mm:ss` 字符串**（不是时间戳） | 官方明文（example `2021-04-19 22:06:48`） | O3 apiId=27239 |

结论：**同一个 server 内三种时间单位并存**。代码里每个工具的 docstring 逐条写明本工具入参
单位，不做统一换算（换算会掩盖差异）。

### 2.2 金额单位

订单出参金额字段（`totalPayAmount`/`totalShippingFree`/`totalDepositAmount`/
`merchantActualReceiveAmount` …）单位为**分**，净重单位为 **g**。官方明文（O3 apiId=27242 各字段描述）。

## 3. 签名

### 3.1 算法（官方明文，O5 docDetailId=39）

```
signSource = method + "?" + "appId={appId}&timestamp={timestamp}&version={version}" + appSecret
sign       = lowercase(hex(md5(signSource)))          # 32 位
```

| 细节 | 结论 | 类别 | 出处 |
|---|---|---|---|
| 参与集合 | **只有 4 个系统参数**：`appId`、`timestamp`、`version`、`method` | 官方明文 | 「目前参与加密的均为系统参数和appSecret。系统参数有：appId,timestamp,version,method」 |
| `accessToken` | **不参与** | 官方明文（两处） | O5(39) body 注释「非必须，不参与验签」；O4 字段描述「该字段不参与sign签名运算」 |
| 业务参数 | **不参与** | 官方明文 | 同「参与集合」一句；三份官方示例代码的入参只有 `appId/timestamp/method/appSecret` |
| `method` 的位置 | 在 `?` **之前**，本身不是 `k=v` 形式、**不参与排序** | 官方明文 | 示例代码 `signSource = method + "?" + queryStr + appSecret`，`params` 列表里只有三个 `k=v` |
| 排序 | 三个 `k=v` 段按自然序（`params.sort()`）⇒ `appId` < `timestamp` < `version` | 官方明文 | Java `params.sort(Comparator.naturalOrder())` / Python `params.sort()` / Go `sort.Strings` |
| `appSecret` 拼接 | 直接拼在末尾，**中间无任何分隔符** | 官方明文 | 示例代码字符串拼接 + 正文步骤 2 |
| 大小写 | **小写** 32 位 hex | 官方明文 | Python `hexdigest()`、Java `String.format("%02x", b)`、Go `hex.EncodeToString` 三份示例一致 |
| 摘要 | MD5（无 secret 包裹、非 hmac） | 官方明文 | 同上 |
| `& ` 后的空格 | 官方正文写作 `appId=xxx& timestamp=xxx`，**同页已注明「拼接字段空格为格式，实际中不存在」**，且三份示例代码都无空格 ⇒ 真实串**无空格** | 官方明文 | O5(39) 步骤 1 标题 |

### 3.2 官方算例无法作为签名向量（不进 `tests/contract/vectors.py`）

O5(39) 给了一个完整的分步算例，但**三项输入与期望值都被打了码**：
`appId:21d6***748be8de0`、`appSecret:429a***a3aee9ef9e4a858210`、期望
`aa4c59****50632d80dc4`。缺失的字符无法反推，因此**不存在可复现的官方向量**。

按 WP01 建立的纪律（`tests/contract/vectors.py` 顶部注释：「a guessed input that happens
to hash correctly would silently bless a wrong implementation」），本 WP **不构造**输入串去
凑那个期望值，也不往 `vectors.py`（WP01 的文件，非本 WP 所有）里塞一条假向量。替代护栏是
`tests/contract/test_wire_xiaohongshu.py` 里**独立实现一遍官方算法**（照 O5 的三份示例代码
写，不调用生产代码），再逐字段做差分断言：改 `appId`/`method`/`timestamp`/`appSecret` 签名必变，
改 `accessToken`/业务参数签名必不变。

### 3.3 与旧实现的差异

旧实现用的是共享基类 `CommerceMCPBase._sign`：`upper(md5(secret + sorted_kv + secret))`，
且把**全部业务参数与 `access_token` 都拼进去**。对小红书四项全错（包裹、排序集合、
参与集合、大小写）。本 server **完全不调用** `CommerceMCPBase._request` / `._sign`
（`servers/xiaohongshu/tests/test_xiaohongshu.py::test_sign_is_not_the_shared_base_algorithm`
把这条钉住），也**未修改** `shared/cn_commerce_base.py`。

### 3.4 「签名集合 == 发送集合 − {sign}」这条跨平台不变式（spec §8）

**小红书是这条不变式的官方明文例外**：`accessToken` 与全部业务参数**被发送但不入签**。

处理方式不是跳过通用断言，而是在
`tests/contract/test_wire_xiaohongshu.py::test_signature_set_matches_sent_modulo_documented_exceptions`
里把例外集合显式列出、从发送集合中扣除后**仍然调用** WP01 提供的
`assert_signature_set_matches_sent`，并且：

1. 先断言「例外项确实在发送集合里」—— 否则"例外"会变成掩盖漏发参数的借口；
2. 另有 `test_naive_signature_set_invariant_would_fail_here` 断言**不扣例外时通用断言必须失败**
   —— 证明这个例外是真的，同时构成护栏：若有人为了让通用断言变绿而把业务参数塞进签名，
   官方验签会失败，而这条测试会先红。

### 3.5 官方示例里的两个已下线 method（抄示例必错）

| 出现位置 | 示例值 | 状态 | 出处 |
|---|---|---|---|
| O4 / O5(40) 系统参数 `method` 的 example | `package.getPackageList` | **2023-04-13 已下线**，`package.*` 整个域被 `order.*` 取代 | spec §2.3 小红书条目；O1+O2 全量 106 条 method 中无 `package.*` |
| O5(39) 签名算法正文与示例 | `product.createItem` | 已被 `product.createItemV2`（官方标「即将废弃」）与 `product.createItemAndSku`（新）取代 | O2 apiNavigationId=17：现行清单里只有 `createItemV2` / `createItemAndSku`，无 `createItem` |

wire 测试 `test_retired_method_names_are_never_sent` 把这两个名字钉成负向断言。
注意：`product.createItem` 作为**签名算例的输入**仍然有效（算法与 method 是否在线无关），
本文 §3.1 的算例照官方原样保留，但**代码里绝不发送**它。

## 4. 判错与信封

### 4.1 网关信封（官方明文，O5 docDetailId=40「返回参数说明」）

```json
{
  "error_code": 0,
  "error_msg": "错误信息",
  "data": { "//": "API文档中返回示例内容" },
  "success": true
}
```

成功判据：**`error_code == 0` 且 `success == true`**；业务数据在 `data`，**需解包一层**。
（旁证：本文 5 个 oracle 自身就是这个信封，例如 `{"data":"[...]","error_code":0,"success":true}`。）

旧实现查的是 `error_response`（淘宝/拼多多的信封形态）⇒ 小红书的失败**完全检测不到**，
会把错误信封当业务数据交给模型。现在的实现 **fail-closed**：任何认不出的信封（缺
`error_code`/`success`、`success:false`、空 body、非 JSON object）都抛 `CommerceAPIError`。

### 4.2 错误码

| 项 | 结论 | 类别 | 出处 |
|---|---|---|---|
| 形态 | 负整数 | 官方明文 | O5(40) 信封示例 + 见下 |
| `-2000400` | 请求参数错误 | **推断/待复核** | 来自 mission 审计语料（`tasks/WP07-小红书重写.md`）。本次尝试用 `POST /api/webSearch/searchDocByKey`（`{"key":"-2000400","pageSize":10,"pageNo":1}`）在公开文档语料中检索，**0 命中**；`GET /api/doc/errorcodeNew` 返回空数组 ⇒ 平台未公开错误码表 |
| `-2000101` | 包裹不存在 | **推断/待复核** | 同上 |

代码里**不硬编码错误码语义**，只把 `error_code` 原样带进 `CommerceAPIError.code`。

### 4.3 网关版本混排（实现要点一）

O2 的每条记录自带 `gatewayId`/`gatewayVersionId`。本 server 用到的 12 个 method 分属两族：

| 网关版本 | method | 出处 |
|---|---|---|
| **103 / 1661** | `order.getOrderList`、`order.getOrderDetail`、`order.getOrderTracking`、`product.searchItemList`、`product.getItemInfo`、**`bill.downloadStatement`** | O2 nav=15/17/21 |
| **165 / 2804** | `afterSale.listAfterSaleInfos`、`afterSale.getAfterSaleInfo`、`inventory.getSkuStockV2`、`finance.pageQueryTransaction`、`finance.querySellerAccountRecords`、`finance.pageQueryExpense` | O2 nav=16/18/21 |

⚠️ 两个反直觉点，都由 O2 直接给出，不要按域名猜：

* **`bill.*` 在 103/1661，`finance.*` 在 165/2804** —— 同属"账单"语义却不同族。
* **库存 V2 换了族**：`inventory.getSkuStock`（旧）在 103/1661，`inventory.getSkuStockV2` 在 165/2804。
* 售后新旧同理：`afterSale.listAfterSaleApi`/`getAfterSaleDetail`（旧）在 103/1661，
  `listAfterSaleInfos`/`getAfterSaleInfo`（新）在 165/2804。**查文档必须用各 method 自己的
  gatewayId/gatewayVersionId**，否则 O3 直接报 `Cannot destructure property 'gatewayVersionName'`。

两族的**形态差异**（这就是"不能用一套请求构造器无脑套"的具体含义）：

| 差异 | 103/1661 | 165/2804 | 类别 |
|---|---|---|---|
| `path` 字段形态 | `/ark/order.getOrderList` | `/api/openapi/aftersale/listaftersaleinfos`（全小写 REST 形) | 官方明文（O3 `path`） |
| `requestHeader` 入参 | 无 | `afterSale.getAfterSaleInfo` 有可选 `requestHeader{requestFrom:number}` | 官方明文（O3 apiId=30038） |
| 响应 schema | 直接就是业务体（如 `total`/`maxPageNo`/`orderList`） | **自带一层 `{code, msg, success, data}`**（`required:[code,data,success]`，注意是 `code` 不是 `error_code`） | 官方明文（O3 apiId=30115/30038/34182/29896/29893/29894） |

实现：`XiaohongshuMCP.METHOD_GATEWAY` 登记每个 method 的族；`_unwrap_envelope` 对 165/2804
族在解掉网关信封后**若仍存在 `{code, success}` 就再解一层**（内层同样 fail-closed）。
`_call` 对**未登记的 method 直接拒绝**，避免再次打到不存在的接口上。

**待官方澄清 / 待真机回归**：官方未明文说明 165/2804 族那层 `{code,msg,success,data}` 是
"网关信封之外的接口自带层"还是"O3 把网关信封一起画进了响应 schema"。本实现按「存在则再解
一层」处理，两种读法都能走通；若真机返回的是**单层**且用 `code` 承载网关状态，`_check_envelope`
也接受 `code`（`payload.get("error_code", payload.get("code"))`）。三层情形（`inventory.getSkuStockV2`
的 `data.response{code,msg,success}`）**不解**：那是业务体内的状态节点，官方未把它列为判错层，
本实现原样返回并在工具 docstring 注明。

### 4.4 限流（官方明文，O5 docDetailId=292，v1.0 2024-09-14）

应用维度默认 100 次/秒（老应用按 1.5×MaxQPS）；method 维度默认 200 次/秒（老接口按
2.5×APIQPS）；另有"应用+方法"维度按商家单独配置。另：`order.getOrderList` 官方建议单商家
轮询间隔 ≥ 5 分钟（spec §2.3.1 小红书条目）。

## 5. Endpoint 清单（13 → 12）

### 5.1 保留并改正的 8 个

| 旧虚构 path | 官方 method | 工具 | 关键入参（官方 required 加粗） | 出处 |
|---|---|---|---|---|
| `/api/order/list` | `order.getOrderList` | `get_order_list` | **`startTime`**、**`endTime`**、**`timeType`**、`orderType`、`orderStatus`、`pageNo`、`pageSize` | O3 apiId=27241 |
| `/api/order/detail` | `order.getOrderDetail` | `get_order_detail` | **`orderId`** | O3 apiId=27242 |
| `/api/logistics/tracking` | `order.getOrderTracking` | `get_logistics_tracking` | **`orderId`** | O3 apiId=27239 |
| `/api/product/list` | `product.searchItemList` | `get_product_list` | **`pageNo`**、**`pageSize`**、**`searchParam`**（object） | O3 apiId=27226 |
| `/api/product/detail` | `product.getItemInfo` | `get_product_detail` | **`itemId`**、`pageNo`、`pageSize` | O3 apiId=27227 |
| `/api/refund/list` | `afterSale.listAfterSaleInfos` | `get_refund_list` | **`pageNo`**、**`pageSize`**、`orderId`、`statuses`、`returnTypes`、`startTime`、`endTime`、`timeType` | O3 apiId=30115 |
| `/api/refund/detail` | `afterSale.getAfterSaleInfo` | `get_refund_detail` | `returnsId`、`needNegotiateRecord`、`requestHeader`（官方 required 为空） | O3 apiId=30038 |
| `/api/inventory/query` | `inventory.getSkuStockV2` | `get_inventory` | **`skuId`**、`inventoryType` | O3 apiId=34182 |

### 5.2 `/api/bill/list` 拆成 4 个（账单不是一个列表）

官方财务分组（O2 nav=21）共 5 个 method，语义互不重叠，原来的单个 `get_bill_list`
（带一个虚构的 `bill_type` 过滤器）无法映射到其中任何一个。按语义拆分：

| 工具 | 官方 method | 语义 | 官方 required | 官方窗口约束 |
|---|---|---|---|---|
| `get_settlement_transactions` | `finance.pageQueryTransaction` | 分页查询**订单货款**结算明细 | `startTime`、`endTime`、`pageNum`、`pageSize` | 单次 ≤ 一天（`24*60*60*1000`） |
| `get_account_records` | `finance.querySellerAccountRecords` | 分页查询**账户动账流水**（充值/结算入账/提现/扣款…） | `startTime`、`endTime`、`pageNum`、`pageSize` | 未给 |
| `get_expense_settlements` | `finance.pageQueryExpense` | 分页查询**其他服务款**结算明细（薯券/快递费/赔付…） | `startTime`、`endTime`、`pageNum`、`pageSize` | 单次 ≤ 一天 |
| `get_monthly_statement_url` | `bill.downloadStatement` | 查询**月度结算单下载地址** | `month`（`yyyy-MM`） | `downloadUrl` **2 小时有效** |

（第 5 个 `bill.queryCpsSettle` 是"带货达人侧详情查询"，与商家账单不同语义，未暴露。）

**决策理由**：不选"定一个主用途"，因为三个 `finance.*` 的分页字段名、时间语义、枚举维度
各不相同（例如 `settleBizType` vs `baseBizType` vs `tradeTypes`），合成一个工具必然要发明
一个官方不存在的统一过滤器 —— 那正是旧实现 `bill_type` 的病根。

⚠️ 分页字段名不统一，别混：`order.*` / `product.*` / `afterSale.*` 用 **`pageNo`**，
`finance.*` 用 **`pageNum`**。均为官方明文（O3）。

### 5.3 删除的 4 个工具（平台不提供，改名救不了）

| 删除的工具 | 平台实际情况 | 类别 | 出处 |
|---|---|---|---|
| `get_review_list`（评价列表） | 106 个 method 全量 grep `review\|comment\|rate\|evaluat`：**0 命中**。商品评价不在电商开放平台范围 | 官方明文 | O1+O2 全量清单 |
| `list_promotions`（营销活动列表） | 11 个分组里**没有** promotion / marketing / activity 域 | 官方明文 | O1 |
| `list_coupons`（优惠券列表） | `order.couponList` 是**虚拟卡券商品的履约券码查询**（需带 orderId、返回卡号/卡密），与"店铺优惠券模板列表"语义完全不同 | 官方明文 | O2 nav=15 + O3 |
| `get_shop_info`（店铺信息） | 无任何店铺名称/类目/评分接口；最接近的 `common.getSellerKeyInfo`（"获取老版本商家授权信息"）只返回 sellerId + appKey | 官方明文 | O2 nav=14 + O3 |

删除而不是留一个报错的桩：一个存在的工具名会被模型当成可用能力去调用。
`servers/xiaohongshu/tests/test_xiaohongshu.py::test_platform_unsupported_tools_are_gone` 钉住。

## 6. `order.getOrderList` 的时间窗与翻页约束（实现要点二）

全部官方明文，出处 O3 apiId=27241（`timeType` 字段描述与 `pageNo`/`pageSize`/`maxPageNo` 描述）：

| 约束 | 内容 |
|---|---|
| `timeType=1`（创建时间） | `endTime - startTime` **≤ 24 小时** |
| `timeType=2`（更新时间） | `endTime - startTime` **≤ 30 分钟**，且**「倒序拉取 最后一页到第一页」** |
| `maxPageNo` | 响应字段，描述「最大页码数 方便 直接从最后一页拉数据」 |
| `pageNo` | 默认 1，**限制 100** |
| `pageSize` | 默认 50，**限制 100** |
| ⇒ 单窗口容量 | **10000 单**上限（100×100）。窗口内更多时只能缩小时间窗，翻页救不了 |

**为什么必须倒着翻**：`timeType=2` 按更新时间排序，翻页期间订单被更新会在结果集里前移，
顺序翻页（1→maxPageNo）会让未读记录跳到已读页码之前 ⇒ **增量同步漏单**。官方给 `maxPageNo`
就是为此。代码在 `get_order_list` 的 docstring 里逐条写出，并对时间窗/分页上限做入参校验
（越界直接抛 `ValueError`，不发请求）。

`afterSale.listAfterSaleInfos` 有形似但不同的一组约束（官方明文，O3 apiId=30115）：
`orderId` 与 `timeType` **至少传一个**；`timeType=1` ≤24h / `timeType=2` ≤30min；
`0 < pageSize ≤ 100` 且 **`pageNo * pageSize ≤ 50000`**；入参时间是**毫秒**。

## 7. 商品粒度决策（ITEM vs SKU）

官方商品分组同时提供两个列表接口：

| method | 官方标题 | 粒度 | required |
|---|---|---|---|
| `product.searchItemList` | 查询Item列表 | **ITEM** | `pageNo`、`pageSize`、`searchParam` |
| `product.getDetailSkuList` | 商品列表完整版 | **SKU** | 无（全部可选，支持 `stockGte`/`stockLte`/`barcode`/`updateTimeFrom` 等过滤） |

**本 server 选 ITEM 粒度的 `product.searchItemList`**，理由：

1. **ID 空间与详情工具一致**：`get_product_detail` 用官方 `product.getItemInfo`（required `itemId`）。
   `getDetailSkuList` 返回的是 skuId，喂不进 `getItemInfo`，列表→详情串不起来。
2. **不与库存工具重复**：SKU 级库存已由 `get_inventory`（`inventory.getSkuStockV2`，required
   `skuId`）覆盖，商品列表再返回 SKU 库存是同一事实的第二份来源。
3. **分页契约确定**：`searchItemList` 的 `pageNo`/`pageSize` 是官方 required，翻页语义无歧义。

代价与补偿：按库存/条码/更新时间筛 SKU 的场景本 server 暂不覆盖，官方对应接口是
`product.getDetailSkuList`，已在 `get_product_list` 的 docstring 与本节记录，后续如需补
按此 method 新增工具即可（gatewayId 103/1661，apiId 27228）。

**已知官方文档笔误（推断）**：`product.getItemInfo` 的参数表把 `pageSize` 的描述写成
「当前页码」、`pageNo` 的描述写成「页码大小」，两条互换。本实现按字段名的通行语义传参
（`pageNo`=页码、`pageSize`=页大小），**标为待真机回归**。

## 8. 收件人信息 / 数据脱敏（只读分析的正确路径）

| 项 | 结论 | 类别 | 出处 |
|---|---|---|---|
| `order.getOrderDetail` 的 `receiverName`/`receiverPhone`/`receiverAddress` | 官方标注「**暂不返回** 详情通过getOrderReceiverInfo获取」 | 官方明文 | O3 apiId=27242 |
| `order.getOrderReceiverInfo` | 出参 `receiverInfos` 描述逐字：「收件人信息列表。**只有订单处于待发货状态下才会返回！！！**」；入参 required 为 `receiverQueries`（数组）+ `isReturn`（是否换货单）；官方另注「请务必在发货前调用一次避免用户修改导致不一致」 | 官方明文 | O3 apiId=27240 |
| `data.batchDecrypt`（批量解密） | 入参 `baseInfos` 描述逐字：「加密数据列表，上限100条。**店铺单日限额10次**，根据订单号隔离，重复的订单号视为1次」；required `baseInfos`/`actionType`/`appUserId` | 官方明文 | O3 apiId=29208 |
| `data.batchDesensitise`（批量脱敏） | 官方描述**逐字包含同一句「店铺单日限额10次」** ⇒ **无法确认脱敏接口不受该限额约束**，**标为待官方澄清** | 官方明文（句子本身）+ 待澄清（适用范围） | O3 apiId=29207。**加重证据**：两个接口的 `baseInfos` 指向**同一个 schema**（`$$ref: #/components/schemas/1757910`，`name: baseInfo`），那句限额写在这个被复用的 schema 描述里 —— 所以它既可能是真约束，也可能只是 schema 复用带来的文案外溢。二者都不能从文档判定 |
| `data.batchIndex`（批量获取索引串） | 入参 `indexBaseInfoList[{plainText, type}]`，`type` 1 地址 / 2 姓名 / 3 电话 / 4 身份证号 / 5 身份证照片链接；**不解密即可做匹配** | 官方明文 | O3 apiId=29206 |

**只读分析的正确路径**（本 server 的立场）：

1. 优先用 `order.getOrderList` / `order.getOrderDetail` **已明文返回的**
   `receiverProvinceName` / `receiverCityName` / `receiverDistrictName`（及对应 Id）做地域分析
   —— 这些字段不是密文、不消耗任何限额；
2. 需要"同一个人/同一地址"的关联匹配时用 `data.batchIndex`（索引串，不解密）；
3. **本 server 不暴露 `data.batchDecrypt` / `data.batchDesensitise` 工具**：单日 10 次的店铺级
   限额下，把解密做成模型可随手调用的工具会在几次对话内耗尽商家全天额度，且脱敏接口是否同受
   限额**未经官方澄清**。需要明文的场景应由业务侧显式实现并自行核算配额。

## 9. 未解决项汇总（按 spec §8，不得用推测填充）

| # | 项 | 状态 | 处理方式 |
|---|---|---|---|
| 1 | `data.batchDesensitise` 是否同受「店铺单日限额10次」 | 官方描述与 `batchDecrypt` 共用 schema，逐字含同一句 | **待官方澄清**；不暴露该工具 |
| 2 | 165/2804 族那层 `{code,msg,success,data}` 是接口自带还是文档把网关信封画了进去 | 官方无明文 | 实现兼容两种读法（存在则再解一层，`code`/`error_code` 都接受），**待真机回归** |
| 3 | 官方错误码表 | `GET /api/doc/errorcodeNew` 返回 `[]`；`-2000400`/`-2000101` 在公开文档语料 0 命中 | 只记录来源为 mission 审计语料，**标为待复核**；代码不硬编码错误码语义 |
| 4 | `product.getItemInfo` 的 `pageNo`/`pageSize` 描述互换 | 官方自相矛盾 | 按字段名语义实现，**待真机回归** |
| 5 | `inventory.getSkuStockV2` 的 `inventoryType` 枚举 | 官方只写「库存类型」，无枚举值 | 默认**不发送**该字段，不替官方猜默认值 |
| 6 | `afterSale.getAfterSaleInfo` 的 `requestHeader.requestFrom` 语义 | 官方描述为空（字面 `//`） | **不发送**（官方 required 为空） |
| 7 | `order.getOrderList` 入参 `startTime`/`endTime` 的单位 | 官方描述未写单位 | 按 example 的 10 位值取**秒**（推断，强），docstring 明示 |
| 8 | 真机回归 | 本 WP 无商家凭证 | 全部结论基于官方文档与官方机器可读 spec；验收标准为"符合官方文档"（spec §1） |

## 10. 不在本 WP 范围内的相邻事实（记录以免后人重复踩）

* **消息推送 webhook 验签规则完全不同**（kebab-case `app-key`、待签串含 URL path），
  见 O5 docDetailId=41「应用消息推送」。本 server 不含 webhook 接收端，未实现。
* 官方还有 `即时零售API` / `会员通API` / `供货商API` / `素材中心API` 四个分组（O1），
  与本 server 的只读商家数据定位无关，未纳入。
* `warehouse.*` 与 `express.*` 属第三个网关版本族 **278 / 6249**（O2 nav=18/20）。本 server
  未用到，但说明"两族"不是全平台的全部 —— 新增 method 时**必须查 O2 的 gatewayId/gatewayVersionId**。
