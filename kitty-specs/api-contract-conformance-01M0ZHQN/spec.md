# API 契约符合性修复

## 1. 目的（TL;DR）

本仓库对外声明支持 8 个中国电商平台、147 个只读工具、358 个测试全绿。实际情况是：**8 个平台中 7 个的调用契约与平台官方文档不符，其中多数在鉴权层就无法发出一个合法请求。**

本 mission 的目标是把 8 个平台的 wire 契约修正到符合官方文档，并建立能持续守住这一点的契约测试。

**验收标准是"符合官方文档"，不需要真实商家凭证。** 这一点是可达的，因为四个平台提供了官方签名算例，六个平台提供了公开无鉴权的文档接口（见 §5）。

## 2. 背景与证据

### 2.1 根因

`shared/cn_commerce_base.py` 的 `_request` / `_sign` 假设"所有中国电商平台的系统参数长一个样"：统一发 `access_token` 参数、统一发 epoch 毫秒 `timestamp`、统一附带 `sign` + `sign_method`、统一按 `error_response` 判错。

这个假设恰好只对**拼多多**成立（base class 的签名算法逐字等于拼多多规范）。其余平台的参数名、时间格式、签名范围、签名拼接方式、传输位置、错误信封各不相同，没有一家与该假设吻合。

四个平台（巨量、淘宝、京东、快手）直接复用 base `_request`，因此全部继承了错误假设。唯一完全正确的是**微信小店** —— 因为微信不需要签名，没有可继承的错误。

### 2.2 附带发现：部分 endpoint 路径是虚构的

- 快手：代码调用 `/open/api/order/list`，官方是 `/open/seller/order/pcursor/list`（`method` 的点换斜杠）
- 小红书：代码调用 `/api/order/list` 等 REST 路径，而小红书**根本没有 REST 路径** —— 它是单一网关 `ark.xiaohongshu.com/ark/open_api/v3/common_controller` + `method` 放 body

两个平台使用同一个虚构模板 `/api/<名词>/<动作>`，在任何官方文档、镜像或 SDK 中均不存在。

### 2.3 巨量引擎的 endpoint 已被官方删除

官方公告（预通知 2024-04-15 `changelog/1796386957503732`、正式 2024-05-07 `changelog/1798385305745562`）确认一批接口于 **2024-05-06 下线**。本仓库调用的 18 个巨量 endpoint 中，**5 个确认已下线**：

| endpoint | 状态 |
|---|---|
| `2/ad/get/` | 已下线 |
| `2/campaign/get/` | 已下线 |
| `2/report/ad/get/` | 已下线 |
| `2/report/audience/` | 已下线（整组） |
| `2/report/creative/get/` | 已下线 |
| `2/report/advertiser/get/` | `platform_version` V1 枚举下线 |

这些页面在当前 1053 篇官方文档中已完全不存在（是删除，非标灰）。官方现存的 `2/report/*` 仅剩 `site/page/`、`rta_exp/get/`、`rta_cus_exp/get/`，本仓库一个都没用。

即 oceanengine server 是双重失效：鉴权方式错，且即使鉴权正确，报表接口本身也不存在了。

### 2.4 测试为何没有拦住

- 所有平台测试都 mock 在 `_call` / `_request` / client 层，系统参数的构造从未被执行
- `tests/test_integration.py:128-132` 是全仓唯一检查出网参数的测试，它断言巨量请求**必须包含** `sign`、`sign_method`、`app_key`、`access_token` 参数 —— 而巨量的官方契约是 token 走 HTTP header 且**完全不签名**。该测试把错误契约钉成了"正确"，任何修复都会先撞红它。

### 2.5 各平台契约差异汇总

| 平台 | 差异数 | 证据来源 |
|---|---|---|
| 微信小店 | 0（+1 可选升级） | 官方文档 |
| 拼多多 | 1 | 官方文档 + 官方算例 |
| 淘宝 | 2 | 官方文档 + 官方算例 |
| 抖店 | 3 | 官方文档全文 |
| 京东 | 6 | 官方文档 + 签名已复现验证 |
| 巨量引擎 | 4 + 5 个死 endpoint | 官方文档全量统计 + 2 份下线公告 |
| 快手 | 8 | 官方文档 + 官方 Java SDK |
| 小红书 | 契约全不符 | 官方文档 + 官方机器可读 spec |

