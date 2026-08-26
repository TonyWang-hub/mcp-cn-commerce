# API 契约符合性修复

## 1. 目的（TL;DR）

本仓库对外声明支持 8 个平台、147 个只读工具、358 个测试全绿。实际情况是：**115 个 endpoint 里只有 45 个真实存在（39%）**，且存在的那些在契约层仍普遍不符；另有约 22 个工具对应的能力**平台根本不对三方开放**。

本 mission 经审计后**收窄**为两件事：

1. **把底子好的四个平台修到真能调通** —— 淘宝（11/13）、小红书（9/13）、快手（9/12）、拼多多（8/13），共 37 个真实 endpoint。修正范围含 endpoint 名称、契约（网关/参数/签名/时间戳/信封）、以及分页范式。
2. **把对外口径改到与事实一致** —— 移除全部 8 个平台中不存在的 endpoint 所对应的工具，修正 README / FAQ / `docs/platforms.md` 的能力声明。

**暂缓（另立 mission）**：抖店（0/20）、京东（0/15）、巨量引擎（2/18）—— 这三个的性质是「按真实接口重建」，研究成果已保留在 `deferred/`。京东另需先决定网关方向（routerjson 为官方标注的历史接口，SP-API 为推荐方向且鉴权完全不同）。

**验收标准是「符合官方文档」，不需要真实商家凭证。** 依据是四个平台提供官方签名算例、八个平台提供公开无鉴权的文档清单接口（见 §5、§2.3.1）。

## 2. 背景与证据

### 2.1 根因（两层，此前只识别了第二层）

**第一层：endpoint 层面 —— 115 个 endpoint 里只有 45 个真实存在（39%）。**

已对 8 个平台全部 115 个 endpoint 做官方文档清单比对（判据：各平台公开的文档后端接口 + 官方公告全文语料，非活体探测）。结果：

| 平台 | 存在 / 总数 | 性质 |
|---|---|---|
| 淘宝 | **11 / 13** | 2 个已官方公告下线（2018/2019），有指定替代 |
| 小红书 | 9 / 13 | REST path 全部虚构；实为单一网关 + body 内 `method` |
| 快手 | 9 / 12 | path / 参数结构 / 命名风格 / 分页范式四层全错 |
| 拼多多 | 8 / 13 | 3 个可改名，2 个平台无此能力 |
| 微信小店 | 6 / 11 | 其中**仅 2 个请求体也正确** |
| 巨量引擎 | 2 / 18 | 见 §2.3 |
| 抖店 | **0 / 20** | 成片"域名幻觉"，见 §2.2 |
| 京东 | **0 / 15** | `jd.pop.*` 命名空间不存在，见 §2.2 |
| **合计** | **45 / 115** | |

且这 45 个里仍有相当比例的请求体、参数命名、分页范式不符（微信 4 个、快手全部、小红书全部）。

**另有约 22 个工具对应的能力平台根本不对三方开放**，无法通过改名修复，只能删除或申请定向开放：抖店 8（评价×2、直播×2、店铺基础信息、店铺流量、短视频数据、IM 消息）、京东 4（店铺评分、单条评价详情、实时售价、订单级物流轨迹）、小红书 4（评价列表、营销活动列表、优惠券列表、店铺信息）、快手 3（物流轨迹、物流公司列表实为静态文档表、营销活动列表）、拼多多 2（全站商品搜索、商品评价）、微信 1（订单物流拉取）。

**第二层：契约层面 —— `shared/cn_commerce_base.py` 的统一假设。**

`_request` / `_sign` 假设"所有中国电商平台的系统参数长一个样"：统一发 `access_token` 参数、统一发 epoch 毫秒 `timestamp`、统一附带 `sign` + `sign_method`、统一按 `error_response` 判错。该假设恰好只对拼多多成立（其签名算法逐字等于拼多多规范）。

四个平台（巨量、淘宝、京东、快手）直接复用 base `_request`，全部继承了错误假设。另有一处跨平台缺陷：`:2900` 先算 `sign`、`:2901` 才补 `sign_method`，而 `_sign`（`:3010`）又排除它 —— 导致 `sign_method` 全平台**发而不签**。

**结论：本 mission 的性质是「按真实接口重建」，不是「修契约」。** 契约修对了，绝大多数工具依然打在不存在的路径上。

### 2.2 编造的形态（三种可识别的模式）

