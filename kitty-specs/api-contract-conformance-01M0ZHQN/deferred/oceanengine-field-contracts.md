# 巨量引擎：替代接口的字段级契约（已验证，勿重新调研）

判据：官方文档接口 `open.oceanengine.com/skiff/api/doc/client/*` 全量实取（AD 库 1104 篇导航项、
千川库 293 篇、更新日志库 246 篇）。

**本轮新发现的取文档通道**（比 HTML 更准，且不需要 identify_key）：

```
GET https://open.oceanengine.com/skiff/api/doc/client/schema/markdown/get/?doc_id=<ID>
```

---

## 0. 先修正三条此前的错误前提

### ① 「千川用 `ad.` host」—— 只对老接口成立，不能推广

千川 v1.0 **内部就是混的**（官方逐篇明文）：

| host | 接口举例 |
|---|---|
| `ad.` | `campaign_list/get/`(1702055567088643)、`report/ad/get/`(1697466415173644)、`report/advertiser/get/`、`ad/get/`、`ad/quota/get/` |
| `api.` | `report/ad/material/get/`(1803706947586073)、`report/today_live/room/data/get/`、`uni_promotion/list/`、`advertiser/type/get/`、千川库的全部 `v3.0/*` |

**推断**：分界线是**文档建档年代**而非路径 —— doc_id 前缀 `1697/1702/1731` 一律 `ad.`，`1745` 之后一律 `api.`。
我们要重建的两个恰好都是老接口 → `ad.` 对，但**不能推广到其他千川接口**。

**一条硬证据说明两个 host 至少部分互通**：同一个 `/open_api/oauth2/access_token/`，AD 库
（doc 1696710505596940）写 `api.`，千川库（doc 1697468230144003）写 `ad.`。同路径两份官方文档给了
不同 host，说明两域名在网关层是同一套后端的两个入口、历史文档没回刷。**但官方零说明，按文档逐接口抄最稳。**

### ② `2/report/audience/get/` 这个 path **从来不存在**

我们代码里注册的这个 path 在任何官方文档里 0 命中。受众分析的旧接口是四个：
`2/report/audience/interest_action/list/`、`/audience/aweme/list/`、`/audience/province/`、`/audience/city/`
（全部于 2024-05-06 下线）。

**且受众分析没有 AD 主线的 v3.0 替代品。** 全量搜 AD 树只有 `v3.0/local/report/audience/get/`（本地推专用）
和 `v3.0/report/report/live_room/audience/portrait/get/`（直播间受众，path 里 `report/report/` 是官方原文
的重复）。自定义报表的 `DMP_DATA` 是「人群包数据」（按人群包看效果），**不等于**旧的行为兴趣/达人/省市下钻。

→ **这块能力是净损失，需如实告知调用方。**

### ③ 线索类指标下线是 **9 个**，不是 3 个

doc 1863611317923907（2026-06-01），生效 2026-06-08，官方原文「传入会导致请求报错」：

```
clue_connected_180s_count   clue_connected_30s_count   clue_connected_60s_count
clue_connected_count        clue_connected_duration    clue_connected_rate
clue_connected_cost         clue_count_all             clue_dialed_count
```

⚠️ 该日志写的接口 path 是 **`v3.0/report/custom/integrate/`**，而 AD 树 1104 项里搜 `integrate`
**0 命中** —— 这个 path 无任何文档页。**推断**为日志笔误或未公开路由。
**结论：这 9 个字段对 `custom/get` 与 `config/get` 一律视为禁用**，别赌它只影响某个不存在的 path。

---

## 1. 星图与 AD 的关系（Q2 答案）

- **文档库共用**：「巨量星图」（label 3/13）的 identify_key 就是 AD 库那把，星图接口物理上是 AD 导航树的
  一个 section。`labels/7/docs/<id>` 与 `labels/3/docs/<id>` 都能打开。
- **鉴权共用**：同一套 OAuth2、同一个 `Access-Token`。官方明文 —— `oauth2/advertiser/get/`
  （doc 1696710506574848）的 `account_role` 枚举里直接列了 `PLATFORM_ROLE_STAR`、`_STAR_AGENT`、
  `_STAR_MCN`、`_STAR_ISV`，与 `ADVERTISER`/`AGENT` 并列在同一个 AccessToken 的授权账户列表里。
- **唯一差别是账户标识参数**：星图用 **`star_id`** 而非 `advertiser_id`。官方定义：「查询到账号角色为
  **6-星图账号** 的账户 id，即为星图 id」。注意文档用的是旧的数字 role，而现在接口返回字符串
  `account_role` 且同时保留 `advertiser_role: number` —— **代码里两者都取**
  （`advertiser_role == 6` 或 `account_role == "PLATFORM_ROLE_STAR"`）。
- **host 星图内部也混**：`2/star/demand/list/`、`2/star/report/order_overview/get/`、
  `.../order_user_distribution/get/` 是 `ad.`；`2/star/star_ad_unite_task/list/`、
  `2/star/vas/create_boost_item_group/` 是 `api.`。
