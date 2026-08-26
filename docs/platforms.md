# Chinese E-Commerce Platform Comparison

> **本文的口径纪律。** 这个文件一度记载的是"我们以为的"契约，而不是官方契约 —— 端点、
> 签名算法、能力矩阵都有成片的错误。经完整审计（8 个平台 115 个 endpoint 逐个与官方文档
> 清单比对）后，本文改为：**「官方契约」列写官方文档说的，「实现状态」列写我们的代码目前
> 是否符合。** 两者不一致时，不许只写一个。
>
> 审计结论的权威出处：`kitty-specs/api-contract-conformance-01M0ZHQN/spec.md` §2；
> 五个已修平台的逐项契约声明在 `docs/api-contracts/<platform>.md`（每条标注官方出处 URL，
> 并区分「官方明文」与「依据充分的推断」）；三个待重建平台的研究成果在
> `kitty-specs/api-contract-conformance-01M0ZHQN/deferred/`。

## Platform Overview

| 平台 | 开放平台地址 | 官方 API 端点 | 凭证传递 | 官方签名方法 | 实现状态 |
|---|---|---|---|---|---|
| 淘宝 | [open.taobao.com](https://open.taobao.com) | `gw.api.taobao.com/router/rest`（主接入文档；`eco.taobao.com/router/rest` 保留兼容） | 参数 `session` | **MD5**（官方 `md5`/`hmac`/`hmac-sha256` 三种并列合法，我们实现 `md5`） | ✅ 已按官方契约修正 |
| 拼多多 | [open.pinduoduo.com](https://open.pinduoduo.com) | `gw-api.pinduoduo.com/api/router` | 参数 `access_token` | MD5 | ✅ 已按官方契约修正 |
| 快手 | [open.kwaixiaodian.com](https://open.kwaixiaodian.com) | `openapi.kwaixiaodian.com` | 参数 `access_token` | MD5（默认）/ HMAC_SHA256；**密钥是独立的 `signSecret`，不是 `appSecret`** | ✅ 已按官方契约重建 |
| 小红书 | [open.xiaohongshu.com](https://open.xiaohongshu.com) | `ark.xiaohongshu.com/ark/open_api/v3/common_controller`（**单一网关**，只 POST） | body `accessToken` | MD5（**仅 4 个系统参数入签**） | ✅ 已按官方契约重写 |
| 微信小店 | [developers.weixin.qq.com](https://developers.weixin.qq.com) | `api.weixin.qq.com` | query `access_token` | **无逐请求签名**（推断，官方从未明文） | ✅ 已按官方契约修正 |
| 巨量引擎 | [open.oceanengine.com](https://open.oceanengine.com) | `api.oceanengine.com/open_api/`（v3.0 全部如此；v2 官方 `ad.`/`api.` 混用且零说明） | **HTTP header `Access-Token`** | **完全不签名**（公共参数无 `sign`/`sign_method`/`app_key`/`timestamp`） | ⛔ 契约不符 + 18 个 endpoint 仅 2 个存在 → 工具已下架 16 个，重建另立 mission |
| 抖店 | [op.jinritemai.com](https://op.jinritemai.com) | `openapi-fxg.jinritemai.com` | query `access_token` | **HMAC-SHA256**，且必须显式传 `sign_method=hmac-sha256`（不传则服务端按 md5 验签） | ⛔ 契约不符 + 20 个 endpoint 全不可用 → 平台工具已全部下架，重建另立 mission |
| 京东 | [jos.jd.com](https://jos.jd.com) | `api.jd.com/routerjson`（官方标注「**历史接口，逐步迁移至 SP-API**」）；`api-cn.jd.com` 的 SP-API 为官方推荐 | routerjson：参数 `access_token`；SP-API：header `X-JOS-Access-Token` | **MD5**（不是 HMAC-MD5）：`UPPER(MD5(secret + Σ(name+value) + secret))` | ⛔ 契约不符 + `jd.pop.*` 命名空间不存在 → 平台工具已全部下架，重建另立 mission |

## Auth Mechanisms

| 平台 | Auth Type | Token Source | Token Refresh | Notes |
|---|---|---|---|---|
| 淘宝 | OAuth 2.0 (Authorization Code) | `/token` | Refresh token（48h 有效、30d 刷新窗口） | 凭证参数名是 **`session`**，TOP 公共参数表里**没有** `access_token`。「订单信息查询」权限包仅开放给 20 种特定应用类型，通用 MCP 连接器不在其中 |
| 拼多多 | OAuth 2.0 (Authorization Code) | `/oauth2/access_token` | Refresh token | 环境变量是 `client_id`/`client_secret` 命名。`pdd.open.decrypt.batch` 云外调用自 2026-05-12 起限 1 次/10 秒 + 单应用单日 100 次 |
| 快手 | OAuth 2.0 (Authorization Code) | `/oauth2/access_token` | Refresh token | **两个凭证**：`appSecret` 只用于 OAuth 换 token，请求签名用独立的 `signSecret`；`signSecret` 绝不作为请求参数发出 |
| 小红书 | OAuth 2.0 (Authorization Code) | Token via authorization callback | Refresh token | `accessToken` 走 POST body 且**不参与签名**（官方两处明文） |
| 微信小店 | AppID + AppSecret（非标准 OAuth） | `POST /cgi-bin/stable_token` | 同一接口按 `expires_in` 重取 | 与 `/cgi-bin/token` 的凭证**互相隔离**，不能共用缓存槽。IP 白名单未匹配返回 **HTTP 403 且不带 `errcode`** |
| 巨量引擎 | OAuth 2.0 (Authorization Code) | `POST https://api.oceanengine.com/open_api/oauth2/access_token/` | refresh_token **一次性轮转**，刷新后原 token 失效 | 有效期须读运行时 `expires_in`，**不要硬编码**（官方正文写 30 天、返回示例写 7 天，自相矛盾）。资质要求为企业认证 + 企业打款认证 |
| 抖店 | App Key + App Secret | 开发者后台手工获取 | N/A | 无 OAuth 流；多个「最近似替代」接口处于 `status=3`（定向开放），需联系行业小二加白 |
| 京东 | OAuth 2.0 (Authorization Code) | `/oauth2/access_token` | Refresh token | routerjson 与 SP-API 鉴权完全不同：SP-API 凭证走 `X-JOS-*` header，且 **header 名本身参与签名串** |

## Signing Methods

以下是**官方**算法。三个待重建平台（巨量 / 抖店 / 京东）的现有实现与此不符，差异见「实现状态」列。

| 平台 | Sign Method | 官方算法 | 待签串构造 | timestamp |
|---|---|---|---|---|
| 淘宝 | MD5 | `UPPER(MD5(secret + Σ(key+value) + secret))` | 除 `sign` 外**全部**参数入签（含 `sign_method`、`format`），key 按 ASCII 码位升序，无分隔符 | `yyyy-MM-dd HH:mm:ss`，GMT+8 显式固定，容差 10 分钟 |
| 拼多多 | MD5 | `UPPER(MD5(client_secret + Σ(key+value) + client_secret))` | 公共 + 业务参数全部入签，无分隔符。**`sign_method` 不是拼多多的参数，不得发送** | UNIX **秒**，容差 10 分钟 |
| 快手 | MD5 / HMAC_SHA256 | `lower(md5(k=v&…&signSecret=<signSecret>))`；HMAC_SHA256 分支产出 **Base64 而非 hex** | `k=v` 用 `&` 连接、末尾追加字面量 `&signSecret=…`（**不是首尾包裹**）；先算签名再 URL encode | epoch **毫秒** |
| 小红书 | MD5 | `lower(md5(method + "?" + "appId=..&timestamp=..&version=.." + appSecret))` | **只有 4 个系统参数入签**；`accessToken` 与全部业务参数**不参与**；`method` 在 `?` 之前且不参与排序 | UNIX **秒**（出参时间字段是毫秒，别混） |
| 微信小店 | 无 | — | 无逐请求签名（**推断**：三类接口页参数表穷举后无 `sign`/`sign_method`/`timestamp`/`nonce`） | — |
| 巨量引擎 | **无** | — | 官方公共参数表里没有 `sign`/`sign_method`/`app_key`/`timestamp`，凭证走 header `Access-Token` | — |
| 抖店 | HMAC-SHA256 | `hash_hmac("sha256", secret + "app_key"+ak + "method"+m + "param_json"+pj + "timestamp"+ts + "v"+v + secret, app_secret)` —— 消息体**前后仍包裹 secret**，同时 secret 又作 HMAC key | 业务参数放 `param_json`（compact、递归 key 有序、数值不带多余小数点、禁 HTML escape） | Unix **秒**（官方注解裁决：datetime 格式「支持但不推荐」） |
| 京东 | MD5 | `UPPER(MD5(appSecret + Σ(name+value, ASCII升序) + appSecret))` | 业务参数放 `360buy_param_json` 且**参与签名**（因 `3` 开头排最前）；`format` 与 `sign_method` **不参与** | `yyyy-MM-dd HH:mm:ss`（可带 `.SSSZ`），容差 **6 分钟**，须显式带 `+0800` |

**跨平台约束：签名参与集合必须恒等于发送集合减去 `sign`。** 基类此前的结构性缺陷是二者不
一致（`sign_method` 全平台发而不签）。`tests/contract/` 下每个平台的 wire 断言都覆盖这一点。

## API Capability Matrix

**这张表记的是「本仓库当前对外暴露的工具」，不是「平台理论上有的能力」。**
`--` = 不暴露；`⛔` = 曾经声明过但已按 FR-015 下架（原因见下节）。

| 平台 | 订单查询 | 商品管理 | 售后/退款 | 物流查询 | 库存管理 | 财务/账单 | 评价 | 推广/优惠券 | 店铺管理 | 广告报表 |
|---|---|---|---|---|---|---|---|---|---|---|
| 淘宝 | Yes | Yes | Yes | Yes | -- | -- | Yes | Yes | Yes | -- |
| 拼多多 | Yes | Yes | Yes | Yes | -- | -- | ⛔ | Yes | Yes | -- |
| 快手 | Yes | Yes | Yes | ⛔ | -- | -- | Yes | ⛔ / 券 Yes | Yes | -- |
| 小红书 | Yes | Yes | Yes | Yes | Yes | Yes | ⛔ | ⛔ | ⛔ | -- |
| 微信小店 | Yes | Yes | Yes | Yes | -- | -- | -- | Yes | Yes | -- |
| 巨量引擎 | -- | -- | -- | -- | -- | 余额 Yes | -- | ⛔ | 账户信息 Yes | ⛔ |
| 抖店 | ⛔ | ⛔ | ⛔ | ⛔ | -- | ⛔ | ⛔ | ⛔ | ⛔ | -- |
| 京东 | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | -- | ⛔ | ⛔ | ⛔ | -- |

抖店与京东当前**只暴露 4 个通用运维工具**（`get_metrics` / `get_traces` / `get_alerts` /
`export_data`）—— 它们由 `register_common_tools()` 注册，不依赖任何平台 endpoint，因此不受
FR-015 影响。巨量引擎另暴露 2 个真实存在的 endpoint。

---

# 下架工具清单（FR-015）

FR-015 的要求是：**移除指向不存在 endpoint 的工具，并记录每一个的原因。** 一个"存在但会
报错"的工具名会被模型当作可用能力去调用，因此让它继续注册就是继续对外说谎。

## 处理方式：取消注册，不删函数

对每个被下架的工具，我们**移除其 `@mcp.tool()` / `@server.tool()` 装饰器**，函数体与
docstring 原样保留，并在函数上方留一行 `# 下架（FR-015）：…` 注释说明原因与官方替代。

- **不删**：函数体记录了当初想要的业务语义（分页范式、字段裁剪、错误兜底），是按真实接口
  重建时的意图记录；删掉就得从头猜。
- **不注册**：MCP server 不再对外暴露它，虚假的能力声明**立即**停止 —— 不必等重建完成。
- 每个平台的测试都把这件事钉成了负向断言（`TestFR015Unregistration`），任何把它们重新
  注册的改动都会先撞红测试。

## 原因分类

| 标注 | 含义 | 可否靠改名修复 |
|---|---|---|
| **已下线** | 接口曾经存在，官方已公告下线（附公告日期） | 不能，须迁移到替代接口 |
| **查无此接口** | 在官方文档全量清单中零命中 —— 从未存在（编造） | 能，改成正确的官方名即可 |
| **平台不对三方开放** | 能力本身平台不提供给三方应用 | **不能**，只能申请定向开放或放弃 |

审计方法论（为何不能用活体探测判存在性）见 spec.md §2.3.1：巨量已下线路由仍返回
`40105 access_token无效` 而非 404；淘宝 `getApiParamList` 对 2018 年就下线的接口仍返回
参数；京东目录对「已下线」与「从未存在」返回同一个 `API不存在`。唯一可靠判据是
「官方文档清单」+「官方公告语料」双重比对。

---

## 巨量引擎 — 下架 16 个，保留 2 个

`servers/oceanengine/server.py`。18 个 endpoint 里只有 2 个真实存在且在维护。
研究成果与替代映射：`deferred/WP03-巨量引擎-鉴权与信封.md`。

### 保留注册的 2 个

| 工具 | endpoint | 备注 |
|---|---|---|
| `get_advertiser_info` | `2/advertiser/info/` | 存在且在维护 |
| `get_account_balance` | `2/advertiser/fund/get/` | 存在且在维护。⚠️ 官方已公告自 **2026 年 6 月中上旬**起不再接受旧工作台的 `bp_id` 参数（changelog `1862437581755404`）—— 已核对：本实现只发 `advertiser_id`，从未发过 `bp_id`，无需改动；重建时也不要加回来 |

### 已下线 —— 2024-05-06 官方下线（5 个）

官方下线公告本身**未指定替代**（41 条 path 的替代栏均为 `-`）。下表的替代依据官方
《升级版与原版差异说明》 `labels/7/docs/1758611573659724`：原版五层结构变四层，
「计划组」对标「项目」、「营销创意」对标「营销」、「营销计划」拆分至两者。

| 工具 | 原 endpoint | 已验证的官方替代 |
|---|---|---|
| `list_campaigns` | `2/campaign/get/` | `v3.0/project/list/`（原版「计划组」= 升级版「项目」） |
| `list_ads` | `2/ad/get/` | **无 1:1 替代**：需 join `v3.0/project/list/` + `v3.0/promotion/list/`（预算/出价/定向分散在两层）。注意该接口实为**广告计划**列表，代码 docstring 标错成「广告创意列表」 |
| `get_ad_detail_report` | `2/report/ad/get/` | `v3.0/report/custom/get/` |
| `get_audience_report` | `2/report/audience/` | `v3.0/report/custom/get/`（原接口整组下线） |
| `get_creative_report` | `2/report/creative/get/` | `v3.0/report/custom/get/` |

### 已下线 —— 2025-08-31 官方下线（1 个）

| 工具 | 原 endpoint | 已验证的官方替代 |
|---|---|---|
| `get_campaign_report` | `2/report/advertiser/get/` | `v3.0/report/custom/get/`，配 `v3.0/report/custom/config/get/` 查可用维度指标；大数据量走 `custom/async_task/{create,get,download}/` |

⚠️ 迁移到 `v3.0/report/custom/*` 时有两条官方已公告、需规避的字段变更：
`clue_connected_*`/`clue_count_all`/`clue_dialed_count` 已于 **2026-06-08** 移除，带这些
字段的请求**会报错**（changelog `1863611317923907`）；
`in_app_order_net_refund_pay_amount_fen` → `stat_in_app_order_net_refund_pay_amount`，
**2026-08-27** 生效（changelog `1873393964685514`）。

### 查无此接口（10 个）

| 工具 | 原 endpoint | 已验证的最近似官方接口 |
|---|---|---|
| `get_ad_detail` | `2/ad/read/` | 官方零命中；最近似 `v3.0/promotion/list/` 配 `filtering.ids`（≤20 个） |
| `get_campaign_detail` | `2/campaign/read/` | 同上 |
| `list_audience_packages` | `2/dmp/audience/list/` | **`2/dmp/custom_audience/select/`**（人群包列表，`docs/1696710570721295`） |
| `list_materials` | `2/material/list/` | 按意图选：`2/file/material/list/`（素材**标签**列表）/ `2/file/video/get/`（视频素材）/ `v3.0/tools/ebp/material/list/`（组织级） |
| `get_qianchuan_campaign_list` | `2/qianchuan/campaign/list/get/` | **`v1.0/qianchuan/campaign_list/get/`** —— 千川用 **`v1.0`** 而非 `2`，文档 host 为 **`ad.oceanengine.com`**；`advertiser_id` 与 `filter` 均必填 |
| `get_qianchuan_report` | `2/qianchuan/report/ad/get/` | **`v1.0/qianchuan/report/ad/get/`** —— 同上；必填 `advertiser_id`/`start_date`/`end_date`/`fields[]`/`filtering`，≤180 天（DAILY 30 天 / HOURLY 7 天） |
| `get_star_report` | `2/star/report/` | **它是路径前缀，不是接口。** 真实接口在其下一级：`2/star/report/order_overview/get/`、`2/star/report/order_user_distribution/get/`、`2/star/report/custom_data_topic_report/` 等 |
| `list_star_tasks` | `2/star/task/list/` | `2/star/demand/list/`（星图客户任务列表）、`2/star/star_ad_unite_task/list/`、`v3.0/tools/ebp/star_task/list/` |
| `get_bid_suggestion` | `2/tools/bid_suggest/` | **`v3.0/tools/bids/suggest/`**（`docs/1771363823169544`）。⚠️ `2/tools/bid/suggest/`（斜杠形式）虽能探测通但**无官方文档**，不要用 |
| `get_diagnosis` | `2/tools/diagnosis/` | **它是路径前缀，不是接口。** 真实接口：`v3.0/tools/diagnosis/suggestion/get/`、`v3.0/tools/promotion_diagnosis/suggestion/get/`、`v3.0/tools/advertiser_diagnosis/suggestion/get/`、`v3.0/tools/project_diagnosis/suggestion/list/` |

**重建前须知**：官方 Java SDK 最新版（1.1.93，2026-08-12）**仍在发布** `ReportAdGetV2Api`
等已下线接口的类 —— **SDK 里有类 ≠ 接口还活着**。另：`ad.` 与 `api.` 的适用范围官方零说明
（1053 篇文档 + 246 篇日志均无），v3.0 全部是 `api.`，v2 两边混用（177 : 152）；「v2 走
`ad`、v3 走 `api`」这个流传的规则是**错的**。

---

## 抖店 — 下架 20 个（全部）

`servers/doudian/server.py`。判据：遍历官方 API 文档 69 个业务域目录、**1664 篇文档**
（去重 1652 个路径）全量比对 —— 20 个 endpoint 无一可用。研究成果与替代映射：
`deferred/WP06-抖店契约修正.md`。

抖店的编造形态是**成片的「域名幻觉」**：官方根本不存在这些一级路径段 ——
`/comment/`（全平台无评价接口）、`/coupon/`（真名是复数 `/coupons/`）、
`/finance/`（账单在 `/order/getSettleBill*`）、`/im/`（真名 `/pigeon/`）、
`/promotion/`（真名 `/marketing/`）、`/video/`（真名 `/shopVideo/`）。

### 已下线（3 个）

文档条目带 `status`（1 在线 / 3 定向开放需加白 / 0 已下线），另有**墓碑判定**：
`queryDocArticleDetail?articleId=<id>` 对已下线接口返回 `content` 长度 **0**。
我们那 3 个"存在"的全是 `status=0` 且正文长度 0。

| 工具 | 原 endpoint | 下线日期 | 已验证的官方替代 |
|---|---|---|---|
| `get_order_detail` | `order/detail` | 2021-08-30 | `/order/orderDetail` |
| `get_order_list` | `order/list` | 2021-08-30 | `/order/searchList` |
| `get_product_list` | `product/list` | 2022-01-20 | `/product/listV2` |

### 查无此接口，有官方替代（9 个）

| 工具 | 原 endpoint | 已验证的官方替代 |
|---|---|---|
| `get_refund_list` | `refund/listSearch` | `/afterSale/List`（真名 `/trade/refundListSearch` 亦已于 2022-01-20 下线） |
| `get_logistics_tracking` | `order/logisticsTrace` | `/order/queryOrderLogistics` |
| `list_logistics_companies` | `order/getLogisticsCompanyList` | `/order/logisticsCompanyList`（**无 `get` 前缀**）或 `/order/queryLogisticsCompanyList` |
| `list_promotions` | `promotion/list` | `/marketing/pageQueryActivity`（营销玩法）—— 无 `/promotion/` 域 |
| `list_coupons` | `coupon/list` | 卡券核销 `/coupons/list`（**复数**）；店铺券 `/marketing/queryShopCouponList` |
| `get_bill_list` | `finance/getBillList` | 结算账单 `/order/getSettleBillDetailV3`；资金流水 `/order/getShopAccountItem` —— 无 `/finance/` 域 |
| `get_shop_score` | `shop/getShopScore` | `/shop/reputation`（商家评分）或 `/shop/getExperienceScore`（体验分） |
| `list_categories` | `product/getCategoryList` | `/shop/getShopCategory`（店铺类目树）或 `/product/getCategories` |
| `list_brands` | `product/getBrandList` | `/brand/list`（按类目取可选品牌） |

规律性错误两条，重建时对照检查：**多加 `get` 前缀**；**按「业务语义 = 路径首段」归属**
（抖店实际不遵守该规律）。另：路径**无版本段**，版本通过接口名后缀表达（`listV2`、
`getSettleBillDetailV3`）；公共参数 `v` 恒为 `2`（协议版本，与业务版本无关）。

### 平台不对三方开放（8 个）

**改名无法修复。** 这一类必须与上面 9 个区分对待 —— 重建 mission 拿不到能力，只能申请
定向开放或放弃该工具。

| 工具 | 原 endpoint | 平台实际情况 | 可否申请定向开放 |
|---|---|---|---|
| `get_review_list` | `comment/list` | 抖店没有 `/comment/` 域，**全平台无评价列表接口**；仅 `/product/commentCounter` 提供计数，且属二方权限组 | ❌ 不可 |
| `get_review_detail` | `comment/detail` | 同上，无评价详情接口 | ❌ 不可 |
| `get_live_data` | `live/getLiveRoomData` | `/live/` 下仅 2 个接口，均 `status=3` | ⚠️ 需联系行业小二加白 |
| `list_live_rooms` | `live/getLiveRoomList` | 同上 | ⚠️ 需联系行业小二加白 |
| `get_shop_info` | `shop/basicInfo` | 主站无「店铺基础信息」接口，仅 `/shop/status`（店铺状态）与 `/open/getAuthInfo`（授权信息） | ❌ 无等价能力 |
| `get_traffic_data` | `shop/getTrafficData` | 罗盘 API 目录**只有 1 篇** `/compass/getProductSaleData` | ⚠️ 需加白，且不是店铺流量 |
| `get_short_video_data` | `video/getVideoData` | 无 `/video/` 域（真实域是 `/shopVideo/*`），且无短视频数据接口 | ❌ 无等价能力 |
| `get_feige_messages` | `im/getMessageList` | 无 `/im/` 域，真名 `/pigeon/messageList`，`status=3` | ⚠️ 需联系行业小二加白 |

---

## 京东 — 下架 15 个（全部）

`servers/jd/server.py`。判据：从官方文档后端拉取覆盖三个网关的**完整目录 3514 个 API**，
做前缀直方图与逐个存在性验证。研究成果与替代映射：`deferred/WP08-京东契约修正.md`。

### 根因：`jd.pop.*` 命名空间不存在

| 前缀 | 官方 API 数量 | 说明 |
|---|---|---|
| `jingdong.` | **3147** | 全部商家 / POP / VC 接口（1.0 网关） |
| `jd.union.open.` | 90 | **仅**京东联盟 CPS |
| `jd.pop.` | **0** | 不存在 |
| 无点分裸名（`listOrders` 等） | ~277 | SP-API |

`jd.` 是真前缀，但**只属于京东联盟** —— 几乎可确定是污染源：从
`jd.union.open.order.query` 推断出 `jd.<域>.<资源>.<动作>` 语法后生成了 `jd.pop.*`。

**注意**：京东目录**无法区分「已下线」与「从未存在」**（都返回 `API不存在`），
`apiStatus` 100% 为 1、`apiSuspend`/`apiState` 100% 为 null，退役接口是直接删除。京东标注
废弃的方式是**写在中文名里**（如「【推下线】…【请切换到 jingdong.ware.stock.sku.set
接口】」，共 30 条），可机读。

### ⚠️ 重建前必须先决定网关方向

官方《开放平台API对接指南》明文把 `https://api.jd.com/routerjson` 标为
「**历史接口，逐步迁移至 SP-API**」，而 `https://api-cn.jd.com` 的 SP-API 标为
「新一代标准化接口（**推荐使用**）」（19 组约 277 个 endpoint），POP 所需能力已全覆盖
（订单列表/详情、物流轨迹、商品/SKU/库存、售后、店铺信息）。

**两者鉴权完全不同**：SP-API 凭证走 header（`X-JOS-App-Key`、`X-JOS-Access-Token`、
`X-JOS-Timestamp` 为 epoch **毫秒**、`X-JOS-Sign`），签名
`upper(md5(secret + sorted_kv + secret))`，且 **header 名本身参与签名串**。

→ **在决定网关之前不要动手。** 若选 SP-API，下表的 `jingdong.*` method 名与 routerjson 的
契约细节（签名向量等）全部作废；若选 routerjson，等于在官方标注的历史接口上重建。

### 查无此接口，有官方正确名（11 个）

| 工具 | 原 method（编造） | 官方正确 method | 权限等级 |
|---|---|---|---|
| `get_order_list` | `jd.pop.order.search` | `jingdong.pop.order.search`（apiId 4246, group 55, 2026-08-18 更新） | R3 |
| `get_order_detail` | `jd.pop.order.get` | `jingdong.pop.order.get`（2026-08-18 更新） | R3 |
| `get_product_list` | `jd.pop.ware.search` | `jingdong.ware.read.searchWare4Valid` | — |
| `get_shop_info` | `jd.pop.shop.get` | `jingdong.vender.shop.query` | R1 |
| `get_after_sale_list` | `jd.pop.afs.search` | `jingdong.ServiceInfoProvider.queryServicePageSafe` 或 `jingdong.afsservice.alltask.get` | R1 |
| `get_after_sale_detail` | `jd.pop.afs.get` | `jingdong.ServiceDetailProvider.findServiceDetail` | R1 |
| `get_review_list` | `jd.pop.comment.search` | `jingdong.pop.PopCommentJsfService.getVenderCommentsForJos` | R1 |
| `get_inventory` | `jd.pop.inventory.get` | `jingdong.ware.stock.sku.query` | R1 |
| `list_promotions` | `jd.pop.promotion.search` | `jingdong.seller.promotion.list` | R1 |
| `list_coupons` | `jd.pop.coupon.search` | `jingdong.seller.coupon.read.getCouponList` | R1 |
| `list_categories` | `jd.pop.category.search` | `jingdong.category.read.findByPId`（其 `pid` 对应我们的 `parent_id`） | — |

### 查无此接口，且京东无官方等价能力（4 个）

**改名无法修复。**

| 工具 | 原 method（编造） | 平台实际情况 |
|---|---|---|
| `get_shop_score` | `jd.pop.shop.score.get` | 3514 个官方 API 中 DSR / 店铺评分 / 口碑 / 服务分**零命中** |
| `get_review_detail` | `jd.pop.comment.get` | 评价类 API 仅 6 个，均无单条评价详情 |
| `get_price_info` | `jd.pop.price.get` | 没有 POP 实时售价读接口；价格随 `jingdong.ware.read.findWareById` 一并返回 |
| `get_logistics_tracking` | `jd.pop.logistics.trace` | 无订单级等价接口；`jingdong.ldop.receive.trace.get` 需**青龙业主号 + 运单号**，不是订单号入口 |

---

## 已修平台在本 mission 中删除的工具（FR-015 完整台账）

五个已修平台在各自 WP 中**直接删除**了平台不提供的工具（而非取消注册）—— 那些平台的
server 已按官方契约重写，保留死函数只会与新结构冲突。逐项理由见各自的契约声明文档。

| 平台 | 删除的工具 | 原因 | 出处 |
|---|---|---|---|
| 小红书 | `get_review_list`、`list_promotions`、`list_coupons`、`get_shop_info` | 平台不提供该 4 个能力（官方 106 个 method / 11 个分组全量比对） | `docs/api-contracts/xiaohongshu.md` |
| 快手 | `get_logistics_tracking` | 物流 API 14 个 + 快递 API 9 个全部核对：**只有物流商向快手「推」轨迹的写接口**，方向与读取需求相反 | `docs/api-contracts/kuaishou.md` §1.3 |
| 快手 | `list_logistics_companies` | **不是 API，而是一份静态文档表**《物流公司编号》 | 同上 |
| 快手 | `list_promotions` | 营销 API 共 14 个，只覆盖 coupon 与人群包，无「营销活动列表」能力 | 同上 |
| 拼多多 | `search_products` | 平台无全站商品搜索能力 | `docs/api-contracts/pinduoduo.md` |
| 拼多多 | `get_review_list` | 平台无商品评价读取能力 | 同上 |
| 拼多多 | `search_affiliate_goods` | **不是不存在，是移出**：`pdd.ddk.goods.search` 属多多进宝联盟体系，需独立开发者身份与应用类型，商家 ISV 授权拿到的 `access_token` 取不到该权限 | 同上 |
| 淘宝 | （无删除） | 2 个已下线 endpoint 有指定替代，改名即可：`taobao.item.get`→`item.seller.get`、`taobao.shop.get`→`shop.seller.get` | `docs/api-contracts/taobao.md` §1 |
| 微信小店 | （无删除） | 5 个不存在的路径均取得字段级官方替代；订单物流改用 `order/get` 内嵌 `delivery_info` | `docs/api-contracts/weixin_store.md` |

## 工具数对照（`scripts/smoke_install.py::EXPECTED_TOOLS` 的权威口径）

每个数字含 `register_common_tools()` 注册的 4 个通用运维工具。该表与 `EXPECTED_TOOLS`
必须一致 —— install-smoke 会实测 `list_tools()` 并比对，漂移即失败。

| 平台 | 平台工具 | 通用运维工具 | 合计 |
|---|---|---|---|
| 淘宝 | 13 | 4 | 17 |
| 拼多多 | 10 | 4 | 14 |
| 快手 | 9 | 4 | 13 |
| 小红书 | 12 | 4 | 16 |
| 微信小店 | 11 | 4 | 15 |
| 巨量引擎 | **2** | 4 | **6** |
| 抖店 | **0** | 4 | **4** |
| 京东 | **0** | 4 | **4** |

---

## Phase Roadmap

原路线图（Phase 1 = 巨量/抖店/京东）已与事实脱节：这三个平台的 endpoint 存在率分别是
2/18、0/20、0/15，实际上是**最未完成**的三个，而非"基础"。修正后的状态：

### 已按官方文档符合性验收（契约声明 + wire 断言齐备）
- **淘宝** — 订单/商品/售后/物流/评价/推广/店铺
- **拼多多** — 订单/商品/售后/物流/推广/店铺
- **快手** — 订单/商品/售后/评价/优惠券/店铺
- **小红书** — 订单/商品/售后/物流/库存/财务
- **微信小店** — 订单/商品/售后/物流/优惠券/店铺/类目

### 待按真实接口重建（另立 mission；工具已下架，不再对外声明）
- **巨量引擎** — 需按 v3.0 `project/list` + `promotion/list` + `report/custom/get` 重建；
  原版「广告计划」无 1:1 替代，需 join 两个接口。当前保留 2 个真实 endpoint
- **抖店** — 20 个 endpoint 全需重写路径；其中 8 个能力平台不对三方开放；12 个替代接口
  的请求/响应字段契约尚未调研（本轮只做到路径级）
- **京东** — **先决定网关方向**（routerjson 历史接口 vs SP-API 推荐且鉴权完全不同），
  再重建 11 个 `jingdong.*`；4 个能力无官方等价

## Common Patterns

**"所有中国电商平台的系统参数长一个样"这个假设是错的** —— 它是本仓库契约层缺陷的根因。
`shared/cn_commerce_base.py` 曾统一发 `access_token` 参数、统一发 epoch 毫秒 `timestamp`、
统一附带 `sign` + `sign_method`、统一按 `error_response` 判错。该假设恰好只对拼多多成立。
反例：淘宝的凭证参数名是 `session`；巨量的凭证走 HTTP header 且**完全不签名**；微信小店
**没有签名**；快手用独立的 `signSecret` 且待签串是 `k=v&…` 形态；小红书只签 4 个系统参数。

因此每个平台 server 的正确做法是：

1. 设 `BASE_URL`，并按该平台的官方契约决定**参数位置**（query / form body / JSON body / header）
2. 按官方参数表构造系统参数 —— **参数名逐字照抄官方**，不要按其他平台的习惯猜
3. 覆写 `_sign()`（或声明无签名），并保证**签名参与集合恒等于发送集合减去 `sign`**
4. 按官方**判错字段**解包（`code`/`errcode`/`error_response`/`error_code` 各不相同），
   认不出的信封要 fail-closed 抛错，**绝不把错误信封当业务数据返回给模型**
5. 在 `docs/api-contracts/<platform>.md` 写下契约声明，逐项标注官方出处 URL，并区分
   「官方明文」与「依据充分的推断」；在 `tests/contract/test_wire_<platform>.py` 加 wire
   层断言（参数名集合、传输位置、timestamp 格式）
