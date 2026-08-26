---
work_package_id: WP11
title: 微信小店-stable_token-升级
dependencies:
- WP02
requirement_refs:
- FR-012
tracker_refs: []
planning_base_branch: sdd/api-contract-conformance
merge_target_branch: sdd/api-contract-conformance
branch_strategy: Planning artifacts for this mission were generated on sdd/api-contract-conformance. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into sdd/api-contract-conformance unless the human explicitly redirects the landing branch.
subtasks:
- T027
- T028
phase: Phase 2 - Platforms
assignee: ''
agent: ''
history:
- timestamp: '2026-08-26T17:37:08Z'
  agent: system
  action: Prompt generated via /spec-kitty.tasks
authoritative_surface: servers/weixin_store/
create_intent:
- tests/contract/test_wire_weixin_store.py
- docs/api-contracts/weixin_store.md
execution_mode: code_change
owned_files:
- servers/weixin_store/server.py
- tests/contract/test_wire_weixin_store.py
- docs/api-contracts/weixin_store.md
- servers/weixin_store/tests/test_weixin_store.py
tags: []
---

# Work Package Prompt: WP11 – 微信小店-stable_token-升级

实现 FR-012。`servers/weixin_store/server.py` 有自己的 `_request` 与 `_ensure_token`。

## endpoint 审计结果与替代映射（已验证，勿重新调研）

**前提更正**：本平台**不是"契约完全正确、只需核实存在性"**。11 个 endpoint 中 **6 个存在、5 个查无此接口**；且存在的 6 个里**有 4 个请求体也是编造的**。四个暂缓平台中它最轻，可优先纳入后续 mission。

### 5 个不存在的 → 官方正确

| 我们调用的 | 官方正确 | 权限集 |
|---|---|---|
| `POST /channels/ec/basicinfo/get` | **`GET /channels/ec/basics/info/get`**（GET，无 body。POST 会 `43001`） | 129、131、192 |
| `POST /channels/ec/category/list/get` | **`GET /shop/ec/category/all`**（注意前缀是 **`/shop/ec/`** 不是 `/channels/ec/`；GET，无 body，一次返回全量类目树，新树在 `cats_v2`；**无 `parent_id` 参数**，我们那个是编造的） | 85、129、192 |
| `POST /channels/ec/coupon/list/get` | **`POST /channels/ec/coupon/get_list`**。4 个字段**全必填**：`status`（枚举 1编辑中/2已生效/3已过期/4已作废/5已删除/200过期或作废 —— 我们默认值 `0` **不合法**）、`page`≥1、`page_size`**≤200**、`page_ctx`（首次空串）。**每次请求页码间隔不能超过 10** | 132 |
| `POST /channels/ec/order/deliveryinfo/get` | **无拉取接口**。全站仅「修改物流信息」写接口。改用 **`order/get` 返回的内嵌 `order.order_detail.delivery_info`**（含 `waybill_id`、`delivery_id`、`extra_logistics_info`）—— 我们本来就在调 order/get | — |
| `POST /channels/ec/supplier/order/list/get` | 不存在。三个真实候选，**分属两套体系**：小店侧 `POST /channels/ec/order/dropship/list`（权限 131）、供货商侧 `POST /channels/ec/order/dropship/supplier/list`（**权限 192，需「小店供货商」账号**）、`POST /channels/ec/order/supplyorder/list`（131）。**用小店 token 调不了供货商侧接口，反之亦然** —— 需先定我们是"小店"还是"供货商" | 131 / 192 |

### 4 个请求体编造的 → 官方正确契约

**订单列表** `/channels/ec/order/list/get`：我们发 `start_create_time`/`end_create_time`/`page` —— **三个字段官方都不存在，会 `40097`**。官方是 `create_time_range{start_time,end_time}` 或 `update_time_range{...}`（**至少填一个**；秒级时间戳 number；**跨度 ≤7 天**）、`page_size` ≤100、`next_key`。返回 `order_id_list` + **`has_more`** + `next_key`。
状态真实枚举：`10` 待付款 / `12` 礼物待收下 / `13` 一起买待成团 / `20` 待发货 / `21` 部分发货 / `30` **待收货** / `100` 完成 / `250` 订单取消 —— 我们 docstring 的「30=已发货、50=已完成、100=已关闭」全错，且缺 250。
专属错误码 `31042`（订单过多，请缩短时间范围）、`606006`（next_key 与上一页参数不一致）。

**商品列表** `/channels/ec/product/list/get`：`page_size` **必填**、默认 10、**上限 30**（我们 docstring 写 200）；我们多发了不存在的 `page`。返回 `product_ids` + `next_key` + **`total_num`（无 `has_more`）**。状态真实枚举 `0` 初始值 / `5` 上架 / `6` 回收站 / `11` 下架；**要"全部"应不传该字段**，我们传 `status=0` 当全部是错的。