**模式一：域名幻觉（抖店）。** 官方**根本不存在**这些一级路径段：`/comment/`（全平台无评价接口）、`/coupon/`（真名 `/coupons/` 复数）、`/finance/`（账单在 `/order/getSettleBill*`）、`/im/`（真名 `/pigeon/`）、`/promotion/`（真名 `/marketing/`）、`/video/`（真名 `/shopVideo/`）。另有规律性错误：多加 `get` 前缀、按"业务语义=路径首段"归属（抖店实际不遵守该规律）。

**模式二：命名空间外推（京东）。** `jd.` 是真前缀，但**只属于京东联盟**（`jd.union.open.*`，90 个）。商家/POP 接口全部是 `jingdong.*`（3147 个）。`jd.pop.*` 在 3514 个官方 API 中命中数为 **0** —— 从真实前缀外推出了一个不存在的命名空间。

**模式三：通用 REST 模板（快手、小红书）。** 两平台使用同一个虚构模板 `/api/<名词>/<动作>`（快手为 `/open/api/...`）。快手官方规则是 `method` 点换斜杠（`open.order.cursor.list` → `/open/order/cursor/list`），中间无 `api` 段；小红书根本没有 REST path。

### 2.3 巨量引擎详情（18 个中 2 个有效）

| 判定 | 数量 | endpoint |
|---|---|---|
| 2024-05-06 官方下线 | 5 | `2/ad/get/`、`2/campaign/get/`、`2/report/ad/get/`、`2/report/audience/`、`2/report/creative/get/` |
| 2025-08-31 官方下线 | 1 | `2/report/advertiser/get/` |
| 官方文档查无此接口 | 10 | `2/ad/read/`、`2/campaign/read/`、`2/dmp/audience/list/`、`2/material/list/`、`2/qianchuan/campaign/list/get/`、`2/qianchuan/report/ad/get/`、`2/star/report/`、`2/star/task/list/`、`2/tools/bid_suggest/`、`2/tools/diagnosis/` |
| ✅ 存在且在维护 | 2 | `2/advertiser/info/`、`2/advertiser/fund/get/` |

替代路径（依据官方《升级版与原版差异说明》 `labels/7/docs/1758611573659724`：原版五层结构变为四层，「计划组」对标「项目」、「营销创意」对标「营销」、「营销计划」拆分至两者）：`2/campaign/get/` → `v3.0/project/list/`；`2/ad/get/`（实为**广告计划**列表，非创意列表 —— 代码 docstring 亦标错）→ 需 join `v3.0/project/list/` + `v3.0/promotion/list/`；报表族 → `v3.0/report/custom/get/`。官方下线公告本身**未指定替代**（41 条 path 的替代栏均为"-"）。

### 2.3.1 审计方法论（供后续巡检复用）

**活体探测不能作为存在性证据。** 三处实证：巨量已下线路由仍返回 `40105 access_token无效` 而非 404；淘宝 `getApiParamList` 对 2018 年就下线的 `taobao.items.list.get` 仍返回参数；京东目录对"已下线"与"从未存在"返回同一个 `API不存在`。

**唯一可靠判据是「官方文档清单」+「官方公告语料」双重比对**：

| 平台 | 公开的文档清单接口 | 备注 |
|---|---|---|
| 抖店 | `queryDocDirTree?dirId=3` + `queryDocArticleList?dirId=&pageSize=500` | 1664 篇；条目带 `status`（1 在线 / **3 定向开放需加白** / 0 已下线）；已下线接口正文长度为 **0**（墓碑判定） |
| 巨量 | `skiff/api/doc/client/tree/get/?identify_key=<lib>` | 866 条 path + 246 篇更新日志 |
| 淘宝 | `handler/document/getApiCatelogConfig.json` | 6601 个 API；**TOP 无"已废弃"标签**，废弃只体现为"从目录移除 + 公告"，故必须翻公告（885 条可程序化拉取） |
| 京东 | `sff.jd.com/api?...api=dsm.jdo.open.cms.api4home.detail4Api` | 3514 个 API；存在性 oracle 直接返回 `API不存在` |
| 拼多多 | `pop/doc/category/list` + `pop/doc/info/list/byCat` | **注意有 16 个隐藏分类**，只按公开分类会漏（290 vs 493）；公告 344 条正文可读 |
| 快手 | 官方 Java SDK（452 个 `*Request` 类）+ `rest/open/platform/doc/api/category/list`（339 个 API） | 双 oracle；**注意 SDK 里 71 个 `@Deprecated` 多是旧包装类而非死接口**，须"全部候选类废弃 **且** 目录中缺失"才判退役 |
| 小红书 | `api/doc/listNew` + `api/doc/second/listNew?apiNavigationId=<id>` | **106 个 method / 11 个分组**（不止 8 个） |
| 微信小店 | 文档站侧边导航树（`crwl` 抓任一 API 页即带全量）+ `changelog.html` | 站内搜索**不索引 API 路径**，搜不到不能当负面证据 |

