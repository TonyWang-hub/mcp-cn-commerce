# 微信小店 (WeChat Store) — API 契约声明

**适用代码**：`servers/weixin_store/server.py`
**wire 层断言**：`tests/contract/test_wire_weixin_store.py`
**单元测试**：`servers/weixin_store/tests/test_weixin_store.py`
**对应 WP**：WP11 / FR-012（`kitty-specs/api-contract-conformance-01M0ZHQN/`）

每一条结论标注**出处**，并区分「官方明文」（官方文档正文/参数表直接写明）与「推断」
（由官方材料穷举或交叉比对得出，官方未明文）。凡官方缺失或自相矛盾的，按 spec §8
处理 —— 标注为缺口，**不用推测填充**。

官方文档站：<https://developers.weixin.qq.com/doc/store/shop/>
接口变更日志（`D` = 删除，可用于巡检）：
<https://developers.weixin.qq.com/doc/store/shop/changelog.html>

---

## 1. 网关与鉴权

| 项 | 值 | 性质 | 出处 |
|---|---|---|---|
| Host | `https://api.weixin.qq.com` | 官方明文 | 各接口页「请求地址」栏 |
| 凭证 | `access_token`，**query string** | 官方明文 | 各接口页请求地址示例 `?access_token=ACCESS_TOKEN` |
| 请求体 | JSON（POST 接口） | 官方明文 | 各接口页「请求参数」栏 |
| 判错 | body 内 `errcode != 0`（`0` = 成功） | 官方明文 | 全局返回码说明 |
| **签名** | **无** | **推断（官方从未明文）** | 见下 |

### 1.1 「无签名」是推断，不是官方明文

官方**从未**在任何一处写下「本接口无需签名」。该结论来自对接口页
**参数表 + 鉴权栏的穷举**：三类接口页（订单/商品/售后）的请求参数表中都不存在
`sign`、`sign_method`、`timestamp`、`nonce` 一类字段，鉴权栏只列 `access_token`
与权限集编号。因此判定为**无逐请求签名**。

按 spec §8 的要求，此项在代码（模块 docstring）与本文档中都标注为推断。
`tests/contract/test_wire_weixin_store.py::test_no_signature_parameters_are_sent`
把这个推断钉住：一旦有人从 `shared/cn_commerce_base.py` 继承回签名逻辑，测试会红。

> 这也是本平台契约层此前唯一正确的原因：微信不需要签名，因此**没有**继承 base
> class 那套「所有中国电商平台系统参数长一个样」的错误假设。

### 1.2 频控与 IP 白名单

| 项 | 值 | 性质 |
|---|---|---|
| 调用频率 | 1 万次/分钟、50 万次/天 | 官方明文 |
| IP 白名单 | 上限 200 条；网段仅支持 `/8` `/16` `/24` | 官方明文 |
| 白名单未匹配 | **HTTP 403，不带 `errcode`** | 官方明文 |

HTTP 403 是本平台**唯一不走 `errcode`** 的失败形态，且 body 不保证是 JSON。
因此 `_decode()` 先看 `status_code`、再解析 body；`code=403` 的
`CommerceAPIError` 消息里直接给出处置办法（把出口 IP 加进白名单）。403 **不会**
触发 token 强制刷新 —— 错的是 IP 不是凭证。

---

## 2. Token：`POST /cgi-bin/stable_token`

| 项 | 值 | 性质 | 出处 |
|---|---|---|---|
| 路径 | `POST /cgi-bin/stable_token` | 官方明文 | getStableAccessToken 接口页 |
| 请求体 | `grant_type` = `client_credential`、`appid`、`secret`、`force_refresh` | 官方明文 | 同上参数表 |
| 返回 | `access_token`、`expires_in` | 官方明文 | 同上 |
| 与 `/cgi-bin/token` 的关系 | 「此接口和 getAccessToken 互相隔离，且比其更加稳定，**推荐使用此接口替代**」 | 官方明文（原文） | 同上 |
| `force_refresh` 限制 | 每天 **20** 次、间隔 **≥30 秒**，官方标注「慎用」 | 官方明文 | 同上 |

### 2.1 两个 token 接口不能共用一个缓存槽

官方明文：两接口凭证**互相隔离**。`stable_token` 的 `force_refresh=true` 不会让
`/cgi-bin/token` 的老 token 失效，反之亦然。因此**只能选一条路**，本 server 全程
只走 `stable_token`（缓存字段 `_stable_access_token` 专属该端点）。

`test_the_legacy_token_endpoint_is_never_called` 断言 `/cgi-bin/token` 不出现在
任何一次出网请求里。

### 2.2 TTL 必须读 `expires_in`，不能硬编码 7200

