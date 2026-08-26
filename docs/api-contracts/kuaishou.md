# 快手小店开放平台契约声明

对象：`servers/kuaishou/server.py`（`KuaishouMCP`）
wire 层断言：`tests/contract/test_wire_kuaishou.py`
工具层断言：`servers/kuaishou/tests/test_kuaishou.py`
审计依据：`kitty-specs/api-contract-conformance-01M0ZHQN/spec.md` §2.2 / §2.3.1 / §8、`tasks/WP09-快手契约修正.md`

## 0. 出处标注规则（先读这条）

每条结论标注「**官方明文**」或「**推断**」。出处栏遵守与 `taobao.md` 同一条纪律：

1. **只写取得过的 URL。** 本 WP 在实施过程中**没有**捕获任何可直接引用的官方文档 URL —— 所有官方结论来自 mission 审计阶段建立的双 oracle，实施阶段是对该审计结论的落地，而不是二次抓取。因此本文出处栏写**证据本身**（哪个 oracle、哪个 SDK 符号、哪条公告），不构造看起来像真的链接。
2. 快手的两个 oracle（spec §2.3.1）：
   - **官方 Java SDK** —— 452 个 `*Request` 类，每个类的 `getApiMethodName()` 给出 method 名，`SignUtils.getSignParam()` 给出签名参与集合；
   - **官方 API 目录接口** —— `rest/open/platform/doc/api/category/list`，339 个在维护的 API。
3. **退役判据**：`SDK 中全部候选类标注 @Deprecated` **且** `该 method 在 339 个目录条目中缺失`。SDK 里共 71 个 `@Deprecated` 类，多数标的是**旧 SDK 包装类**而非死接口（典型：退款列表的旧类已废弃、新类仍在目录中，接口是活的），单看 `@Deprecated` 会误杀。

## 1. Endpoint 修正

原实现的 12 个 path 全部是同一个虚构 REST 模板 `/open/api/<名词>/<动作>` 的产物（spec §2.2「模式三：通用 REST 模板」）。官方规则是 **path 由 `method` 名点换斜杠机械导出**，中间**没有** `api` 段。

### 1.1 保留的 9 个（全部 GET）

| 原虚构 path | 官方 method | 官方 path | 类别 | 出处 |
|---|---|---|---|---|
| `/open/api/order/list` | `open.order.cursor.list` | `/open/order/cursor/list` | 官方明文 | SDK `getApiMethodName()` + API 目录 |
| `/open/api/order/detail` | `open.order.detail` | `/open/order/detail` | 官方明文 | 同上 |
| `/open/api/item/list` | `open.item.list.get` | `/open/item/list/get` | 官方明文 | 同上 |
| `/open/api/item/detail` | `open.item.get` | `/open/item/get` | 官方明文 | 同上 |
| `/open/api/refund/list` | `open.seller.order.refund.pcursor.list` | `/open/seller/order/refund/pcursor/list` | 官方明文 | 同上 |
| `/open/api/refund/detail` | `open.seller.order.refund.detail` | `/open/seller/order/refund/detail` | 官方明文 | 同上 |
| `/open/api/comment/list` | `open.comment.list.get` | `/open/comment/list/get` | 官方明文 | 同上 |
| `/open/api/coupon/list` | `open.promotion.coupon.page.list` | `/open/promotion/coupon/page/list` | 官方明文 | 同上 |
| `/open/api/shop/info` | `open.shop.info.get` | `/open/shop/info/get` | 官方明文 | 同上 |

代码里**不硬编码 path**：`KuaishouMCP.path_for()` 从 method 名导出，所以 path 与 method 不可能再各自漂移。这不是风格偏好 —— 上一版之所以能长期携带 9 个虚构 path，正是因为 path 是独立于 method 的第二份字符串。

### 1.2 已退役、不再使用的 method

| 退役 method | 现役替代 | 类别 | 出处 |
|---|---|---|---|
| `open.seller.order.pcursor.list` | `open.order.cursor.list` | 官方明文 | 迁移公告「11.30 下线」+ 已从 339 个目录条目中移除 |
| `open.seller.order.detail` | `open.order.detail` | 官方明文 | 同上 |
| `open.item.list` | `open.item.list.get` | 官方明文 | 同上 |
| `open.item.detail` | `open.item.get` | 官方明文 | 同上 |