- 星图接口的文档页**没有「MCP调用」入口**（AD 主线 v2/v3.0 普遍有）—— **推断**星图不在官方 MCP 覆盖内。
- 星图有自己独立的一套「数据主题」体系（`2/star/report/data_topic_config/`、
  `.../custom_data_topic_report/`），**与 AD 自定义报表完全不共用**。

---

## 2. 报表迁移

### 2.1 旧接口死亡时间线（官方明文）

| 旧接口 | 下线时间 | 依据 doc |
|---|---|---|
| `2/report/{ad,creative,campaign,misty,video,video/frame,integrated}/get/` | **2024-05-06** | 1796386957503732（预告）+ 1798385305745562（执行确认） |
| `2/report/audience/{interest_action/list,aweme/list,province,city}` | 2024-05-06 | 同上 |
| `2/report/advertiser/get/` | **2025-08-31**（晚 15 个月） | 1839039608273802：「主要维度及指标已迁移至 自定义报表接口-基础数据主题」 |

### 2.2 `v3.0/report/custom/get/`（同步版）

doc **1741387668314126** · host **`api.oceanengine.com`** · **GET**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `advertiser_id` | number | ✅ | |
| `data_topic` | string | ❌ | 默认 `BASIC_DATA` |
| `dimensions` | string[] | ✅ | |
| `metrics` | string[] | ✅ | |
| `filters` | object[] | ⚠️ | HTML 未标必填，schema 标 required。**按可选处理但至少传空数组** |
| `filters[].field/type/operator/values` | | 条件必填 | `type`: 1 固定枚举/2 固定输入/3 数值；`operator`: 1 等于 … 11 多值都包含 |
| `start_time`/`end_time` | string | ✅ | `yyyy-MM-dd hh:mm:ss`。2025-07-09 起由天级改秒级，**两种格式兼容**（doc 1837158870776896） |
| `order_by` | object[] | ✅ | **必填不可省**。`field` 须在已选 metrics/dimensions 中 |
| `page`/`page_size` | number | ❌ | 默认 1 / 默认 10，**最大 100** |

**响应**：`data.rows[].dimensions`（dict）+ `.metrics`（dict）+ `data.total_metrics`（不受 page 影响）
+ `data.page_info{page,page_size,total_number,total_page}`。
**metrics/dimensions 是动态 map 不是固定字段；所有数值以 string 返回**（官方示例 `"stat_cost":"0.00"`）—— 反序列化不要用 number。

**时间窗：官方完全没给上限**（三篇里搜「跨度/最长」0 命中）。不要用 `v3.0/local/report/*` 的
365 天/7 天规则去推 —— 那是本地推的规则。

**筛选技巧（官方明文，易漏）**：取「起量带来的增量数据」需在筛选项上传 `field=is_boost && values=1`。

### 2.3 `data_topic` 枚举 —— 四个接口四套，必须分别定义常量

| 接口 | 枚举数 | 备注 |
|---|---|---|
| `custom/get` 与 `config/get` **请求侧** | **16** | 权威。含 `BASIC_DATA`（旧 advertiser 报表的官方迁移目标）、`MATERIAL_DATA`（旧 creative 的近似替代）、`QUERY_DATA`、`BIDWORD_DATA`、`PRODUCT_DATA`、`ONE_KEY_BOOST_DATA`、`DMP_DATA`、`VIDEO_DUARATION_DATA`、`MATERIAL_BOOST_DATA` + 6 个 `STD_*` |
| `config/get` **应答侧** | 8 | 少了全部 `STD_*` 与 `MATERIAL_BOOST_DATA`。**推断**为文档未同步 → 对应答做严格枚举校验会炸 |
| `async_task/create` | **6** | `BASIC_DATA`/`BIDWORD_DATA`/**`DPA_VIDEO_DATA`**/`MATERIAL_DATA`/`PRODUCT_DATA`/`QUERY_DATA`。即 `DMP_DATA`、`ONE_KEY_BOOST_DATA`、`VIDEO_DUARATION_DATA`、全部 `STD_*` **不能走异步** |
| `async_task/get` 的 `filtering.data_topics` | 7 | create 的 6 个 + `ONE_KEY_BOOST_DATA` |

⚠️ **`VIDEO_DUARATION_DATA` 官方拼错了**（正确拼法是 DURATION），**必须照抄错的**。
⚠️ 另有个只在更新日志出现、未进接口文档的 `UNI_BASIC_DATA`（全域基础数据，doc 1873393964685514，
日志把 `_DATA` 全写成 `_DATE`）。**不要猜着用，先 config/get 探。**

### 2.4 维度/指标字段名 —— 官方已不再静态发布

**证据链**：① 两篇正文都只说「调用 config/get 获取 / 从平台报表→API参数生成」；
② 2022-08-17 上线日志曾链接《自定义指标和维度说明》doc **1741394565702733**，用全部 5 个
identify_key 逐个请求**均返回「文档不存在」** —— 这篇被删了，旧站 404，archive.org 无快照；
③ config/get 自己的应答示例是空的 `"data": {}`；④ 246 篇日志里搜 `stat_cost` 仅 1 处命中。