逐平台的差异明细与官方出处，在 plan 阶段落到各 WP 的 contract 文档中。

## 3. 功能需求

| ID | 需求 | 验收依据 |
|---|---|---|
| FR-001 | 建立契约测试框架：每平台一份契约声明 fixture（网关、系统参数表、timestamp 格式、签名规则、错误信封，逐项标注官方出处 URL），并提供签名向量断言与 wire 层参数断言能力 | 四个平台的官方签名向量为硬断言且通过 |
| FR-002 | 提供通用断言：签名参与集合恒等于实际发送集合减去 `sign` | 对每个签名类平台生效 |
| FR-003 | 重写 `tests/test_integration.py:128-132`，使其断言巨量官方契约（token 走 `Access-Token` header、不发 `sign`/`sign_method`/`app_key`） | 该测试不再要求错误参数 |
| FR-004 | 巨量引擎契约修正：token 移至 HTTP header、移除签名、host 统一 `api.oceanengine.com`、错误判定改用 body 的 `code` 与 `message` | wire 断言 + 契约声明 |
| FR-005 | 巨量引擎报表迁移：5 个已下线 endpoint 迁至 `v3.0/report/custom/get/`，参数结构改为 `data_topic`/`dimensions`/`metrics` | 不再引用已下线 path |
| FR-006 | 淘宝契约修正：token 参数名改 `session`、timestamp 改 `yyyy-MM-dd HH:mm:ss`（GMT+8）、网关默认改 `gw.api.taobao.com` 并保留 `eco` 兼容 | 官方算例 + wire 断言 |
| FR-007 | 抖店契约修正：补发必填 `method`（点分）与 `param_json`（递归 key 排序、compact、`1.0`→`1`、不转义中文与 `&<>`、置于 POST body）、签名串改为 `secret + app_key{}method{}param_json{}timestamp{}v{} + secret`、显式传 `sign_method=hmac-sha256` | 官方签名工具比对 + wire 断言 |
| FR-008 | 小红书契约修正：改为单一网关 `ark.xiaohongshu.com/ark/open_api/v3/common_controller`、全部参数移入 POST body、参数名改 `appId`/`method`/`version`/`timestamp`（秒）/`accessToken`、签名仅覆盖 4 个系统参数且输出小写、错误判定改 `error_code==0 && success==true` 并解包 `data` | wire 断言 + 契约声明 |
| FR-009 | 京东契约修正：timestamp 改 `yyyy-MM-dd HH:mm:ss.SSSZ`、签名改纯 MD5（secret 首尾包裹）、业务参数改由 `360buy_param_json` 承载且参与签名、移除 `format` 与 `sign_method`、错误解析改 `code`/`zh_desc`/`en_desc` | 官方签名向量 + wire 断言 |
| FR-010 | 快手契约修正：path 改为 `method` 点换斜杠的官方形式、参数名改 `appkey`/`signMethod`、补 `method` 与 `version`、业务参数打包进单个 `param` JSON 字符串、签名改 `k=v&…&signSecret=X` 且输出小写、成功判定改 `result==1` 并解包 `data` | wire 断言 + 契约声明 |
| FR-011 | 拼多多契约修正：timestamp 改 UNIX 秒 | 官方签名向量 + wire 断言 |
| FR-012 | 微信小店升级：改用 `POST /cgi-bin/stable_token`、缓存 TTL 读取返回的 `expires_in`、错误处理覆盖 HTTP 403（IP 白名单不走 errcode） | 契约声明 |
| FR-013 | 文档口径修正：README 能力声明与实际状态一致、`docs/platforms.md` 记载与代码及官方文档一致、FAQ 中巨量资质要求更正为企业认证 + 企业打款认证 | 人工复核 |

### NFR