`tests/contract/test_wire_kuaishou.py::test_retired_order_methods_are_not_used` 把这四个名字钉成负向断言，防止后续从旧文档/旧 SDK 抄回来。

### 1.3 删除的 3 个工具（平台不提供，改名无法修复）

| 删除的工具 | 原虚构 path | 平台实际情况 | 类别 | 出处 |
|---|---|---|---|---|
| `get_logistics_tracking` | `/open/api/logistics/track` | 物流 API 14 个 + 快递 API 9 个全部核对：**只有物流商向快手「推」轨迹的写接口**，方向与我们的读取需求相反，没有商家侧拉取轨迹的接口 | 官方明文 | API 目录逐条比对（spec §2.1 快手 3 项） |
| `list_logistics_companies` | `/open/api/logistics/company/list` | **不是 API，而是一份静态文档表**《物流公司编号》；文档另有警告：用已下线编码发货会被按**虚假发货**拦截 | 官方明文 | 同上 + 该文档正文 |
| `list_promotions` | `/open/api/promotion/list` | 营销 API 共 14 个，只覆盖 coupon 与人群包，没有「营销活动列表」这一能力 | 官方明文 | 同上 |

删除而不是保留一个报错的桩：一个存在的工具名会被模型当作可用能力去调用。两处测试各自钉住（wire 层 `test_capabilities_the_platform_does_not_offer_are_gone`、工具层 `test_unavailable_capabilities_are_not_exposed`）。

## 2. 参数结构

系统参数**平铺**，业务参数**不平铺** —— 全部序列化成**一个 JSON 字符串**放进 `param` 字段，键名 **camelCase**。

| 参数 | 命名 | 值 | 原实现 | 类别 | 出处 |
|---|---|---|---|---|---|
| `appkey` | **全小写、无下划线** | app key | ❌ `app_key` | 官方明文 | SDK 公共参数常量 |
| `method` | 点分 | 如 `open.order.cursor.list` | ❌ **根本没发** | 官方明文 | 同上 |
| `version` | — | `1` | ❌ **根本没发** | 官方明文 | 同上 |
| `access_token` | **snake_case** | token | ✅ 已正确 | 官方明文 | 同上 |
| `timestamp` | — | epoch **毫秒** | ✅ 已正确 | 官方明文 | 同上 |
| `signMethod` | **camelCase** | `MD5` / `HMAC_SHA256` | ❌ `sign_method` | 官方明文 | 同上 |
| `sign` | — | 见 §3 | ✅ 名称正确、算法错 | 官方明文 | 同上 |
| `param` | — | 业务参数的单个 JSON 串 | ❌ 业务参数当独立 query 散发 | 官方明文 | 同上 |
| `uid` | — | **不要发** | 未发（正确） | 官方明文 | 历史参数，当前 SDK 已无此字段 |

注意 `signMethod` 的两副面孔：**参数名是驼峰，取值是全大写下划线**（`HMAC_SHA256`）。这跟基类的 `SignMethod.HMAC_SHA256 == "hmac_sha256"` 不是一回事，`KuaishouMCP.sign_method` 存的是**发到线上的那个值**。

### 2.1 空值与 `param` 的关系

- **系统参数**为空则整个键不发（`build_params()` 过滤 `("", None)`）。这让「签名集合 == 发送集合 − {sign}」由构造保证，而不是靠事后校对。
- **业务参数**只丢 `None`，**保留空串**：`cursor` / `pcursor` 被官方定义为「首次传空」，键必须存在。
- 业务参数全空时 `param` **整个不发**（如 `open.shop.info.get`）。

### 2.2 序列化只做一次

`pack_param()` 用 `sort_keys=True, separators=(",", ":")` 序列化，返回的字符串同时供签名与发送使用。spec §8 列的抖店缺陷「签的是 sorted-compact JSON、发的是 httpx 默认序列化的两份不同字节」在此结构上不可能发生。

### 2.3 Content-Type 与 POST 形态

Content-Type **仅支持** `application/x-www-form-urlencoded`（官方明文）。POST 时官方客户端只把 `appkey` 留在 query string、从 body 中移除它，其余全部走 form body —— `_call(http_method="POST")` 实现了这一形态。

