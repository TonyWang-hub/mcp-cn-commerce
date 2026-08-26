# 拼多多（Pinduoduo）API 契约声明

**适用代码**：`servers/pinduoduo/server.py`
**契约测试**：`tests/contract/test_wire_pinduoduo.py`、`tests/contract/vectors.py`（官方签名算例）、`servers/pinduoduo/tests/test_pinduoduo.py`
**对应 WP**：WP10（FR-011）
**最后核对**：2026-08（本 WP 未联网；证据来自 mission 审计阶段固化的官方文档清单与公告语料）

## 证据分级约定

本文件每条结论标注三类来源之一（NFR-002）：

| 标记 | 含义 |
|---|---|
| **官方明文** | 官方文档 / 参数表 / 公告正文直接写明，且出处可核 |
| **官方算例** | 官方给出的可复现工作示例（本仓库已本地精确复现） |
| **推断** | 官方无明文，依据充分的推断；给出推断依据 |

出处 URL 缺失的条目不做补齐式编造，一律进入 §9 待回填清单（spec.md §8：官方缺失项不得用推测填充）。

---

## 1. 网关与传输

| 项 | 值 | 来源 |
|---|---|---|
| 网关 | `https://gw-api.pinduoduo.com/api/router` | **官方明文**（接入指南 / 签名文档，见 §10-A） |
| 协议 | HTTPS。HTTP 版本已不允许调用 | **官方明文** |
| 方法 | `POST` | **官方明文** |
| 参数位置 | 全部走 POST 表单（`application/x-www-form-urlencoded`），query string 不带任何参数 | **官方明文**（参数表未定义 query 参数）+ 官方算例形态一致 |
| 寻址 | 单一 router，API 名放在 `type` 参数里（无 per-API path） | **官方明文** |

代码现状：一致，本 WP 未改动。

## 2. 系统参数表

| 参数 | 必填 | 值 | 来源 |
|---|---|---|---|
| `type` | 是 | API 名，如 `pdd.order.list.get` | **官方明文** |
| `client_id` | 是 | 应用 client_id（本仓库映射自 `PINDUODUO_CLIENT_ID`） | **官方明文** |
| `timestamp` | 是 | UNIX 时间（**秒**），见 §3 | **官方明文** |
| `data_type` | 否 | `JSON`（官方算例用 `XML`，两者均合法） | **官方明文** |
| `access_token` | 视接口 | 商家授权 token；本仓库调用的接口均需要 | **官方明文** |
| `sign` | 是 | 见 §4 | **官方明文** |

**`sign_method` 不是拼多多的请求参数** —— 官方参数表中无此项。因此不发送是正确的；一旦发送，它就成为"发了却无法按契约入签"的参数（spec.md §8 的跨平台缺陷类）。契约测试把 `sign_method` / `format` / `v` / `version` 全部列为禁发参数并硬断言。（**官方明文**：参数表穷举）

## 3. timestamp —— 本平台唯一的契约错误（已修）

| 项 | 官方 | 修复前 | 修复后 |
|---|---|---|---|
| 语义 | UNIX 时间（**秒**） | epoch **毫秒**（13 位） | UNIX 秒（10 位） |
| 官方示例 | `1480411125`（10 位） | — | — |
| 容差 | **10 分钟** | — | — |
| 校时 | 官方提供 `pdd.time.get` | — | 未使用（只读场景本机时钟足够；如遇 10 分钟外偏差再引入） |

来源：**官方明文**（参数表「UNIX时间（秒）」）+ **官方算例**（§4 的算例里 `timestamp1480411125`，10 位）。

毫秒值（如 `1774591200000`）被平台读作秒即约公元 48000 年，落在 10 分钟容差之外，会被网关直接拒绝 —— 这是"测试全绿但真机 100% 失败"的典型形态：既有单测全部 mock 在 `_call` 层，系统参数从未被执行（spec.md §2.4）。

代码：`servers/pinduoduo/server.py` 的 `PinduoduoMCP._call`，`str(int(time.time() * 1000))` → `str(int(time.time()))`。