官方明文：非强制刷新模式下，若上次的 token 仍然有效，接口会返回**上次的 token
及其剩余有效期**（官方示例 `expires_in: 345`）。所以 7200 是错的默认值。

实现：
- `_token_ttl` / `_token_expires_at` 全部来自返回的 `expires_in`。
- 提前刷新缓冲 300 秒，但**按 `min(300, ttl/2)` 收窄** —— 否则 `expires_in: 345`
  会被 300 秒缓冲吞掉大半。这一条是工程取舍，**不是官方契约**，故标注为本仓库决定。
- 若返回体里**没有** `expires_in`（官方文档中不存在这种情况）：按 spec §8 不猜
  TTL —— 本次调用照用该 token，但不写入过期时间，下次重新问。

### 2.3 `force_refresh` 只在三个 errcode 时使用

`40001` / `42001` / `40014`（凭证无效、超时、不合法）。其他 errcode 一律不烧
`force_refresh` 预算。客户端自身也执行官方限制（间隔 ≥30 秒、每天 ≤20 次）：预算
不足时**不再尝试刷新**，把原始 errcode 抛给调用方，而不是静默重试。

---

## 3. Endpoint 清单

### 3.1 路径修正（5 个原路径查无此接口）

| 原调用（不存在） | 官方正确 | 方法 | 权限集 |
|---|---|---|---|
| `POST /channels/ec/basicinfo/get` | `/channels/ec/basics/info/get` | **GET** | 129、131、192 |
| `POST /channels/ec/category/list/get` | `/shop/ec/category/all` | **GET** | 85、129、192 |
| `POST /channels/ec/coupon/list/get` | `/channels/ec/coupon/get_list` | POST | 132 |
| `POST /channels/ec/order/deliveryinfo/get` | **无此能力** → 读 `order/get` 内嵌 `delivery_info` | POST | — |
| `POST /channels/ec/supplier/order/list/get` | `/channels/ec/order/dropship/list`（见 §5） | POST | 131 |