**"编造"与"下线"的区分判据**（拼多多最清晰）：该平台历史上所有下线都点名到具体接口且公告永久可查，因此「在全部公告语料中 0 命中 **且** 不在现行清单中」= **从未存在**。

### 2.3.2 本轮修正的自身错误（避免重复踩）

1. 抖店 timestamp：官方《API调用指南》注解明确 Unix 秒为推荐、datetime 格式"支持但不推荐"，**现有 epoch 秒实现是正确的**（早前误判为 bug）；API 详情页那张参数表是陈旧模板。
2. 快手：`open.seller.order.pcursor.list` **本身已退役**（迁移公告"11.30 下线"，SDK 标 `@Deprecated` 且已从官方目录移除），现役为 `open.order.cursor.list`（入参已删除 `currentPage`，只支持游标）。同类：`open.seller.order.detail`→`open.order.detail`、`open.item.detail`→`open.item.get`、`open.item.list`→`open.item.list.get`。
3. 微信小店**不是"唯一完全正确的平台"**：11 个 endpoint 中 5 个不存在，存在的 6 个里 4 个请求体也是编造的（`start_create_time`/`page` 等字段官方不存在，会 `40097`；售后列表契约与订单列表完全不同，跨度上限 24h 而非 7d 且无分页字段）。
4. 京东 `format` 参数：是**已入签**（`jd._call` 放进 params，`:2898` 合入后 `:2900` 入签），问题在于官方验证向量里没有它 —— 与"发而不签"方向相反。
5. 小红书 `data.batchDesensitise`：官方文档描述中**逐字包含同一句「店铺单日限额10次」**，无法确认脱敏接口不受限额约束，待官方澄清。只读分析的正确路径是 `order.getOrderList`/`getOrderDetail` 已明文返回的省/市/区，以及 `data.batchIndex`（不解密做匹配）。
6. 淘宝 `taobao.promotionmisc.activity.range.list.get` **真实存在**（官方目录 docId=22252，出现在 53 条大促公告中），早前的怀疑不成立。

### 2.3.3 平台侧的架构性约束（非改名可解）

- **拼多多**：`pdd.open.decrypt.batch` 自 2026-05-12 起云外调用限制为 **1次/10秒 + 单应用单日 100 次**，官方明文"请勿将云外解密作为正式业务场景使用"。云外连接器每日仅能解密 100 条订单收件人信息。
- **淘宝**：订单接口 `receiver_address` 字段自 **2026-08-31** 起全脱敏（公告 25845）。「订单信息查询」权限包仅开放给 20 种特定应用类型，**通用 MCP 连接器不在其中**，使用者须自有该类 ISV 应用并申请通过。
- **京东**：SP-API（`api-cn.jd.com`，RESTful，约 277 个接口）为现役网关，routerjson 官方标注"历史接口，逐步迁移"。SP-API 鉴权走 `X-JOS-*` header 且**header 名参与签名** —— 整个调用约定需重估。
- **抖店**：多个"最近似替代"处于 `status=3`（定向开放），需联系行业小二加白，非拿到 token 即可调用。

### 2.4 测试为何没有拦住