## 4. 签名（现有实现已正确，本 WP 未改动）

```
sign = UPPER( MD5( client_secret + Σ(key + value, key 按 ASCII 升序) + client_secret ) )
```

- 公共参数与业务参数**全部参与**；
- 拼接处**无任何分隔字符**（不是 `k=v&`，也不带 `&`）；
- 结果转**大写**，32 位十六进制；
- 参与集合 = 发送集合 − `{sign}`。

**官方算例**（`tests/contract/vectors.py::VERIFIED[pinduoduo]`，本地精确复现）：

| 项 | 值 |
|---|---|
| secret | `testSecret` |
| 拼接串 | `access_tokenasd78172s8ds9a921j9qqwda12312w1w21211client_id1data_typeXMLorder_status1page1page_size10timestamp1480411125typepdd.order.number.list.get` |
| 期望 sign | `E4DE3ED21002510DED352819E7AE6775` |
| 出处 | §10-A |

契约测试的做法（`test_wire_pinduoduo.py`）：

1. 把算例参数逐个转写成 dict，再按「排序拼接」重建拼接串，**断言重建结果与官方拼接串逐字相等** —— 防止用一组碰巧哈希正确的参数糊过去；
2. 用 `PinduoduoMCP._sign` 对该 dict 签名，断言等于官方期望值；
3. 对每个工具的真实出网请求，用**扰动法**反推"哪些参数真的影响了签名"（逐个改动参数值看签名是否变化），再套用 WP01 的 `assert_signature_set_matches_sent`。扰动法不复制实现里的过滤规则，因此实现改了也不会假绿。

## 5. 错误信封

```json
{"error_response": {"error_code": 0, "error_msg": "", "sub_code": "", "sub_msg": "", "request_id": ""}}
```

来源：**官方明文**。代码现状一致（`_call` 判 `error_response` 并抛 `CommerceAPIError`）。

## 6. Endpoint 清单（修正后：10 个）

| 工具 | API type | 状态 |
|---|---|---|
| `get_order_list` | `pdd.order.list.get` | 官方存在，未改 |
| `get_order_detail` | `pdd.order.information.get` | 官方存在，未改 |
| `get_product_list` | `pdd.goods.list.get` | 官方存在，未改（**仅本店商品**） |
| `get_product_detail` | `pdd.goods.detail.get` | 官方存在，未改 |
| `get_refund_list` | `pdd.refund.list.increment.get` | **改名**（原 `pdd.refund.list.get`） |
| `get_refund_detail` | `pdd.refund.information.get` | 官方存在，未改 |
| `get_logistics_tracking` | `pdd.logistics.ordertrace.get` | **改名**（原 `pdd.logistics.trace.query`） |
| `list_logistics_companies` | `pdd.logistics.companies.get` | 官方存在，未改 |
| `get_shop_info` | `pdd.mall.info.get` | 官方存在，未改 |
| `list_promotions` | `pdd.promotion.merchant.coupon.list.get` | **改名 + 语义收窄**，见 §6.1 |

加上 `shared` 的 4 个跨平台运维工具（`get_metrics` / `get_traces` / `get_alerts` / `export_data`），本 server 注册 **14 个工具**（修复前 17 个）。

存在性判据（**官方明文**）：拼多多公开文档清单接口 + 公告全文语料双重比对（spec.md §2.3.1）。该平台历史上每次下线都点名到具体接口且公告永久可查，因此「全部公告语料 0 命中 **且** 不在 493 个现行接口清单中」= **从未存在**（而非已下线）。

### 6.1 `promotion.list` 的选型决策

官方**没有**裸 `pdd.promotion.list.get`。候选三个：

| 候选 | 语义 |
|---|---|
| `pdd.promotion.goods.coupon.list.get` | 商品券批次 |
| `pdd.promotion.merchant.coupon.list.get` | 店铺券批次 |
| `pdd.promotion.limited.discount.list.get` | 限时限量购活动 |