**当前 9 个 endpoint 全部是 GET**，所以这条分支在本仓库里没有活跃调用方。保留它是因为 GET/POST 在快手是**逐 API 决定**的（官方 SDK 453 个请求类中 233 GET / 219 POST），下一个接入的接口很可能是 POST；把形态写对一次，比在 POST 出现时临时拼一遍安全。

## 3. 签名

### 3.1 密钥：`signSecret`，不是 `appSecret`

快手有**两个凭证**：`appSecret` 只用于 OAuth 换 token，请求签名用**独立的 `signSecret`**（官方明文）。原实现已经用对了 `sign_secret`，这是四层里唯一没错的一处。`tests/contract/test_wire_kuaishou.py::test_signature_uses_sign_secret_not_app_secret` 正反两侧都断言（用 `appSecret` 算出来的值必须**不等于**发出去的 `sign`）。

### 3.2 算法

| 项 | 官方契约 | 原实现 | 类别 | 出处 |
|---|---|---|---|---|
| 参与集合 | 必填 `method` / `appkey` / `access_token`；非空则含 `signMethod` / `version` / `timestamp` / `param`；排除 `sign` 与 byte[] | ❌ 排除了 `sign_method`，且 `method`/`version`/`param` 根本不存在 | 官方明文 | SDK `SignUtils.getSignParam()` |
| 排序 | 按参数名字典序（SDK 用 TreeMap，跳过 null） | 已排序 | 官方明文 | 同上 |
| 拼接 | `k=v` 用 `&` 连接 | ❌ 无分隔符的 `kvkv...` | 官方明文 | 同上 |
| secret 位置 | **末尾追加字面量 `&signSecret=<signSecret>`** | ❌ 首尾各包一次 | 官方明文 | 同上 |
| 摘要 | MD5 → **小写 hex**；或 HMAC_SHA256 → **Base64（非 hex）** | ❌ MD5 → **大写** | 官方明文（见 §3.4） | 同上 |
| 编码时机 | **先算签名，再 URL encode** | 不适用（当时无 `param`） | 官方明文 | 同上 |

待签串形态（`KuaishouMCP.sign_base_string()`）：

```
access_token=<tok>&appkey=<key>&method=open.item.get&param={"itemId":"30001"}&signMethod=MD5&timestamp=1704038400000&version=1&signSecret=<signSecret>
```

`signSecret` **绝不作为请求参数发出** —— 它只出现在待签串末尾。`test_sign_secret_is_never_transmitted` 同时检查参数值和最终 URL。

### 3.3 编码时机是硬约束，不是风格

签名对**原始值**计算，URL 编码只在发送时做（`param` 里的 `"` 和 `:` 在线上是 `%22` / `%3A`）。反过来做必然验签失败。实现上由 httpx 在 `client.get(url, params=...)` 时完成编码，代码里传出去的始终是原始 dict —— 顺序因此由结构保证。`test_signature_is_computed_before_url_encoding` 断言两件事：捕获到的 `param` 仍是原始 JSON，且**按 percent-encoded 值算出的签名与实际发出的签名不相等**（若二者相等，这条断言就没有区分力，说明测试假的）。

### 3.4 默认摘要选 MD5

`signMethod` 两个取值都是官方的。本实现**默认 MD5**，可用 `KUAISHOU_SIGN_METHOD=HMAC_SHA256` 切换：

- MD5 是有公开算例、可交叉验证的那一支；
- 官方文档 §4 示例 URL 里 anchor 文本是小写、href 是大写，**自相矛盾**；官方 SDK 用 `md5Hex`，**以小写为准**（官方明文，SDK 优先）。

HMAC_SHA256 分支产出 **Base64**，不是 hex —— 这点容易照抄成 `hexdigest()`，`test_hmac_sha256_variant_is_base64_not_hex` 钉住。

> **不属于本 WP 的连带影响**：`tests/test_api_compatibility.py::test_kuaishou_sign_uses_sign_secret` 与 `tests/test_integration.py::test_kuaishou_sign_uses_sign_secret` 断言快手签名为**大写**。改小写后二者会红。这两个文件不在本 WP 的 owned_files 内，未修改。

## 4. 判错：`result == 1`