- 所有平台测试都 mock 在 `_call` / `_request` / client 层，系统参数的构造从未被执行
- `tests/test_integration.py:128-132` 是全仓唯一检查出网参数的测试，它断言巨量请求**必须包含** `sign`、`sign_method`、`app_key`、`access_token` 参数 —— 而巨量的官方契约是 token 走 HTTP header 且**完全不签名**。该测试把错误契约钉成了"正确"，任何修复都会先撞红它。
- 同文件 :135-153 又把 `error_response` 信封钉成巨量的错误契约（官方是 `code != 0` + `message`）。因此需要处理的不止那 5 行，而是整个 oceanengine 契约块。
- 另有一批测试直接编码了错误契约，会在对应平台修复时变红，且**必须纳入相应 WP 的 owned_files**：`servers/kuaishou/tests/test_kuaishou.py`（:445/:506/:536/:567 硬编码虚构路径 `/open/api/*`）、`servers/xiaohongshu/tests/test_xiaohongshu.py`（断言 `_call("GET", "/api/order/list", ...)`）、`tests/test_api_compatibility.py`（:650 断言抖店签名 32 位小写、:660+ 断言快手签名大写）、`scripts/smoke_install.py`（硬编码各 server 工具数，而 install-smoke 在 NFR-003 验收清单内）。

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
| FR-001 | 建立契约测试框架：每平台一份契约声明 fixture（网关、系统参数表、timestamp 格式、签名规则、错误信封、**endpoint 清单**，逐项标注官方出处 URL），并提供签名向量断言与 wire 层参数断言能力 | 四个平台的官方签名向量为硬断言且通过 |
| FR-002 | 提供通用断言：签名参与集合恒等于实际发送集合减去 `sign` | 对每个签名类平台生效 |
| FR-003 | 移除编码了错误契约的既有测试，交接给对应平台 WP（不在本 WP 内补正确断言，避免与 CI 全绿冲突） | 现有 CI 保持全绿 |
| FR-014 | **endpoint 存在性巡检**：按 §2.3.1 记录的各平台公开文档清单接口，实现可离线运行（默认跳过联网）的巡检脚本，用于发现 endpoint 下线与官方公告中的下线关键词 | 能对当前代码中的全部 endpoint 输出存在性判定 |
| FR-006 | 淘宝：endpoint 修正（`taobao.item.get`→`item.seller.get`、`taobao.shop.get`→`shop.seller.get`）+ 契约修正（token 参数名改 `session`、timestamp 改 `yyyy-MM-dd HH:mm:ss` GMT+8、网关默认改 `gw.api.taobao.com`、`sign_method` 必须参与签名）+ 补 `use_has_next` | 官方算例 + wire 断言 |
| FR-008 | 小红书：改为单一网关 `ark.xiaohongshu.com/ark/open_api/v3/common_controller` + POST body + 官方 method 名（9 个）+ 参数名 `appId`/`method`/`version`/`timestamp`(秒)/`accessToken` + 签名仅覆盖 4 个系统参数且小写 + 判错 `error_code==0 && success==true` 并解包 `data`；**删除 4 个平台不提供的工具**（评价列表、营销活动列表、优惠券列表、店铺信息） | wire 断言 + 契约声明 |
| FR-010 | 快手：改为官方 method 点换斜杠的真实 path（9 个，注意 `open.order.cursor.list` 而非已退役的 `pcursor.list`）+ 参数名 `appkey`/`signMethod` + 补 `method`/`version` + 业务参数打包进单个 `param` JSON（camelCase）+ 签名 `k=v&…&signSecret=X` 小写 + `result==1` 判错 + **按接口实现各自的分页范式**（订单游标 / 退款混合 / 商品页码 / 评价 offset）；**删除 3 个平台不提供的工具** | wire 断言 + 契约声明 |
| FR-011 | 拼多多：timestamp 改 UNIX 秒 + endpoint 修正（`logistics.trace.query`→`logistics.ordertrace.get`、`refund.list.get`→`refund.list.increment.get`、`promotion.list.get`→按语义选定具体接口）；**删除 2 个平台不提供的工具**（全站商品搜索、商品评价）；**移出 `pdd.ddk.goods.search`**（属多多进宝联盟体系，需独立开发者身份与应用类型） | 官方签名向量 + wire 断言 |
| FR-012 | 微信小店：5 个不存在路径改为官方正确（`GET /channels/ec/basics/info/get`、`GET /shop/ec/category/all`、`POST /channels/ec/coupon/get_list`、物流改用 `order/get` 内嵌 `delivery_info`、供应商订单需先定小店/供货商体系）+ 4 个编造请求体按官方字段契约修正 + 改用 `stable_token` + 覆盖 HTTP 403 | wire 断言 + 契约声明 |
| FR-013 | 文档与对外声明一致性：README / `README_en.md` 的能力声明与实际状态一致、`docs/platforms.md` 记载与官方文档一致、`docs/FAQ.md` 更正巨量资质要求（企业认证 + 企业打款认证）与各平台阶段口径 | 人工复核 |
| FR-015 | **移除不存在 endpoint 对应的工具**（覆盖全部 8 个平台，含暂缓的四个）：删除或明确标记为不可用，并在 `docs/platforms.md` 记录每个被移除工具的原因（不存在 / 已下线 / 平台不对三方开放） | 工具注册数与真实可用 endpoint 一致 |

### NFR

