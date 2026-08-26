# 淘宝开放平台（TOP）契约声明

对象：`servers/taobao/server.py`（`TaobaoMCP`）
wire 层断言：`tests/contract/test_wire_taobao.py`
审计依据：`kitty-specs/api-contract-conformance-01M0ZHQN/spec.md` §2.1 / §2.3.1 / §8、`tasks/WP05-淘宝契约修正.md`

## 0. 出处标注规则（先读这条）

每条结论都标了「**官方明文**」或「**推断**」。出处栏遵守两条纪律：

1. **只写取得过的 URL。** 本 WP 只有一个可直接引用的官方文档 URL（见下表 §2），它由 WP01 在 `tests/contract/vectors.py` 中记录并注明取回方式（公开可读，程序化抓取需带 `_tb_token_` cookie 访问 `/handler/document/getDocument.json?docId=101617&docType=1`）。
2. **官方证据存在但 URL 未在本 mission 内捕获时，写证据本身**（公告编号 / API 目录 docId / 官方目录接口），不构造看起来像真的链接。淘宝的 API 详情页确实是 `open.taobao.com/api.htm?docId=<N>&docType=2` 形式，但由 docId 拼出来的 URL 属于我构造的、未验证的东西，因此不作为出处写入本文。

审计口径同样记录在此：TOP **没有「已废弃」文档标签**，废弃只通过「从目录移除 + 平台公告」表达。因此"文档页看着正常"和"`getApiParamList` 返回成功"都不是接口在维护的证据（`taobao.items.list.get` 2018 年下线，注册表至今仍返回参数）。唯一判据是官方目录树（`handler/document/getApiCatelogConfig.json`，6601 个 API）+ 885 条公告全文的双重比对。

## 1. Endpoint 修正

| 我们原先调用的 | 状态 | 现在调用 | 类别 | 出处 |
|---|---|---|---|---|
| `taobao.item.get` | 2018-01-22 官方公告下线 | `taobao.item.seller.get` | 官方明文 | 官方目录比对 + 公告语料（spec §2.1、WP05 endpoint 修正表） |
| `taobao.shop.get` | 2019-04-08 官方公告下线 | `taobao.shop.seller.get` | 官方明文 | 同上 |

其余 11 个 method 经目录比对确认在维护，未改动。其中 `taobao.promotionmisc.activity.range.list.get` 真实存在（官方目录 docId=22252，并出现在 53 条大促公告中），早前的"疑似虚构"结论不成立（spec §2.3.2 第 6 条）。

## 2. 系统参数与签名