**选定：`pdd.promotion.merchant.coupon.list.get`（店铺券批次），并标注待确认。**

理由（原工具的意图证据，逐条）：

1. 原 docstring 是 "List promotion activities **for the authenticated shop**" —— 店铺维度，不是商品维度；
2. 入参只有 `page` / `page_size`，**没有 `goods_id`** —— 排除商品券批次（`goods.coupon`），它天然以商品为检索维度；
3. 剩下两个候选之间，原实现**没有留下可判别的证据**：被删掉的假响应 fixture 里同时编造了「满减」（更接近店铺券）与「秒杀」（更接近限时限量购）两类活动，各占一半。即原作者想表达的是"店铺所有营销活动"这一**平台不提供的聚合能力**；
4. 因此按 WP10 指示走保守选项 = 店铺券批次，并在此标注**待确认**。若使用方真正需要的是限时限量购活动，应新增一个独立工具指向 `pdd.promotion.limited.discount.list.get`，而不是改这个工具的语义。

同步动作：工具 docstring 已改为"列出本店店铺券批次"，不再宣称"所有促销活动"；单测中那份编造的响应 fixture 已换成**只断言透传与 API type**的信封 fixture —— 官方响应 schema 未取回，编造字段等于把本 mission 要消灭的缺陷重新造一遍（spec.md §8）。

### 6.2 删除的工具（平台无此能力，改名救不了）

| 原工具 | 原 API type | 判据 |
|---|---|---|
| `search_products` | `pdd.goods.search` | 商家侧**没有"搜全站商品"能力**；`pdd.goods.list.get` 只能列自己店铺的商品。（**官方明文**：现行接口清单无此能力项） |
| `get_review_list` | `pdd.goods.comments.get` | 493 个现行接口中 `comment` / `review` / `评价` / `评论` **零命中**；8 年 344 条公告**零命中** → 拼多多**从未开放**评价接口。（**官方明文**：清单 + 公告语料双重比对） |

`servers/pinduoduo/tests/test_pinduoduo.py` 里有一条参数化测试，断言这些名字**不再出现在 server 模块上** —— 让"重新加回来"必须是一次同时更新本文件的自觉动作，而不是一次静默回退。

### 6.3 移出的工具

| 原工具 | 原 API type | 原因 |
|---|---|---|
| `search_affiliate_goods` | `pdd.ddk.goods.search` | 属**多多客 / 多多进宝联盟体系**（归分类 12，不是商品 API） |

移出而非删除的理由（**官方明文**）：该接口本身存在，但需要**完全独立的开发者身份**——

- 角色 = 多多进宝推手；
- 应用类型 = 多多客联盟类应用；
- 还需额外完成 `client_id` ↔ 多多进宝账号绑定。

**走商家 ISV 授权拿到的 `access_token` 取不到该权限**；业务语义也不同：多多客是"选品赚佣金"，本 server 是"管理我的店"。把两者塞进同一个 server 会让使用者以为一套凭证能同时用。

后续选项：

1. **独立成 connector**（推荐）：新建 `servers/pinduoduo_ddk/`，自己的 env 前缀与 client_id，复用同一套签名与 timestamp 契约（多多客走同一网关与签名算法）；
2. 保持缺席 —— 只读经营分析场景不需要联盟选品。

本 WP 只做移出，不新建 connector（不在 WP10 范围）。

## 7. 平台侧约束（必须记录，非改名可解）

### 7.1 云外解密限额 —— `pdd.open.decrypt.batch`

- 自 **2026-05-12** 起，云外调用限 **1 次 / 10 秒**，且对「电商软件服务商」角色叠加**单应用单日 100 次**上限；
- 官方明文：**"请勿将云外解密作为正式业务场景使用"**；
- 推论（**推断**，依据上面两条明文）：云外部署的连接器每天最多只能解密 100 条订单收件人信息，不具备生产可用性。

**本 server 不实现解密**，因此不受该限额影响：只读经营分析不需要收件人明文。若将来确有明文需求，正确路径是脱敏接口 `pdd.open.decrypt.mask.batch`（无云内限制），而不是提高云外解密频次。