**售后列表** `/channels/ec/aftersale/getaftersalelist`：**契约与订单列表完全不同，勿照抄** —— 不是嵌套 range 而是 4 个**平铺**字段 `begin_create_time`/`end_create_time`/`begin_update_time`/`end_update_time`（成对使用、必选其一）；**跨度上限 24 小时**（不是 7 天）；秒级时间戳 number（我们传 `"2024-01-01 00:00:00"` 字符串）；**没有 `page_size` 也没有 `page`**（我们两个都发了）。返回 `after_sale_order_id_list` + `has_more` + `next_key`。

**商品详情** `/channels/ec/product/get`：漏了 `data_type`（选填，默认 1；1=线上 2=草稿 3=两者）。

### 2 个契约正确的

`order/get`（仅 `order_id`）、`aftersale/getaftersaleorder`（仅 `after_sale_order_id`）。

### 其他

- token 应改用 **`POST /cgi-bin/stable_token`**（官方明文"推荐使用此接口替代"）。两个 token 接口**凭证完全隔离互不影响**，不能混用同一缓存槽。TTL 必须读返回的 `expires_in`（普通模式若仍有效会返回**上次的 token 及剩余时间**，如 `expires_in: 345`）。`force_refresh=true` 限**每天 20 次 + 间隔 ≥30 秒**。
- 错误处理需覆盖 **HTTP 403**（IP 白名单未匹配，不走 errcode）。白名单上限 200 个，网段仅支持 `/8` `/16` `/24`。
- 「无签名」这一点**官方从未明文**，是三个接口页参数表 + 鉴权栏穷举后的**推断**，契约声明中须如此标注。
- 视频号小店→微信小店是**文档站与品牌迁移，非接口下线**；API 路径保留 `channels/ec/` 是正常的，但**前缀不统一**（类目走 `/shop/ec/`）。
- 官方有 [接口变更日志](https://developers.weixin.qq.com/doc/store/shop/changelog.html)（`D`=删除）可做巡检；**我们那 5 个"不存在"在 changelog 里查不到任何下线记录 —— 是从未存在，非曾存在后下线**。

### 尚缺

**详情类接口的响应体字段未逐个核对**（本次只核了列表接口的返回结构）。鉴于请求体的编造率，返回体解析逻辑也需单独过一遍。

## 现状：唯一完全符合官方契约的平台

token 走 `GET /cgi-bin/token` 带 5 分钟缓冲缓存、`access_token` 放 query、POST JSON body、按 `errcode != 0` 判错 —— 全部符合腾讯文档。它对的原因很直白：**微信不需要签名**，没有 base class 那套错误假设可继承。

（"无签名"这一点官方从未明文写过，是三个接口页参数表 + 鉴权栏穷举后的**推断**，需在契约声明中如此标注。）

## 本 WP 的三项改进

| 项 | 官方 | 现状 |
|---|---|---|
| token 接口 | `POST /cgi-bin/stable_token` —— 官方原文「此接口和 getAccessToken 互相隔离，且比其更加稳定，**推荐使用此接口替代**」（另有三处官方表述指向同一结论） | `GET /cgi-bin/token` |
| 缓存 TTL | 必须读返回的 `expires_in`（普通模式若仍有效会返回**上次的 token 及其剩余时间**，如 `expires_in: 345`） | 缓存 `expires_in` 但默认回落 7200 |
| HTTP 403 | IP 白名单未匹配返回 **403，不走 errcode** | 未覆盖 |

## 注意

- 两个 token 接口的凭证**完全隔离、互不影响** —— `stable_token` 的 `force_refresh=true` 不会让 `cgi-bin/token` 的老 token 失效，反之亦然。**不能混用同一缓存槽**，只选一条路。
- `force_refresh=true` 会使上次 token 失效；官方限制**每天 20 次且间隔 ≥ 30 秒**，官方示例标注"慎用"。仅在 40001/42001/40014 时使用并加限流。
- 频控：1 万次/分钟、50 万次/天。
- API 路径仍保留历史的 `channels/ec/`（channels = 视频号），文档站已是 `/doc/store/shop/` —— 这个不一致是正常的，`channels/ec/` 是官方现行形式。
- 业务契约细节（免踩 `40097 invalid request body`）：订单列表 `create_time_range`/`update_time_range` 至少填一个、秒级、跨度 ≤ 7 天、`page_size ≤ 100`；商品列表 `page_size` 必填上限 30，返回用 `total_num` 判分页（**没有 `has_more`**）。

## 通用约束

1. 签名参与集合必须恒等于发送集合减去 `sign`（WP02 提供通用断言，必须启用）。
2. 签名与发送使用同一字符串对象；业务参数 JSON 只序列化一次并缓存。
3. 契约声明文档中每项结论标注官方出处 URL，区分「官方明文」与「推断」。
4. 官方缺失/矛盾项按 spec.md §8 处理，不得推测填充。
5. 交付需附 wire 层断言：参数名集合、传输位置、timestamp 格式。