| ID | 需求 |
|---|---|
| NFR-001 | CI 不得引入对真实凭证或外部网络的依赖；联网校验任务默认跳过 |
| NFR-002 | 每项契约结论必须标注官方出处 URL，并区分「官方明文」与「依据充分的推断」 |
| NFR-003 | 现有 CI 全绿（`test` 3.11/3.12/3.13、`lint`、`typecheck`、`code-quality`、`install-smoke`） |

## 4. 范围

### 4.1 In scope

1. 建立契约测试框架（先行，后续所有 WP 用它验收）
2. 修正 8 个平台的 wire 契约至符合官方文档：网关地址、系统参数名与位置、timestamp 格式与单位、签名算法（参与范围/拼接/摘要/大小写）、业务参数传递方式、错误信封解析
3. 重写 `tests/test_integration.py:128-132`，使其断言官方契约而非现有假设
4. 巨量报表 endpoint 迁移至 `v3.0/report/custom/get/`（参数结构由 fields/group_by 改为 data_topic/dimensions/metrics，属重写而非改 URL）
5. 修正 README / docs 中与事实不符的能力声明（`8/8 全部完成`、147 tools 等口径）
6. 修正 `docs/platforms.md` 中与代码及官方文档不一致的记载（如淘宝签名方式）

### 4.2 Out of scope（另立）

1. **京东 SP-API 迁移** —— 官方将 `routerjson` 标注为"历史接口，逐步迁移"，新网关 `api-cn.jd.com/rest` 走 header 签名，是整套换代，需独立评估
2. **真实凭证联调** —— 本 mission 以官方文档符合性为验收标准；真机验证需商家授权，另行安排
3. **拼多多多多云部署** —— 订单接口云外可调（返回密文），仅解密接口强制云内。只读分析场景应走脱敏接口 `pdd.open.decrypt.mask.batch`（无云内限制），不在本次实现范围
4. **抖店 md5 → hmac-sha256 的下线时间表跟踪** —— 官方只有"后续会下线"措辞，无时间表
5. 修复 `tests/test_integration.py::test_build_pythonpath_includes_shared_and_repo` 中硬编码仓库目录名的脆弱断言

## 5. 契约测试框架（WP01，其余 WP 的前置）

不依赖真实凭证的两类验收手段：

### 5.1 官方签名算例（4 个平台可硬断言）

| 平台 | 官方向量 |
|---|---|
| 淘宝 | `secret=helloworld` → `66987CB115214E59E6EC978214934FB8` |
| 京东 | 官方示例拼接串 → `D70825340F4084360B9362B60DFD7930`（已独立复现验证） |
| 拼多多 | 官方示例拼接串 → `E4DE3ED21002510DED352819E7AE6775` |
| 抖店 | 官方在线签名工具 `op.jinritemai.com/docs/guide-docs/gen-sign`（公开），可生成任意用例 |

### 5.2 公开的官方文档接口（6 个平台可自动比对）

| 平台 | 端点 |
|---|---|
| 抖店 | `op.jinritemai.com/doc/external/open/queryDocArticleDetail?articleId=` |
| 京东 | `sff.jd.com/api?...api=dsm.jdo.open.home.doc.detail` |
| 拼多多 | `open-api.pinduoduo.com/doc/article/getArticle` |
| 快手 | `open.kwaixiaodian.com/rest/open/platform/doc/page/detail?pageSign=` |
| 小红书 | `open.xiaohongshu.com/api/doc/common/paramNew` 等 4 个端点 |
| 巨量引擎 | `open.oceanengine.com/skiff/api/doc/client/node/get/` |

框架需提供：
- 每平台一份**契约声明**（fixture），记录网关、系统参数表、timestamp 格式、签名规则、错误信封，并标注官方出处 URL
- 针对签名的**向量测试**（对 §5.1 的平台为硬断言）
- 针对系统参数构造的**wire 断言**：拦截出网请求，校验参数名集合、位置（query/body/header）、timestamp 格式
- 一个**可选的**、默认跳过的联网校验任务，拉取 §5.2 的官方 JSON 与本地契约声明比对，用于发现平台侧变更（不进 CI 必过路径，避免外部依赖导致 CI 不稳定）

## 6. WP 划分与顺序

按「影响 × 证据强度」排序，WP01 为其余全部 WP 的前置：

