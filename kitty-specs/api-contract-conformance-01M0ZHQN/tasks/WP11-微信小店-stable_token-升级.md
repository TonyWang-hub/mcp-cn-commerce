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
tags: []
---

# Work Package Prompt: WP11 – 微信小店-stable_token-升级

实现 FR-012。`servers/weixin_store/server.py` 有自己的 `_request` 与 `_ensure_token`。

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