相关（**官方明文**，供部署决策）：入云对「商家自研」是**可选**的（官方原文"可以选择"），只有「订单类应用」「企业 ERP 类」是"必须"。即：订单接口云外可调，只是收件人字段为密文。

### 7.2 联系人字段变更 —— 2025-11-07

- 自 **2025-11-07** 起，联系人手机号**只在 `contact_mobile` 返回**；
- `receiver_phone` / `contact_phone` **不再包含**该信息；
- 该类订单的 `receiver_name` / `receiver_address` **返回空值属正常**，不是错误。

**解析逻辑必须接受空值。** 本 server 对订单接口做原样透传（不解析、不重排收件人字段），因此天然容忍；`servers/pinduoduo/tests/test_pinduoduo.py` 里有两条测试（列表 + 详情）用「`receiver_name`/`receiver_address` 为空 + 只有 `contact_mobile`」的载荷把这个行为钉住。任何将来在此处加字段映射的改动，都必须先过这两条测试。

补充（**官方明文**，尚未固化为测试）：订单在「已发货 / 已退款 / 审核中」状态下收件人信息直接为空；密文格式正在从「含检索串」灰度到「不含检索串」，下游若要解析密文需兼容两种。

## 8. 敏感接口

官方敏感接口清单共 4 个，本仓库调用其中 2 个：`pdd.order.list.get`、`pdd.order.information.get`（**官方明文**）。使用方需具备相应资质与授权；这属使用者侧前提，非代码问题。

## 9. 待确认 / 待回填（spec.md §8 处理，不得推测填充）

| # | 项 | 状态 | 处理 |
|---|---|---|---|
| 1 | `pdd.promotion.merchant.coupon.list.get` 的**业务参数名** | 官方参数表未取回；现沿用旧的 `page` / `page_size` | 标注待确认；不改名、不臆造。取回官方参数表后一并修正参数名与 `test_wire_pinduoduo.py` 的期望集合 |
| 2 | `pdd.refund.list.increment.get` 的**业务参数名** | 同上；接口语义是"增量"（按更新时间），现沿用 `start_created_at` / `end_created_at`（创建时间语义） | 标注待确认。这条风险比 #1 高：语义可能是 updated 而非 created |
| 3 | `pdd.logistics.ordertrace.get` 的**业务参数名** | 同上；现沿用 `order_sn` | 标注待确认 |
| 4 | 上述三个接口的**响应 schema** | 未取回 | 不编造字段；单测只断言透传与 API type |
| 5 | §6 / §7 各条的**逐条 deep-link URL** | 结论来自 mission 审计阶段固化的官方清单与公告语料，单条公告/接口的 idStr 深链未随审计留存 | 记为待回填。**不编造 URL** |
| 6 | 共享 `_sign` 会**丢弃空值参数** | 与拼多多"全部参数入签"冲突 | 目前 `_call` 不会发空值参数，故无实际偏差。`test_wire_pinduoduo.py` 显式断言"不发空值参数"，把这条前提钉住；`shared/cn_commerce_base.py` 不属本 WP |

## 10. 出处

- **A** 签名算法与官方算例：<https://open.pinduoduo.com/application/document/browse?idStr=8EC06C399636041E>
- **B** 存在性判据所用的公开文档清单接口（无鉴权）：`https://open.pinduoduo.com/pop/doc/category/list` + `https://open.pinduoduo.com/pop/doc/info/list/byCat` —— **注意有 16 个隐藏分类**，只按公开分类会漏（290 vs 493）。详见 spec.md §2.3.1
- **C** 网关：`https://gw-api.pinduoduo.com/api/router`（来源同 A）
- **D** 审计结论的仓内出处：`kitty-specs/api-contract-conformance-01M0ZHQN/spec.md` §2.3.1 / §2.3.3 / §8、`kitty-specs/api-contract-conformance-01M0ZHQN/tasks/WP10-拼多多-timestamp-单位.md`