→ **`config/get` 是唯一权威来源，必须作为运行时依赖，不能硬编码清单。**

**有官方出处的确切字段名**（custom/get 应答示例）：

维度 `cdp_project_id`（项目ID，`cdp_` 前缀是升级版实体命名习惯）、
`stat_time_hour`（返回值形如 `"2022-08-02 14:00 - 14:59"`，**是区间字符串不是时间戳**）

| 语义 | v3.0 自定义报表 | 旧 v2 `fields` |
|---|---|---|
| 消耗 | `stat_cost` | 同名 |
| 展示 / 点击 | `show_cnt` / `click_cnt` | `show`/`show_cnt`、`click`/`click_cnt` |
| CTR / CPM / CPC | `ctr` / `cpm_platform` / `cpc_platform` | 同名 |
| 转化数 | `convert_cnt` | **同名** |
| **转化成本** | **`conversion_cost`** | **`convert_cost`** ← 不同名 |
| **转化率** | **`conversion_rate`** | **`convert_rate`** ← 不同名 |
| 深度转化 数/成本/率 | `deep_convert_cnt` / `deep_convert_cost` / `deep_convert_rate` | 同名 |

**这个不对称有明确历史成因**（doc 1740034645231629，2019-12-04 条目）：当年 `2/report/integrated/get/`
把 `conversion_cost` **改名为** `convert_cost`、`conversion_rate` → `convert_rate`；v3.0 自定义报表
**又用回了 `conversion_*``**。所以旧 v2 与千川用 `convert_*`，v3.0 用 `conversion_*`，而 `convert_cnt`
两边同名。**做映射表时别用正则统一处理。**

**v3.0 报表族的通用词表底本**（doc 1804000847733786 = `v3.0/local/report/project/get/`，
目前唯一还静态列全字段名的 v3.0 报表文档）：

```
时间维度  stat_time_day（时间-天）、stat_time_hour（时间-小时）
基础指标  stat_cost / show_cnt / click_cnt / ctr / cpc_platform / cpm_platform
转化指标  convert_cnt / conversion_rate / conversion_cost
计费时间版 attribution_convert_cnt / attribution_conversion_rate / attribution_convert_cost
```

⚠️ **计费时间版的命名不对称**：`attribution_convert_cnt`、`attribution_convert_**cost**`
（不是 conversion_cost），但 `attribution_**conversion**_rate`（不是 convert_rate）。官方原文，已核对两遍。

**`stat_time_day` 用在自定义报表 `BASIC_DATA` 的 dimensions 里属推断** —— custom/get 示例只出现了
`stat_time_hour`。上线前必须用 config/get 确认。

**ROI 指标字段名：取不到，明说。** v3.0 自定义报表的 ROI 字段名无任何官方出处。命中的都属于别的接口
（旧 v2 advertiser 报表的 `attribution_game_in_app_roi_1day..8days`、`pay_amount_roi`、`union_roi_0/3/7`、
`luban_order_roi`；千川的 `create_order_roi`、`all_order_pay_roi_7days` 等；出价接口的 `roi_goal` 是
**出价系数不是报表指标**）。其中 `union_roi_*`、`luban_order_roi`、`attribution_wechat_pay_30d_roi`
已被官方明文标为**未迁移、随 2025-08-31 一起下线**。

**一个高价值推断（附证据强度）**：旧 v2 的 `fields` 名在迁移中**1:1 保留、没有重命名**。依据是
doc 1839039608273802 在宣布迁移时，附的「**未**迁移清单」（27 个字段）用的**全是 v2 原名**，
而不是「v2 名 → v3.0 新名」的对照表 —— 官方在讲「哪些不搬」时用 v2 原名，强烈暗示搬过去的
那些名字没变。**这是推断不是明文。** 落地做法：把现有 v2 `fields` 白名单拿去当 `metrics` 候选，
用 config/get 返回做交集，交集外记为「已下线/需人工确认」。

### 2.5 `config/get` 就是「合法组合」的表达机制

doc **1755261744248832** · host `api.` · GET
请求：`advertiser_id`✅ + **`data_topics`（复数、数组）**✅ —— 与 custom/get 的单数 `data_topic` 不同。

应答 `data.list[]`（每个 topic 一个元素）：
```
.dimensions[] / .metrics[]
   .field / .name / .description
   .sort_able        bool    ← 能否进 order_by（仅 dimensions 有）
   .filter_able      bool
   .filter_config{ type, operator, value_limit, range_value[]{label,value} }
   .exclusion_dims    string[]   ← 与该项互斥的维度
   .exclusion_metrics string[]   ← 与该项互斥的指标