| 项 | 官方契约 | 原实现 | 现实现 | 类别 | 出处 |
|---|---|---|---|---|---|
| 凭证参数名 | `session` | `access_token` | `session` | 官方明文（TOP 公共参数表中不存在 `access_token`） | 官方公共参数表（WP05 官方契约对照表；URL 未在本 mission 内捕获） |
| timestamp 格式 | `yyyy-MM-dd HH:mm:ss` | epoch 毫秒 | `%Y-%m-%d %H:%M:%S` | 官方明文 | 同上 |
| timestamp 时区 | GMT+8，容差 10 分钟 | 依赖 epoch（无时区概念） | `timezone(timedelta(hours=8))` 显式固定 | 官方明文 | 同上 |
| `format` / `v` | `format` 服务端默认 xml，故必须显式发 `json`；`v` 必填 `2.0` | 已正确 | 保持 | 官方明文 | 同上 |
| 摘要与拼接 | `upper(md5(secret + Σ(key+value) + secret))`，无分隔符，UTF-8 | 已正确 | 保持 | 官方明文 | [签名算法文档 docId=101617](https://open.taobao.com/docV3.htm?docId=101617&docType=1)（官方算例 `secret=helloworld` → `66987CB115214E59E6EC978214934FB8`；URL 由 WP01 记录于 `tests/contract/vectors.py`） |
| 排序 | key 按 **ASCII 码位**升序 | 已正确（Python `sorted()` 即码位序） | 保持 + 显式断言 | 官方明文 | 同上 |
| 签名参与集合 | 除 `sign` 与 byte[] 外**全部**参数入签 | ❌ `sign_method` 发而不签 | 全部入签 | 官方明文（官方算例的拼接串本身含 `sign_method` 与 `format`） | 同上 |
| 空值处理 | key 或 value 为空 → 整个参数跳过 | 已正确（基类按 `v != ""` 过滤） | 保持，并改为按 canonical 后的值判断 | 推断（官方 SDK 强制，文档正文未写） | 官方 SDK 行为（spec §2.1 / WP05） |

### 2.1 `sign_method` 发而不签（本 WP 修的核心缺陷）

基类 `shared/cn_commerce_base.py` 的顺序是：`:2900` 先算 `sign` → `:2901` 才把 `sign_method` 塞进发送参数；而 `_sign`（`:3010`）又显式把 `sign_method` 排除。净效果是 `sign_method` **发了但没参与签名**，对"除 `sign` 外全部入签"的 TOP 就是确定的验签失败源（`25 Invalid Signature`）。

**本 WP 采用「让 `sign_method` 参与签名」**，不采用「不发 `sign_method`」。理由：官方规则是全量入签，官方自己的算例拼接串里就有它；而"不发"只在摘要恰为默认 md5 时成立，一旦改用 `hmac` / `hmac-sha256` 就必须发，等于把正确性押在一个可变的默认值上。

### 2.2 摘要算法：只实现 md5

TOP 的 `sign_method` 有三种合法值 `md5` / `hmac`（= HMAC-MD5）/ `hmac-sha256`。**md5 与 hmac 的待签串不同**：md5 前后各包一次 secret，hmac 只用 secret 作 HMAC key、不包裹（与抖店相反，抖店的 hmac 也包裹 —— 别写混）。`hmac-sha256` 的细节官方正文缺失，仅官方 SDK 有（key=secret，不包裹，64 位大写 hex）。

按 spec §8：本 WP 只实现 md5，另两种由 `_sign` 显式抛错而非静默降级。**本文与代码均不出现「淘宝 md5 将下线」的说法 —— 该说法无任何官方来源**，官方至今三者并列且自己的完整算例用的就是 md5。

### 2.3 混淆源（踩过的坑，留作路标）

`developer.alibaba.com` 上淘宝**全球开放平台**的签名串要在待签串前面加 API 名称。把那套规则套到 TOP 的 `/router/rest` 上必报 `25 Invalid Signature`。二者是不同平台，不要交叉引用文档。

## 3. 网关

| 项 | 值 | 类别 | 出处 |
|---|---|---|---|
| 默认 | `https://gw.api.taobao.com/router/rest` | 官方明文（主接入文档） | 官方接入文档（spec §8、WP05 官方契约对照表） |
| 兼容保留 | `https://eco.taobao.com/router/rest`（`TaobaoMCP.LEGACY_BASE_URL`） | 官方明文（API 详情页 HTTPS 行） | 同上 |
| 二者关系 | **未知** | — | 无官方说明 |

两个 host 都有官方出处，但官方从未说明它们是别名、是灰度还是有能力差异。按 spec §8 的约定：默认 `gw.api`，`eco` 保留可用，**不声明二者等价**。`tests/contract/test_wire_taobao.py::test_legacy_gateway_stays_available_for_pinned_callers` 只断言"覆写 `BASE_URL` 仍可用"，不断言两者行为一致。

传输形态保持仓库原有做法：系统参数与业务参数一起放在 POST 的 query string 里（TOP 明文支持 POST/GET，无 JSON body 概念）。因此本实现把基类的 `data` 参数并入参数集合而不是序列化成 body —— 否则 body 里的业务参数将不入签，正是 spec §8 列的京东那类缺陷。

## 4. 分页：`use_has_next`

官方建议批量查询传 `use_has_next=true` 以提高成功率（**官方公告 25838**）。本实现按 allowlist 落地：

```python
USE_HAS_NEXT_METHODS = {"taobao.trades.sold.get", "taobao.trades.sold.increment.get"}
```

**为什么不是所有 list 接口**：`use_has_next` 只在官方参数表声明了它的接口上合法，而本 WP 只核实了这两个交易查询（也正是公告针对的对象）。给未核实的接口加参数属于推测填充（spec §8 禁止），而且在 TOP 上它还会改变待签串。其余 list 接口（`taobao.items.onsale.get` / `taobao.refunds.receive.get` / `taobao.traderates.get`）留作 §6 的待确认项。

副作用已写进工具 docstring：开启后响应返回 `has_next` 而不是 `total_results`。

## 5. 平台侧使用前提（非代码可解，必须让使用者知道）

| 约束 | 内容 | 类别 | 出处 |
|---|---|---|---|
| 地址脱敏 | `receiver_address` 自 **2026-08-31** 起全脱敏（落实《个人信息保护法》） | 官方明文 | 官方公告 25845 |
| 权限包 | 「订单信息查询」权限包**仅开放给 20 种特定应用类型**（进销存软件 / 商家后台系统 / 商家应用-ERP软件 / 企业ERP 等）；**通用 MCP 连接器不在其中** | 官方明文 | 官方权限包说明（spec §2.3.3、WP05） |
| 时间窗 | 全量订单接口硬限制只能查 3 个月 | 官方明文 | 官方接口说明（WP05） |

第二条是**使用前提而不是 bug**：使用者须自有上述类型的 ISV 应用并申请通过，否则订单类工具无论契约多正确都会被权限拦下。

第一条已改口径：`get_order_list` / `get_order_detail` 的 docstring 明确写了地址将被平台脱敏，不再暗示能拿到可用的详细地址。

## 6. 已知缺口与待确认项（不填推测）

1. **`fields` 参数未传。** `taobao.item.seller.get` / `taobao.shop.seller.get` 这类 TOP 接口通常要求 `fields` 指定返回字段，缺失会得到 `40 Missing required arguments`。本 WP 未取到这两个接口的官方参数表与合法字段清单，**不编造字段名**，故未补。→ 需要一次官方参数表核对（目录接口可程序化拉取）。
2. **`taobao.shop.seller.get` 是否接受 `nick`。** 被替代的 `taobao.shop.get` 接受 `nick`；替代接口按语义只返回授权卖家自己的店铺。官方参数表未核实，故保持 `nick` 透传、未据推测删除工具入参。
3. **历史订单缺能力。** 官方另有 `taobao.trades.sold.history.get`（覆盖 3 个月 ～ 2 年），本仓库未覆盖。记为能力缺口，本 WP 不实现。
4. **官方签名算例仍是 `PENDING`。** `tests/contract/vectors.py` 里淘宝向量的期望值已知（`66987CB115214E59E6EC978214934FB8`），但完整入参串未取回，WP01 明确拒绝反构造。因此本 WP 的签名断言用的是"独立实现复现线上实际发送的 sign"这一路径（见 §7），不是官方算例。取回官方算例后应把该向量移入 `VERIFIED`。
5. **`hmac` / `hmac-sha256` 未实现**（见 §2.2）。

## 7. 绕过了哪些基类行为

不改 `shared/cn_commerce_base.py`（WP 边界），改法是在 `servers/taobao/server.py` 里覆写。被绕过的基类行为逐条如下：

| 覆写 | 绕过了什么 | 为什么 |
|---|---|---|
| `TaobaoMCP._sign` | 基类 `_sign` 把 `sign_method` 排除在待签串外 | TOP 要求除 `sign` 外全部入签（§2.1） |
| `TaobaoMCP._sign` | 基类只按原始值 `v != ""` 过滤 | 改为按 canonical 后的值判断，使 `None` 之类也被正确跳过 |
| `TaobaoMCP._sign` | 基类 `SignMethod.HMAC_SHA256` 分支 | TOP 的 hmac 系待签串规则与基类实现不同；显式抛错优于静默算错（§2.2） |
| `TaobaoMCP._request` | 基类发 `access_token` | TOP 叫 `session`（§2） |
| `TaobaoMCP._request` | 基类发 epoch 毫秒 `timestamp` | TOP 要 GMT+8 的 `yyyy-MM-dd HH:mm:ss`（§2） |
| `TaobaoMCP._request` | 基类"先算 sign 再补 `sign_method`"的顺序 | 顺序颠倒即验签失败（§2.1） |
| `TaobaoMCP._request` | 基类把 `data` 作为 JSON body 发送（POST 时 body 不入签） | TOP 无 body 概念；`data` 并入参数集合，全部入签（§3） |
| `TaobaoMCP._request` | 基类会把空值参数照发（`app_key=""` 之类） | 空值参数在发送前就丢掉：签名规则跳过它们，发了就等于给网关一个我们没签的参数，摘要必然不一致（官方 SDK 同样在发送前丢弃） |
| `TaobaoMCP._ensure_client` | 基类建连时的 `HEAD` 探针与重连退避循环 | 探针打的是 `/router/rest`，那是 API 路由不是健康检查端点，其响应说明不了网关是否会接受签名请求；连接失败已由 `_request` 的 `retry_config` 处理。**连接池与 `_ensure_client` 这个 seam 本身保留** |

基类保留使用的部分：`_validate_params`（注入校验）、`rate_limiter`、`metrics`、`_tracer`、`error_response` 判错、`from_env`、`register_common_tools`。

跨平台不变式「签名集合 ≡ 发送集合 − `sign`」现在对淘宝成立（`tests/contract/conftest.py::assert_signature_set_matches_sent`）。注意这条缺陷本身不是淘宝独有 —— 基类对所有平台都"发而不签"`sign_method`，机制层的根治属于 WP02 的策略层。

## 8. wire 层断言覆盖什么

`tests/contract/test_wire_taobao.py`（17 条）在 `httpx` 层捕获实际出网请求，因此位于既有单测 mock 边界（`taobao._request`）**之下** —— 那个边界正是本仓库所有系统参数缺陷藏身之处。

- 网关 host / path / HTTP 方法；`LEGACY_BASE_URL` 仍可用
- 两个已下线 method 不再出现在 wire 上（改名后的 `taobao.item.seller.get` / `taobao.shop.seller.get`）
- 参数名集合**完全相等**（多发少发都失败）
- 凭证叫 `session`，且 `access_token` 不出现
- `format=json`、`v=2.0`
- timestamp 匹配 `^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$`
- timestamp 是北京时间，且在 `TZ=UTC` 下仍然是（容器常跑 UTC；读进程时区会让每个请求偏离容差窗 8 小时）
- 发送的 `sign` 能被**独立实现**（测试文件内按文档规则另写一份，不调用生产代码）复现
- 去掉 `sign_method` 后签名**不**再复现 → 坐实它真的入签了
- `assert_signature_set_matches_sent`（跨平台不变式）
- ASCII 码位序：`foo` < `foo_bar` < `foobar`
- 空值参数既不入签也**不发送**（否则网关会给一个我们没签的参数算摘要），且生产签名器与独立实现一致
- `use_has_next` 只出现在 allowlist 的接口上

反向验证（mutation check）：把实现整体改回旧行为（旧 endpoint 名、`eco` 网关、`access_token`、epoch 毫秒、`sign_method` 排除签名、无 `use_has_next`）后，17 条里有 11 条失败。