判据（spec §2.3.1）：官方文档清单 + 公告语料双重比对。**活体探测不作为存在性证据**。
这 5 条在官方[接口变更日志](https://developers.weixin.qq.com/doc/store/shop/changelog.html)
里查不到任何下线记录 —— 是**从未存在**，不是曾存在后下线。

两个 GET 接口**不带 body**：向 GET 接口发 POST 会返回 `43001`（官方明文，全局返回码）。
`test_the_two_get_endpoints_send_no_body` 断言这一点。

**注意前缀不统一**：类目接口是 `/shop/ec/`，其余是 `/channels/ec/`。
`channels` = 视频号，是历史遗留；视频号小店 → 微信小店是**文档站与品牌迁移，
不是接口下线**，`channels/ec/` 仍是官方现行形式（官方明文）。

### 3.2 契约本就正确的 2 个

| Endpoint | 请求体 |
|---|---|
| `POST /channels/ec/order/get` | `order_id` |
| `POST /channels/ec/aftersale/getaftersaleorder` | `after_sale_order_id` |

---

## 4. 请求体契约（4 个原请求体是编造的）

### 4.1 订单列表 `POST /channels/ec/order/list/get`

| 字段 | 类型 | 必填 | 说明 | 性质 |
|---|---|---|---|---|
| `create_time_range` | object `{start_time, end_time}` | 与 `update_time_range` **至少填一个** | 秒级时间戳 number；跨度 **≤ 7 天** | 官方明文 |
| `update_time_range` | object `{start_time, end_time}` | 同上 | 同上 | 官方明文 |
| `status` | number | 否 | 见枚举 | 官方明文 |
| `page_size` | number | 否 | **≤ 100** | 官方明文 |
| `next_key` | string | 否 | 上一页返回值，游标翻页 | 官方明文 |

返回：`order_id_list` + `has_more` + `next_key`（官方明文）。

**原实现发的 `start_create_time` / `end_create_time` / `page` 三个字段官方都不存在**，
会得到 `40097 invalid request body`。本 server 现在按上表发送，并在客户端就拦掉
字符串时间、毫秒时间戳、超 7 天跨度、`page_size > 100`。

状态枚举（官方明文）：

| 值 | 含义 |
|---|---|
| 10 | 待付款 |
| 12 | 礼物待收下 |
| 13 | 一起买待成团 |
| 20 | 待发货 |
| 21 | 部分发货 |
| **30** | **待收货**（原 docstring 写「已发货」，错） |
| 100 | 完成（原 docstring 写「已关闭」，错） |
| **250** | 订单取消（原实现缺失） |

原 docstring 里的 `50 (已完成)` **不是**合法状态值。

专属错误码（官方明文）：`31042` 订单过多，请缩短时间范围；`606006` `next_key` 与
上一页参数不一致（游标翻页时除 `next_key` 外所有参数必须保持不变）。

### 4.2 商品列表 `POST /channels/ec/product/list/get`

| 字段 | 类型 | 必填 | 说明 | 性质 |
|---|---|---|---|---|
| `page_size` | number | **是** | 默认 10、**上限 30** | 官方明文 |
| `status` | number | 否 | 见枚举；**要「全部」应不传该字段** | 官方明文 |
| `next_key` | string | 否 | 游标 | 官方明文 |

返回：`product_ids` + `next_key` + **`total_num`**；**本端点没有 `has_more`**，
按 `total_num` 判分页（官方明文）。

状态枚举（官方明文）：`0` 初始值 / `5` 上架 / `6` 回收站 / `11` 下架。
枚举里**没有「全部」成员** —— 原实现传 `status=0` 当「全部」是错的，`0` 是「初始值」。
原 docstring 的 `1 上架 / 2 下架 / 3 审核中 / 4 审核失败` 与 `page_size` 上限 200
均为编造。原实现还多发了一个不存在的 `page`。

### 4.3 售后列表 `POST /channels/ec/aftersale/getaftersalelist`

**契约与订单列表完全不同，不可照抄**：

| 字段 | 类型 | 必填 | 说明 | 性质 |
|---|---|---|---|---|
| `begin_create_time` / `end_create_time` | number | 与 update 对**必选其一** | 秒级时间戳；**成对使用** | 官方明文 |
| `begin_update_time` / `end_update_time` | number | 同上 | 同上 | 官方明文 |
| `next_key` | string | 否 | 游标 | 官方明文 |

- 是 **4 个平铺字段**，不是嵌套 range 对象。
- 跨度上限 **24 小时**（不是订单列表的 7 天）。
- **没有 `page_size`，也没有 `page`** —— 原实现两个都发了。
- 原实现传 `"2024-01-01 00:00:00"` 字符串，官方要的是秒级 number。

返回：`after_sale_order_id_list` + `has_more` + `next_key`（官方明文）。

### 4.4 商品详情 `POST /channels/ec/product/get`

| 字段 | 类型 | 必填 | 说明 | 性质 |
|---|---|---|---|---|
| `product_id` | string | 是 | | 官方明文 |
| `data_type` | number | 否 | 默认 1；`1` 线上 / `2` 草稿 / `3` 两者 | 官方明文 |

原实现漏了 `data_type`。本 server 显式发送（默认 1），使读的是哪份数据在调用处可见。

### 4.5 优惠券列表 `POST /channels/ec/coupon/get_list`

| 字段 | 类型 | 必填 | 说明 | 性质 |
|---|---|---|---|---|
| `status` | number | **是** | 见枚举 | 官方明文 |
| `page` | number | **是** | ≥ 1 | 官方明文 |
| `page_size` | number | **是** | **≤ 200** | 官方明文 |
| `page_ctx` | string | **是** | 首次传空串，之后传上一页返回值 | 官方明文 |

4 个字段**全必填**。状态枚举（官方明文）：`1` 编辑中 / `2` 已生效 / `3` 已过期 /
`4` 已作废 / `5` 已删除 / `200` 过期或作废。

**枚举里没有 `0`**，原实现的默认值 `status=0` 不合法；也因此本端点**不存在
「查全部状态」的查询**，工具的 `status` 参数**没有默认值**，必须由调用方指定。
原 docstring 的 `0 全部 / 1 进行中 / 2 未开始 / 3 已结束 / 4 已停止` 为编造。

另有官方约束：**相邻两次请求的页码间隔不能超过 10**。客户端按此校验
（`_coupon_page_cursor`），跨度超限时在本地报错而不是打到平台。

---

## 5. 物流与供货：两个「体系/能力」层面的决定

### 5.1 物流：无拉取接口，改读订单详情

官方**全站只有「修改物流信息」写接口**，没有任何物流拉取接口
（判据：文档清单比对，spec §2.3.1）。原实现的
`POST /channels/ec/order/deliveryinfo/get` 不存在。

**决定**：`get_logistics_tracking` 改为调 `POST /channels/ec/order/get`
（我们本来就在调它），从返回体里取 `order.order_detail.delivery_info`
（含 `waybill_id`、`delivery_id`、`extra_logistics_info`）。

**能力边界**：这是**发货状态**，不是承运商轨迹 —— 没有揽收/中转/派送节点可返回。
工具 docstring 明确说明了这一点，返回体里带 `source` 字段标出数据来自哪个 endpoint
的哪个字段，避免下游误以为拿到了轨迹。

### 5.2 供货订单：明确选择「小店侧」

三个真实候选**分属两套体系**，用小店 token 调不了供货商侧接口，反之亦然（官方明文：
权限集不同，供货商侧需「小店供货商」账号）：

| 候选 | 体系 | 权限集 | 账号要求 |
|---|---|---|---|
| **`POST /channels/ec/order/dropship/list`** | **小店侧** | **131** | 微信小店商家 |
| `POST /channels/ec/order/dropship/supplier/list` | 供货商侧 | 192 | 需「小店供货商」账号 |
| `POST /channels/ec/order/supplyorder/list` | 小店侧 | 131 | 微信小店商家 |

**决定：选 `POST /channels/ec/order/dropship/list`（小店侧，权限 131）。**

**理由**：

1. 本 server 的鉴权身份就是**微信小店商家** —— `WX_APP_ID`/`WX_APP_SECRET` 对应
   小店应用，其余 10 个 endpoint 全部是小店侧接口（订单、商品、售后、店铺基础信息）。
   供货商侧接口需要「小店供货商」账号，**用现有凭证调不通**，选它等于交付一个
   必然 401/权限错误的工具。
2. 原工具的 docstring 写的是「unique to WeChat Store」（小店），而实现却发
   `supplier/...`（供货商侧）—— **意图与实现自相矛盾**。按 docstring 声明的意图
   （我们是小店）解决该矛盾。
3. 两个小店侧候选之间选 `dropship/list`：与原工具语义（代发/供货订单列表）对应，
   且权限集与我们已在用的订单接口一致（131）。`order/supplyorder/list` 保留为后续
   如需「供货单」而非「代发订单」时的备选，**未在本 WP 中实现**。

**未验证项（spec §8 缺口，不用推测填充）**：`order/dropship/list` 的**请求字段清单
未进入本次已核实语料**。原实现向一个不存在的路径发了 5 个编造字段
（`start_create_time`/`end_create_time`/`status`/`page`/`page_size`）；本次**不再重复
这个错误**：工具**不接受任何参数**，请求体为空 `{}`，不发送任何无法溯源的字段名。
代价是暂不支持筛选与翻页 —— 这是本 WP 明确留下的缺口，待官方字段表核实后另行补齐
（`test_dropship_body_invents_nothing` 把「不发明字段」这条钉住）。

---

## 6. 已知缺口（spec §8）

| 项 | 状态 | 处理 |
|---|---|---|
| 「无签名」 | 官方从未明文 | 标注为**推断**（§1.1），并用 wire 断言钉住 |
| `order/dropship/list` 请求字段 | 未进入已核实语料 | 请求体留空，不发明字段；工具暂不暴露筛选/翻页（§5.2） |
| **详情类接口的响应体字段未逐个核对** | 本次只核了列表接口的返回结构 | 鉴于请求体的编造率，返回体解析逻辑需单独过一遍；本 WP 未做 |
| token 缓冲窗口 `min(300, ttl/2)` | 官方无规定 | 标注为**本仓库工程决定**，非契约（§2.2） |
| `expires_in` 缺失时的 TTL | 官方文档中不存在该情况 | 不猜 TTL：用完即弃，下次重新问（§2.2） |

## 7. 变更影响（调用方需知）

| 工具 | 变化 |
|---|---|
| `get_order_list` | 时间参数由日期字符串改为 **epoch 秒（int）**；`page` 移除，改 `next_key` 游标；新增 `time_field`；状态枚举校验 |
| `get_product_list` | `status` 由 int 改 str（空 = 不筛选）；`page` 移除，改 `next_key`；`page_size` 默认 10、上限 30 |
| `get_product_detail` | 新增 `data_type`（默认 1） |
| `get_refund_list` | 时间参数改 epoch 秒；`page`/`page_size` 移除（平台无此字段）；新增 `time_field`、`next_key`；跨度上限 24h |
| `get_logistics_tracking` | 返回体改为 `{errcode, errmsg, order_id, delivery_info, source}`；不再有轨迹节点 |
| `get_shop_info` | 改 GET |
| `list_coupons` | `status` **变为必填**（无「全部」）；新增 `page_ctx` |
| `get_supply_order_list` | 参数全部移除（见 §5.2）；endpoint 改小店侧 dropship |
| `list_categories` | `parent_id` 移除（该参数是编造的）；改 GET；一次返回全量树（`cats_v2`） |

工具**数量不变**：11 个平台工具 + 4 个跨平台运维工具 = **15**（`scripts/smoke_install.py`
的 `EXPECTED_TOOLS["weixin_store"]` 无需改动）。