| 项 | 官方契约 | 原实现 | 类别 | 出处 |
|---|---|---|---|---|
| 成功判定 | `result == 1` | ❌ 查 `error_response` | 官方明文 | SDK 响应基类 |
| 业务数据位置 | `data` | 直接把整个信封当数据返回 | 官方明文 | 同上 |
| 错误文案 | `error_msg` | 退化为 `"unknown"`（因为压根没进错误分支） | 官方明文 | 同上 |

`error_response` 是淘宝/拼多多的信封，快手**从不产出**这个键。净效果是：**快手的任何失败都检测不到**，错误信封会被当成业务数据交给模型 —— spec §2.1 把这一类列为最危险的缺陷，因为模型拿到的是看起来成功的垃圾数据。

`_check_envelope()` 现在负责：HTTP ≥ 400 → `CommerceAPIError(code=status)`；`result != 1` → `CommerceAPIError(code=result, msg=error_msg)`；否则返回**完整信封**（含 `result` / `data` / 游标），由工具层原样 JSON 化。返回完整信封而非只返回 `data`，是因为游标（`cursor` / `pcursor`）是调用方翻页必须拿到的东西。

响应体内**字段名**的规范化不在本 WP 范围内（`shared/normalizer.py` 的 kuaishou 映射未改动），本 WP 只改请求侧四层与信封判定。

## 5. 分页：逐接口不同，不可一概而论

这是快手最容易一概而论出错的地方 —— 五个列表接口用了**五种**分页范式。

| 接口 | 范式 | 参数 | 约束 | 类别 | 出处 |
|---|---|---|---|---|---|
| `open.order.cursor.list` | 纯游标 | `cursor`（首次空串，返回 `"nomore"` 到底） | `pageSize` ≤ 50；时间窗 ≤ 7 天；只能查 **90 天内**；`orderViewStatus` **必填** | 官方明文 | API 目录 + SDK 请求类字段 |
| `open.seller.order.refund.pcursor.list` | **混合** | `pcursor` **与** `currentPage` 都要传 | `pageSize` ≤ 100；时间窗 **≤ 1 天** | 官方明文 | 同上 |
| `open.item.list.get` | 真页码 | `pageNumber` + `pageSize` | `pageSize` 10–100，推荐 20 | 官方明文 | 同上 |
| `open.comment.list.get` | offset/limit | `offset` + `limit` | `limit` **≤ 20** | 官方明文 | 同上 |
| `open.promotion.coupon.page.list` | 页码 | `pageNo`（从 1）+ `pageSize` | — | 官方明文 | 同上 |

`orderViewStatus` 枚举（官方明文）：1 全部 / 2 待付款 / 3 待发货 / 4 待收货 / 5 已收货 / 6 交易成功 / 7 已关闭。工具默认 `1`，非枚举值直接 `ValueError`。

### 5.1 越界处理：分页值夹紧，时间窗告警

- `pageSize` / `limit` 越界 → **夹紧到官方区间并 `logger.warning`**。夹紧是安全的：它只会让请求变成一个官方接受的请求。
- 时间窗超限、`beginTime` 超出 90 天留存 → **只告警，不拦截**。理由有两层：(1) 平台才是当前限制的权威，退款窗口在大促期间会被临时收紧到小时/分钟级，客户端硬拦会把本来能过的调用挡掉；(2) 90 天留存需要拿 `now` 做判断，硬拦会让"同一份参数今天能跑、90 天后跑不了"，测试与回放都会变得不确定。

退款窗口上限做成可配置（`KUAISHOU_REFUND_WINDOW_HOURS`，默认 24 小时），正是因为它是会被平台临时改的那一条。

### 5.2 时间入参：naive 值按 GMT+8 解释

工具接受 epoch 毫秒、epoch 秒、`YYYY-MM-DD HH:MM:SS`、`YYYY-MM-DD`、ISO 8601。**不带时区的值显式按 GMT+8 解释**（`timezone(timedelta(hours=8))`），不依赖进程时区 —— 这是 spec §2.1 在京东那条上记的同一个教训：容器跑 UTC 会让每个查询窗口静默偏 8 小时。解析不出来的值抛 `ValueError`，不静默取 0。

## 6. 网关

| 项 | 值 | 类别 | 出处 |
|---|---|---|---|
| 默认 | `https://openapi.kwaixiaodian.com` | 官方明文 | 官方接入文档（spec §2.3 快手行；URL 未在本 mission 内捕获） |
| 备用 | `open.kwaixiaodian.com` | 官方明文 | 同上 |