```

**合法组合 = 全集 − 互斥关系。** 校验算法：取 topic 下 dimensions∪metrics 全集，对每个已选维度检查其
`exclusion_dims`/`exclusion_metrics` 是否与其它已选项相交，对每个指标检查 `exclusion_dims`。
注意**指标侧没有指标↔指标互斥**。`metrics[]` 无 `sort_able`，但 custom/get 明文说「metrics 所有字段
支持排序」，故指标一律可排序。

### 2.6 时间粒度：**没有 `time_granularity` 参数**

三篇里搜 `time_granularity` 全部 0 命中。粒度**通过维度表达**：小时级 → dimensions 加
`stat_time_hour`（官方明文）；天级 → **推断**加 `stat_time_day`；汇总 → **推断**不放时间维度。

只有**非自定义报表**的接口才有 `time_granularity`：`v3.0/local/report/project/get/`
（`TIME_GRANULARITY_DAILY` 默认 / `_HOURLY` / `_TOTAL`，DAILY|TOTAL ≤365 天、HOURLY ≤7 天）、
千川 `v1.0/qianchuan/report/ad/get/`（DAILY / HOURLY，不传=区间聚合）。

→ **旧代码若把 `time_granularity` 直接转发给新接口，会被当未知参数忽略或报错。粒度必须改写成维度。
这是迁移里最容易漏的一处。**

### 2.7 异步版三接口

| 接口 | doc | 方法 | 要点 |
|---|---|---|---|
| `custom/async_task/create/` | 1769188789062663 | **POST** ⚠️ | abstract 元数据写 `"method":"GET"` 是**文档 bug**，正文与 schema 都是 POST。`task_name` ≤25 字符且不能空；`start/end_time` 是**天级 `yyyy-MM-dd`**（与同步版秒级不同）；`page_size` 默认与最大都是 **1,000,000**；`filters` **明确必填**。**配额：每开发者每天每营销账号最多 10 个任务** |
| `custom/async_task/get/` | 1769189735826436 | GET | `filtering.task_ids` ≤10；`page_size` 默认 1、范围 [1,10]。**`data.list[]` 除 `data_topic` 外的字段官方没列**，应答示例空 → 只能实调探 |
| `custom/async_task/download/` | 1769190063706123 | GET | **`data` 内部结构官方零文档**（示例 `"data": {}`），不知是返回下载 URL 还是数据体 → 必须实调 |

`task_status`：`ASYNC_TASK_STATUS_CREATED`/`_EXECUTING`/`_COMPLETED`/`_FAILED`

**何时必须异步**（从官方数字推出的硬边界）：同步 `page_size` 上限 100 vs 异步 1,000,000 → 万级以上
基本必须异步；异步只接受**天级**时间 → 小时级/秒级窗口只能同步；异步只支持 6 个 topic →
`DMP_DATA`/`ONE_KEY_BOOST_DATA`/`VIDEO_DUARATION_DATA`/全部 `STD_*` 被 100/页卡死；
`DPA_VIDEO_DATA` **只能走异步**；异步有 10 任务/天/账号配额，**不能当轮询用**。

### 2.8 其余字段变更（246 篇日志逐篇过完）

- **退款金额改名**（doc 1873393964685514，生效 2026-08-27，**已过期**）：
  `in_app_order_net_refund_pay_amount_fen` → **`stat_in_app_order_net_refund_pay_amount`**。
  影响 `custom/get` 与 `config/get`，主题 `BASIC_DATA`/`UNI_BASIC_DATA`/`STD_BASIC_DATA`。
- **拼写修正**（2022-12-14 提出、2023-01-11 上线）：`attribution_day_acitve_pay_{cost,count,rate}`
  → `active`（`acitve` → `active`）。2023 年初已完成。
- 其余 `report/custom` 相关日志均为能力增量，无字段删改。

**结论：截至 2026-09-01，自定义报表的破坏性字段变更就是 9 删 + 1 改名。** 前提是官方日志完整 ——
日志库 2026 年只有 9 篇，2026-06-08 那天本身没有日志条目，说明颗粒度较粗，不能 100% 保证无遗漏。

---

## 3. 全局约束与存在性判据

### 三层频控（doc 1696710758159360）

| 层 | 维度 | 错误码 | 说明 |
|---|---|---|---|
| 客户频控 | `advertiser_id` × 单接口 | **40130** | 仅对「不活跃账户」（90 天无活跃）生效；**被这层拦掉不占开发者配额**；可用「获取不活跃账户列表」T+1 预过滤 |
| 开发者频控 | 开发者 × 单接口 | **40110** | 每接口独立配额，值在后台→频控管理查看；每月 1/15 日 9 点后评估可提频，**需手动点确认，约 5 分钟生效** |
| 接口总频控 | 全平台 × 单接口 | **40100** | 系统动态调整，优先级高于开发者频控，整点/半点峰期易触发 |

响应头 **`X-RateLimit-Dimension`** 可判断触发了哪一层。**没有任何接口的具体 QPS 数值被公开** ——
官方明说「无法提供具体的评估计算公式」。

### 存在性判据（对本 mission 的方法论是重要补强）

- **`40105` 不在官方返回码附录里**（doc 1696710760866831 全篇核过：40xxx 段有 40001/40002/40100/
  40102/40103/40104/40107/40110/40113/40115/40118/40119/40130，**没有 40105**）。
  → 「已下线路由返回 40105」这个行为**官方完全未文档化**，按导航树判存在性是对的做法。
- **`going_offline=true` 在 AD 库 1104 项里只有 1 项**（`v1.0/enterprise/bind/list/get/`），千川库 0 项。
  → 官方基本不用这个标记，**已下线接口是直接从树里删掉**。**树里没有 = 已下线**，
  `going_offline` 只是锦上添花，不能当主判据。
- 另有个 `status` 字段（取值 0/1/2/3/4，分布 145/6/1/26/876），**含义官方未说明，不要用它做判断**。
- **文档内嵌的「待下线/即将下线」标注不进更新日志**（千川 `report/ad/get/` 在日志里 0 命中，
  但文档字段表里有 14 个「即将下线」的结算指标 + 3 个「待下线」的转化指标）。
  → **必须同时扫文档正文和更新日志，只看一边会漏。**

---

## 4. 其余替代接口参数表

统一：header 均为 `Access-Token`（必填）；响应均有顶层 `code`/`message`/`request_id`；
`going_offline` 全部 false，**无一被标注「不再维护」**。

### 4.1 `2/advertiser/info/` — 获取投放账户信息
doc 1696710508983311 · host **`ad.`** · GET
- `advertiser_ids`(number[])✅ **1-100 个**，含无权限 ID 会整体返回 no permission error
- `fields`(string[])❌ 允许值 `id,name,role,status,address,reason,license_url,license_no,license_province,license_city,company,brand,promotion_area,promotion_center_province,promotion_center_city,industry,create_time,note`
- **响应 `data` 是数组**（应答示例 `"data": [ {...} ]`）。⚠️ schema 端点渲染成 `data.data.{...}` 嵌套，
  **是老 v2 文档的渲染 bug，以 HTML 正文 + 应答示例为准**（B.2、B.4 同坑）
- 字段：`id`/`name`/`role`/`status`/`note`/`address`/`license_url`（**预览链接默认 1 小时有效**）/
  `license_no`/`license_province`/`license_city`/`company`/`brand`/`promotion_area`/
  `promotion_center_province`/`promotion_center_city`/`first_industry_name`/`second_industry_name`/
  `reason`/`create_time`
- 不一致：`fields` 允许值有 `industry`（旧字段），应答字段表**没有**它，但官方示例返回了
  `"industry": "xxx"` → **推断**为遗留字段仍在返回，建议两套都解析
- 官方提示：**入海投放账户不返回** `brand`/`promotion_area`/`promotion_center_province`/`promotion_center_city`
- **`bp_id`：该接口从来没有这个参数**，2026-04-27 的 bp_id 下线清单也没列它 → 不受影响
- 更新日志：2022 年以来无变更。稳定接口

### 4.2 `2/advertiser/fund/get/` — 查询账号余额
doc 1696710526192652 · host **`ad.`** · GET
- `advertiser_id`(number)✅ **客户ID 或代理商ID**；`grant_type_split`(string)❌ `ON`/`OFF`(默认)
- **响应 `data` 是单个 object**，全部单位**元**：`balance`/`valid_balance`/`cash`/`valid_cash`/`grant`/
  `default_grant`/`common_grant`/`search_grant`/`union_grant`/`valid_grant`/`return_goods_abs`/
  `valid_return_goods_abs`/`return_goods_cost`/`return_goods_grant`/`compensation_grant`/
  `return_goods_valid_grant`/`compensation_valid_grant`/`wallet_id`/`wallet_name`/`wallet_total_balance_valid`
  （`return_goods_*` 仅部分客户）
- ⚠️ 官方应答示例把 `email` 拼成 **`"emal"`**，字段表才是权威
- **`bp_id`：官方明文已下线。** doc 1862437581755404（2026-04-27）「资金管理（16个接口）」明确列了本接口，
  变更内容「停止支持旧版工作台组织账户维度（bp_id）入参」，生效 **2026 年 6 月中上旬**（已过）。
  注意 `bp_id` 从来不是显式文档参数 —— 历史行为是 `advertiser_id` 位置可传 bp_id 值，这条路已断
- 更新日志：2023-07-19 新增 `wallet_id`/`wallet_name`/`wallet_total_balance_valid`

### 4.3 `2/dmp/custom_audience/select/` — 人群包列表
doc 1696710570721295 · host **`ad.`** · GET
- `advertiser_id`✅、`select_type`(number)✅（`0` 该客户创建+被推送给该客户的 / `1` 状态为可投放的）、
  **`offset`/`limit` 分页**（不是 page/page_size），`limit` 默认 100、**范围 1-100**
- 响应：`data.custom_audience_list[]` + `data.offset` + `data.total_num`（**无 page_info**）
- 字段：`custom_audience_id`/`isdel`(1 已删除/0 未删除)/`data_source_id`/`name`/`source`/`status`/
  `delivery_status`/`cover_num`/`upload_num`（**可为 null**）/`tag`
- **`delivery_status` 是判断能否投放的唯一依据**：`CUSTOM_AUDIENCE_DELIVERY_STATUS_AVAILABLE`（可投放）
  / `_NEED_PUSH`（已发布未推送）/ `_NEED_PUBLISH`（未发布已推送）/ `_UNAVAILABLE`（都没有）
- 官方注：`cover_num` 是与 uid 对应后再与头条系 MAU 求交的数量，**可能多于或少于 `upload_num`**
- **更新日志 246 篇 0 命中** —— 完全稳定

### 4.4 `v3.0/tools/bids/suggest/` — 查询建议出价
doc 1771363823169544 · host **`api.`** · GET
- 必填：`advertiser_id`、`project_id`、`pricing`(`PRICING_CPC`/`_CPM`/`_OCPC`/`_OCPM`)、`external_action`
- 选填：`deep_external_action`、`deep_bid_type`、`platform`(`ANDROID`/`HARMONY`/`IOS`)、
  `marketing_goal`(`LIVE`/`VIDEO_AND_IMAGE`)、`campaign_type`(`ALL`/`SEARCH`)、`package_name`、
  `user_name`、`app_id`
- 字段明文：`bid_high_30`/`bid_high_50`/`bid_high_90`(double，竞争力超过 N% 的高跑量出价)、
  `suggest_bid`（**0 表示无建议出价**）、`suggest_roi_goal`（**0 表示无建议**）
- ⚠️ **`data` 是一层还是两层嵌套取不到**：HTML 与 schema 都写成 `data.data.*` 双层，且应答示例是空的
  → 与 4.1/4.2 不同（那两个有非空示例可推翻 schema），**这里必须实调确认**

### 4.5 诊断建议 family —— **四个接口结构完全不同，不能抽象成泛型**

全部 host `api.`、GET。

**a) `v3.0/tools/diagnosis/suggestion/get/`**（doc 1847119758118924，**单元层级**）
- `advertiser_id`✅ + `promotion_ids`(number[])✅ **最多 100**
- 响应 `data.promotion_suggestions[]`：`promotion_id`/`diagnosis_id`/`expire_timestamp`/`hit_scenes`(string[])
  + `rec_suggestions[]`{`rec_suggestion_type`(number)/`_content`/`_reason`/`_mode`/`_name`,
  `rec_suggestion_tools[]`{`rec_suggestion_tool`,`_tool_str`,`tool_params`}}
- `rec_suggestion_type`/`tool` 枚举 15 个：`AD_PAUSE` 6001、`KEEP_OBSERVATION` 6009、`I_KNOW` 6010、
  `OPTIMIZE_MATERIAL` 6011、`ADJUST_MATERIAL` 6012、`ADV_RECHARGE` 6013、`ADD_BUDGET` 6014、
  `ADD_COMPETE` 6015、`UPDATE_TARGET` 6016、`MATERIAL_COMPETE` 6017、`RAISE_BID` 6018、
  `OPTIMIZE_COST_EFFECT` 6019、`_UP_COST` 6020、`_UP_ROI` 6021、`_UP_ROI_STABLE_COST` 6022、
  `_DOWN_COST` 6023
- `tool_params` 内：`cpa_bid`/`roi_goal`（线上实际值）、`suggest_content`/`suggest_cpa_bid`/`suggest_roi_goal`
- ⚠️ **已确认的文档缺口**：doc 1862437581755404（2026-04-27）宣布应答新增 `status`
  （`RUNNING` 生成中 / `SUCCESS` / `FAILED`）并注明「**诊断分析非实时生成，约需 6-7 秒；
  status=RUNNING 时请等待后重试**」，但**当前文档字段表里完全没有 `status`**（grep `RUNNING` 0 命中）。
  **代码必须处理 `RUNNING` 重试，否则会拿到空的 reason。这个信息只存在于更新日志。**

**b) `v3.0/tools/promotion_diagnosis/suggestion/get/`**（doc 1754715780584459）
- `advertiser_id`✅、`promotion_ids` ≤100✅、**`scenes`(string[])✅ 必填**：`CLEAN`/`POTENTIAL`/`ZOMBIE`
- `scene_type` 取值是**中文字符串**不是英文枚举：CLEAN → 「预估活跃度低（**已下线，请通过 scene=ZOMBIE 获取**）」
  「预估空耗」「相似单元挤压严重」「预估学习期失败率高」「低效素材无法跑量」；POTENTIAL → 「出价潜力」；
  ZOMBIE → 「活跃度低单元」
- ⚠️ `ZOMBIE` 只在入参枚举里，应答 `scene` 的可选值表**没列** —— 文档不一致
- `object_list_param` 三种结构：`title_materials`{title, word_ids}、`image_materials`{image_mode, image_id}、
  `video_materials`{image_mode, video_id, cover_image_id}

**c) `v3.0/tools/advertiser_diagnosis/suggestion/get/`**（doc 1854281728162826）
- **当前仅支持 7R 双出价产品投放建议**（官方限定）。`filtering.suggestion_type`：`SEVEN_DAYS_ROI_SUGGESTION`
- `expire_timestamp` **最长 10min 过期**（比 a) 短）
- `adjust_bid_rate`/`adjust_roi_goal_rate`(float) 是**百分比，返回 0.05 即 5%**

**d) `v3.0/tools/project_diagnosis/suggestion/list/`**（doc 1872851830768907，`is_new=true`）
- ⚠️ **path 结尾是 `/list/` 不是 `/get/`**，树里不存在 `project_diagnosis/suggestion/get/`
- `project_ids` ≤100✅、`advertiser_id`✅ → `data.results[]`{project_id, reason}
- 能力极窄：**只查「标签为重复投放」的建议**，不是项目层级的通用诊断

### 4.6 千川 `v1.0/qianchuan/campaign_list/get/`
doc 1702055567088643 · host **`ad.`** · GET
- `advertiser_id`✅、**`filter`（单数，不是 `filtering`）✅**
- `filter.marketing_goal`✅ `VIDEO_PROM_GOODS`/`LIVE_PROM_GOODS`；`filter.ids`（**目前只支持一个**）；
  `filter.name`（1-30 字符，1 中文=2 位）；`filter.marketing_scene` 默认 `FEED`（/`SEARCH`/`SHOPPING_MALL`）；
  `filter.status` `ALL`（含已删除）/`ENABLE`/`DISABLE`/`DELETE`，不传=所有不含已删除
- `page_size` 默认 10，**允许值只能是 10/20/50/100/500/1000**（枚举不是范围）
- 响应 `data.list[]`{id, name, budget(float 元 2 位小数), budget_mode, marketing_goal, marketing_scene,
  status, create_date(`yyyy-mm-dd`)} + `page_info`
- ⚠️ **应答示例与字段表严重不符**：示例返回 `{name,id,campaign_create_time,campaign_modify_time}`，
  后两个**根本不在字段表里**，而字段表里的 budget 等示例一个都没有。示例是 2019 年老残留
  （时间戳 `2019-04-23`）。**以字段表为准，代码应容忍多余字段**
- 更新日志 0 命中

### 4.7 千川 `v1.0/qianchuan/report/ad/get/`
doc 1697466415173644 · host **`ad.`** · GET
**这是全套调研里唯一还完整静态发布指标清单的报表接口（132 个），可当 v1.0 词表的权威底本。**

- 必填：`advertiser_id`、`start_date`（**不得早于今日-180 天**）、`end_date`、`fields`(string[])、`filtering`
- `filtering.marketing_goal`✅ `VIDEO_PROM_GOODS`/`LIVE_PROM_GOODS`/`ALL`；`filtering.ad_ids` ≤100；
  `order_platform` `ALL`/`QIANCHUAN`(默认)/`ECP_AWEME`；`marketing_scene`（小店随心推时不支持）；
  `smart_bid_type`（小店随心推或搜索场景不支持）；`status`（**暂不支持"系统暂停"和"在投计划配额超限"**）；
  `campaign_scene`（小店随心推时不支持）
- `time_granularity`❌ 不传=区间聚合 / `TIME_GRANULARITY_DAILY` / `_HOURLY`
- **`order_type` 默认 `ASC`（升序，与直觉相反）**；`order_field` 默认 `stat_cost`
- `page_size` 默认 10，**范围 1-500**
- **时间窗三档**：不传粒度 ≤180 天；DAILY ≤30 天；HOURLY ≤7 天
- 响应固定维度：`advertiser_id`/`ad_id`/`stat_datetime`（**仅当 time_granularity 有入参时返回**）
- ⚠️ **关键行为**：「若所有字段均无值，则该条计划不返回。即有可能拉取 10 条计划仅返回 7 条」
  → **不能用返回条数推断计划数，也不能用 total_number 对齐**
- 转化指标是 `convert_cost`/`convert_rate` 且**已标「待下线」**（连 `convert_cnt` 一起）
- **结算/退款两套并存，必须用新的**：
  - ❌ 即将下线（14 个）：`live_order_refund_count_7d`/`_amount_7d`/`live_order_settle_amount_7d`/
    `_count_7d`/`_count_rate_7d`/`ad_live_order_settle_roi_7d`/`_cost_7d` 及全部 `_14d` 版本
  - ✅ 新的：`ad_all_order_settle_amount_7d`/`_count_7d`/`ad_all_order_count_settle_rate_7d`/
    `ad_all_order_settle_roi_7d`/`_cost_7d`/`all_order_refund_count_7d`/`_amount_7d`/
    `ad_order_gmv_refund_rate_7d`/`ad_order_refund_rate_7d`/`ad_all_order_gmv_settle_rate_7d` 及 `_14d`
- 电商核心指标：`pay_order_count`/`pay_order_amount`/`create_order_count`/`create_order_amount`/
  `create_order_roi`/`prepay_and_pay_order_roi`/`pay_order_cost_per_order`（客单价）等
- `dy_*` 系仅短视频支持；`luban_live_*`/`live_*` 系仅直播支持
- 更新日志 0 命中（但文档内嵌了「待下线」标注 —— 见 §3 的方法论补强）

### 4.8 星图 `2/star/demand/list/`
doc 1696710606998540 · host **`ad.`** · GET · 无 MCP 入口
- **`star_id`✅ 不是 advertiser_id**
- `filtering.component_type`/`task_category`/`name`（模糊匹配）/`universal_order_status`
  （**是订单状态不是任务状态** —— 语义是"过滤出包含该状态订单的任务"）/`universal_settlement_type`/
  `query_time_range.{start_time,end_time}`（`yyyy-MM-dd HH:mm:ss`，**必须同时传且 start ≤ end**）
- `page_size` 默认 10，**最大 50**
- 响应 `data.list[]`{demand_id, demand_name, component_type, task_category, create_time,
  universal_settlement_type} + `page_info`
- ⚠️ **`total_number` 官方注「一次查询超过 5000 条会被截断」** → 大账号必须靠 `query_time_range` 切窗
- ⚠️ **2024-09-11 行为破坏性变更**（doc 1809890958557315）：`task_category` 新增支持多类型，并
  「**去除默认查询「抖音传播任务_指派_视频」，未筛选默认返回全部支持类型任务**」。
  旧代码若依赖"不传 task_category 只返回抖音视频任务"，现在会拿到全类型
- 配套 `2/star/demand/order/list/`（doc 1696710607541263）提供 order_overview 需要的 `order_id`

### 4.9 星图 `2/star/report/order_overview/get/`
doc 1696710608099328 · host **`ad.`** · GET · 无 MCP 入口
- `star_id`✅ + `order_id`✅（来自 `2/star/demand/order/list/`）。无分页
- ⚠️⚠️ **全接口最关键一条（官方提示卡）：「结果中所有的 rate 均为 ×100 后的结果，如
  `five_s_play_rate=2750` 表示 27.5%」** —— 即所有比率字段是**万分比整数**。
  **不做转换就是错数据。**
- **金额单位是分**（`cost_effectiveness.price`、`.cpm`）—— 与 AD `advertiser/fund/get`（元）**相反**
- 数据非实时：一般次日凌晨产出前一天数据
- 响应 `data` 五个分组：`spread`{play,like,comment,share}、`creative`{finish_rate,
  **`five_s_play_rate`（已废弃）**, **`play_rate`（已废弃）**}、`convert`{show,click,ctr}、
  `comment`{high_frequency_words(string[]), pos_rate, neu_rate, neg_rate}、
  `cost_effectiveness`{play, price, cpm} + `update_time`
- ⚠️ **`spread.play` 与 `cost_effectiveness.play` 是两个不同分组下的同名字段**（"播放量" vs "播放次数"），
  扁平化时别覆盖

### 4.10 `2/file/video/get/` — 获取视频素材
doc 1696710601820172 · host **`api.`** · GET
- ⚠️ **这是唯一一个 v2 路径但 host 是 `api.` 的目标接口**，与同批的 advertiser/dmp/star（全 `ad.`）不同。
  **别顺手统一**
- `advertiser_id`✅；`filtering.width`/`height`/`ratio`(float[]，传 1.7 搜 1.65-1.75，**精度浮动 0.05**)/
  `video_ids`(≤100)/`material_ids`(≤100)/`signatures`(md5, ≤100)/`start_time`+`end_time`
  （按**上传时间**，`yyyy-mm-dd`，**必须搭配使用**）/`labels`/`source`（**枚举值大小写敏感**）/
  `star_author_ids`（**仅当 `source=STAR` 时生效**，≤20）
- ⚠️ **三互斥（官方加粗）：`video_ids`、`material_ids`、`signatures` 只能选一个**
- 响应 `data.list[]`{id, size, width, height, url, format, signature, poster_url, duration(double),
  material_id, bit_rate(**bps**), source, create_time, filename, labels[], organization_tags[]（官方无描述）,
  star_author_id, video_cover_id, cover_source(`MANUAL_SOURCE`/`FIRST_FRAME`/`AI_COVER`)} + `page_info`
- ⚠️ **主体校验**：`url` 与 `poster_url` **仅同主体可见**。投放账户主体须与 APPID 对应开发者主体一致，
  否则**把「素材所属主体与开发者主体不一致无法获取URL」这个字符串塞进字段**（不是报错）。
  第三方可在授权时申请**敏感物料授权**（授权链接拼 `material_auth=1`），对应错误码 **40119**。
  **预览链接有效期 1 小时**
- 数据量：官方明文「在 **100w** 以内时支持全量获取」

---

## 5. 取不到、必须实调确认的清单（不猜）

1. 各 `data_topic` 下的**完整维度/指标字段名** —— 官方仅运行时通过 `config/get` 提供，静态说明文档已被删除
2. **v3.0 自定义报表的 ROI 指标字段名** —— 无任何官方出处
3. `stat_time_day` 是否是 `BASIC_DATA` 的合法维度 —— v3.0 报表族明文，但 custom/get 未列
4. `async_task/get` 的 `data.list[]` 除 `data_topic` 外的字段
5. `async_task/download` 的 `data` 结构 —— 官方完全空白
6. `bids/suggest` 的 `data` 是一层还是两层嵌套
7. `custom/get` 的**最大时间窗** —— 官方无任何数字
8. `report/custom/integrate/` 这个 path 是否真实存在
9. `UNI_BASIC_DATA` 是否是可用的 data_topic