| WP | 内容 | 依赖 |
|---|---|---|
| WP01 | 契约测试框架 + 重写 `test_integration.py:128-132` | — |
| WP02 | 巨量引擎：去签名、token 移至 header、host 统一 `api.oceanengine.com`、错误字段 `message`、报表迁移 v3.0 | WP01 |
| WP03 | 淘宝：token 参数改 `session`、timestamp 改 `yyyy-MM-dd HH:mm:ss` GMT+8、网关默认改 `gw.api.taobao.com` | WP01 |
| WP04 | 抖店：补 `method` 与 `param_json` 必填参数、签名串修正、显式传 `sign_method=hmac-sha256` | WP01 |
| WP05 | 小红书：改单一网关 + POST body + 全部参数名 + 签名范围 + 错误信封（等于重写该 server） | WP01 |
| WP06 | 京东：timestamp 格式、纯 MD5、`360buy_param_json` 入签、去掉 `format`/`sign_method`、错误字段 `zh_desc`/`en_desc` | WP01 |
| WP07 | 快手：path 修正、`appkey`/`signMethod` 命名、补 `method`/`version`、业务参数打包进 `param`、签名格式与小写、`result==1` 判错 | WP01 |
| WP08 | 拼多多：timestamp 改 UNIX 秒 | WP01 |
| WP09 | 微信小店：改用 `stable_token`、TTL 读 `expires_in`、错误处理覆盖 HTTP 403 | WP01 |
| WP10 | 文档口径修正：README 能力声明、`docs/platforms.md` 记载、FAQ 中巨量资质要求（官方要求企业认证 + 企业打款认证） | WP02–WP09 |

## 7. 验收标准

1. WP01 的契约测试框架就位，4 个平台的官方签名向量为硬断言且通过
2. 每个平台 WP 交付时附带该平台的契约声明文档，逐项标注官方出处 URL，并区分「官方明文」与「依据充分的推断」
3. 每个平台的系统参数构造有 wire 层断言覆盖：参数名集合、传输位置、timestamp 格式
4. `tests/test_integration.py:128-132` 断言的是巨量官方契约（header token、无签名）
5. 现有 CI 全绿（`test` 3.11/3.12/3.13、`lint`、`typecheck`、`code-quality`、`install-smoke`）
6. 不引入对真实凭证或外部网络的 CI 依赖
7. README 与 docs 中的能力声明与实际状态一致

## 8. 风险与已知不确定项

以下项**官方文档缺失或自相矛盾**，实现时必须按标注处理，不得用推测填充：

| 项 | 状态 | 处理方式 |
|---|---|---|
| 抖店 API 方向 md5 公式 | 官方仅给 hmac-sha256 代码 | 只实现 hmac-sha256，不实现 md5 |
| 京东 hmacmd5/hmacsha256 字节规则 | 官方期望值无法复现（文档数据陈旧） | 只实现 md5 |
| 淘宝 `hmac-sha256` 细节 | 官方正文缺失，仅官方 SDK 有 | 以官方 SDK 为准并注明 |
| 淘宝 `eco` 与 `gw.api` 关系 | 无官方说明，两者均有官方出处 | 默认 `gw.api`，`eco` 保留兼容 |
| 巨量 `ad.` 与 `api.` 适用范围 | 1053 篇文档零说明，官方自身混用 | 统一 `api.`，保留 per-endpoint override |
| 巨量 v2 接口在 `api.` 上的可用性 | 三条间接证据支持，无官方明文 | 标注为待真机回归 |
| 淘宝「md5 将下线」 | **无任何官方来源** | 不得写入代码注释或文档 |
| 巨量 refresh_token 有效期 | 正文 30 天 vs 返回示例 7 天 | 读运行时 `expires_in`，不硬编码 |
| 微信小店「无签名」 | 官方未明文，为参数表穷举推断 | 标注为推断 |

另有一项跨平台约束：**签名集合必须恒等于发送集合减去 `sign`**。当前实现最大的结构性问题正是二者不一致（例如京东发 `format` 但不入签、抖店业务参数在 body 而签名用另一份数据）。框架应对此提供通用断言。