| ID | 需求 |
|---|---|
| NFR-001 | CI 不得引入对真实凭证或外部网络的依赖；联网校验任务默认跳过 |
| NFR-002 | 每项契约结论必须标注官方出处 URL，并区分「官方明文」与「依据充分的推断」 |
| NFR-003 | 现有 CI 全绿（`test` 3.11/3.12/3.13、`lint`、`typecheck`、`code-quality`、`install-smoke`） |

## 4. 范围

### 4.1 In scope

1. 契约测试框架 + endpoint 存在性巡检（FR-001、FR-002、FR-003、FR-014）
2. 五个平台修到可调通：淘宝、小红书、快手、拼多多、微信小店（FR-006、FR-008、FR-010、FR-011、FR-012）
3. 移除全部 8 个平台中不存在 endpoint 对应的工具（FR-015）
4. 对外声明与文档口径修正（FR-013）

### 4.2 Out of scope

**暂缓至后续 mission（研究成果已在 `deferred/`，不要重新调研）**：

（微信小店已于审计后拉回本 mission —— 其 5 个不存在的路径与 4 个编造请求体均已取得字段级官方契约，工作量与淘宝相当。）

1. **抖店重建**（0/20）—— 20 个 endpoint 全需重写路径，其中 8 个能力平台不对三方开放
2. **京东重建**（0/15）—— `jd.pop.*` 命名空间不存在；且 SP-API（`api-cn.jd.com`，header 签名且 header 名参与签名）为现役网关，routerjson 官方标注为历史接口，整套调用约定需重估
3. **巨量引擎重建**（2/18）—— 需按 v3.0 `project/list` + `promotion/list` + `report/custom/get` 重建，其中原版"广告计划"无 1:1 替代需 join 两个接口

**其他不做**：

5. 真实凭证联调 —— 本 mission 以官方文档符合性为验收标准
6. 拼多多多多云部署 —— 云外解密自 2026-05-12 起限 1次/10秒 + 单应用单日 100 次；只读分析不需要收件人明文
7. 淘宝「订单信息查询」权限包的获取 —— 仅开放给 20 种特定应用类型，通用连接器不在其中，属使用者侧前提而非代码问题
8. 修复 `tests/test_integration.py::test_build_pythonpath_includes_shared_and_repo` 中硬编码仓库目录名的脆弱断言

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

WP 的权威定义在 `tasks/`。暂缓平台的 WP 已移至 `deferred/`（不参与本 mission 校验与实施）。

| WP | 内容 | 依赖 | FR |
|---|---|---|---|
| WP01 | 契约测试框架 + endpoint 存在性巡检 + 移除错误契约测试 | — | FR-001, FR-002, FR-003, FR-014 |
| WP02 | base class 契约策略层 | WP01 | FR-002 |
| WP05 | 淘宝：2 个 endpoint 改名 + 契约修正 | WP02 | FR-006 |
| WP07 | 小红书：单一网关重写 + 9 个 method + 删 4 个工具 | WP02 | FR-008 |
| WP09 | 快手：真实 path + 协议四层重写 + 删 3 个工具 | WP02 | FR-010 |
| WP10 | 拼多多：timestamp + 3 个改名 + 删 2 个工具 + 移出 ddk | WP02 | FR-011 |
| WP11 | 微信小店：5 个路径修正 + 4 个请求体修正 + stable_token + HTTP 403 | WP02 | FR-012 |
| WP12 | 工具清理（全 8 平台）+ 文档与对外声明一致性 | WP05, WP07, WP09, WP10, WP11 | FR-013, FR-015 |

WP01/WP02 为前置；WP05、WP07、WP09、WP10 之间无相互依赖可并行；WP12 收尾。WP 编号保留原值以便与 `deferred/` 对应，故不连续。

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

另有一项跨平台约束：**签名集合必须恒等于发送集合减去 `sign`**。当前实现最大的结构性问题正是二者不一致，已核实的三处：

1. **`sign_method` 全平台发而不签** —— `cn_commerce_base.py:2900` 先算 `sign`、:2901 才补 `sign_method`，而 `_sign`（:3010）又显式排除它。对淘宝这类「除 `sign` 外全部参数入签」的平台，这本身就是验签失败源。
2. **抖店签名与发送用两份不同的序列化** —— 签的是 sorted-compact JSON，body 发的是原始 dict 经 httpx 默认序列化。
3. **京东业务参数在 POST body 而不入签** —— 官方要求业务参数经 `360buy_param_json` 参与签名。（注意：`format` 是**签了但官方验证向量里没有它**，与"发而不签"方向相反。）

框架应对此提供通用断言。