备用网关**未在代码中启用** —— 官方没有说明两者是别名、灰度还是有能力差异，按 spec §8 的口径不声明二者等价。改 `BASE_URL` 即可切换。

## 7. 绕过基类的哪些能力

`servers/kuaishou/server.py` **不走** `CommerceMCPBase._request`。原因不是偏好：基类 `_request` 会写死 `app_key` / `sign_method` 两个错名、把业务参数平铺进 query、并按 `error_response` 判错 —— 对快手，这三件事逐一都是错的，而它们发生在 `_request` 内部，没有可注入的缝。仓库中已有 4 个平台出于同类原因自建请求组装：拼多多、小红书、微信小店（覆写 `_request`）、淘宝（覆写 `_request` 与 `_ensure_client`）。快手是第五个。

| 基类能力 | 状态 | 说明 |
|---|---|---|
| 参数组装（`app_key`/`sign_method`/平铺业务参数） | **绕过** | 三项对快手全错，是绕过的原因本身 |
| `error_response` 判错 | **绕过** | 换成 `result == 1`（§4） |
| 入参注入校验（`_validate_params`） | **保留** | `_call` 里对业务参数显式调用 |
| 限流（`RateLimiter.acquire`） | **保留** | `_call` 里显式 `await` |
| tracing（`RequestTracer` span） | **保留** | 每次调用一个 span，含 `api_method` 属性 |
| metrics（`MetricsCollector`） | **保留** | 成功/失败双路径都记录，`get_metrics` 工具照常可用 |
| **重试（`RetryConfig` / `with_retry`）** | **绕过，未接** | 基类的重试与「每次重试重算 timestamp」耦合在 `_request` 里。快手的 timestamp 参与签名，重试必须重算签名 —— 这条已在 `build_params()` 里成立，但重试策略本身尚未接线。**已知缺口**，需要时按 `_call` 外层包装补。 |
| 连接池 / 自动重连（`_ensure_client`） | **绕过** | 与另外几个平台一致，按调用创建 `httpx.AsyncClient(timeout=30)`。基类 `_ensure_client` 默认会先发 HEAD 探针（`ReconnectConfig.probe_on_connect=True`），对一个只接受签名请求的网关是多余往返。 |
| 请求体压缩（`RequestCompressor`） | **绕过，且不适用** | 网关只接受 `application/x-www-form-urlencoded`，没有可压缩的 JSON body。 |

## 8. 甄别陷阱（留作路标）

1. **`@Deprecated` ≠ 死接口。** SDK 里 71 个 `@Deprecated` 多数标的是旧包装类。判据必须是「全部候选类废弃 **且** 目录中缺失」，见 §0.3。
2. **活体探测不是存在性证据**（spec §2.3.1）。
3. **不要参考第三方 Python SDK。** 已知两处错误：`/open/open/...` 双前缀 bug，以及把 `result` 当 payload 的信封误解 —— 后者正是原实现犯的同一个错。
4. **`signMethod` 参数名驼峰、取值全大写**，两处大小写风格不一致是官方就这样，不是笔误。

## 9. 未取到 / 有意留空的项（spec §8 口径）

| 项 | 状态 | 处理 |
|---|---|---|
| 退款列表的状态筛选参数名 | 官方参数名未在本 WP 的证据范围内取到 | **不提供该筛选**，工具 docstring 与本表记录原因；不猜一个 `refundStatus` 填进去 |
| 优惠券列表的状态筛选参数名 | 同上 | 同上 |
| `open.order.cursor.list` 除 5 个已确认字段外的可选参数 | 未取到 | 不发 |
| 备用网关与主网关的关系 | 无官方说明 | 不声明等价（§6） |
| 响应体字段命名规范化 | 不在本 WP 范围 | `shared/normalizer.py` 的 kuaishou 映射未改动 |

原实现被删掉的 `order_status` / `refund_status` / `status` 三个筛选参数，都属于「参数名未取到」这一类。它们此前之所以"存在"，是因为整套参数都是照通用模板编的 —— 保留一个名字错的筛选参数比没有筛选更糟：调用方以为筛了，网关按未知参数处理。
