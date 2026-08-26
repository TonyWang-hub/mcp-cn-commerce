---
work_package_id: WP02
title: base class 契约策略层
dependencies:
- WP01
requirement_refs:
- FR-002
tracker_refs: []
planning_base_branch: sdd/api-contract-conformance
merge_target_branch: sdd/api-contract-conformance
branch_strategy: Planning artifacts for this mission were generated on sdd/api-contract-conformance. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into sdd/api-contract-conformance unless the human explicitly redirects the landing branch.
subtasks:
- T005
- T006
- T007
- T008
phase: Phase 1 - Foundation
assignee: ''
agent: ''
history:
- timestamp: '2026-08-26T17:34:41Z'
  agent: system
  action: Prompt generated via /spec-kitty.tasks
authoritative_surface: shared/
create_intent: []
execution_mode: code_change
owned_files:
- shared/cn_commerce_base.py
- tests/test_cn_commerce_base.py
tags: []
---

# Work Package Prompt: WP02 – base class 契约策略层

## 目标

把 `shared/cn_commerce_base.py` 中"所有平台系统参数长一个样"的硬编码假设，替换为由各平台声明的契约策略。覆盖 IC-02 ~ IC-06 的抽象骨架。

**本 WP 不修任何单个平台的行为**，只提供能表达差异的机制，并保证现有测试不回归。逐平台修正在 WP03~WP11。

## 现状（要改掉的三处硬编码）

| 位置 | 现状 | 问题 |
|---|---|---|
| `cn_commerce_base.py:2880-2882` | 固定发 `app_key` + `access_token` 两个参数 | 参数名逐平台不同；巨量根本不该发这两个 |
| `cn_commerce_base.py:2899-2901` | 固定发 epoch 毫秒 `timestamp` + `sign` + `sign_method` | 四种时间语义；巨量不签名 |
| `cn_commerce_base.py:2928-2932` | 固定按 `error_response.{code,msg}` 判错 | 五种信封；快手/小红书的失败检测不到 |

## 交付物

### T005 — 系统参数策略

每平台声明自己的系统参数表（名称、位置、必填性、取值来源），由 `_request` 按表组装，不再硬编码参数名。必须支持凭证落在 query / body / header 三种位置（IC-03）。

### T006 — 时间戳策略

支持四种语义：`unix_s`（拼多多/抖店/小红书）、`unix_ms`（快手）、`datetime_gmt8`（淘宝，`yyyy-MM-dd HH:mm:ss`）、`datetime_tz`（京东，`yyyy-MM-dd HH:mm:ss.SSSZ` 且**显式带 `+0800`，不依赖进程时区** —— 容器跑 UTC 会有 8 小时偏差被网关直接拒绝）。

生成的字符串必须同时用于签名和发送。

### T007 — 签名策略

支持"无签名"（巨量）与四种签名构造。差异维度见 plan.md IC-04，实现时应把这些维度参数化而非为每个平台写一份完整算法：

- 拼接形态：无分隔符 `kv` / `k=v&` 连接 / 固定顺序 / `method?query` 前缀
- secret 位置：首尾包裹 / 仅作 HMAC key / 末尾追加字面量 / 直接拼接
- 摘要与大小写：MD5 大写 / MD5 小写 / HMAC-SHA256
- 密钥来源：`app_secret` / 独立 `signSecret`（快手）
- 参与范围：全部参数 / 仅系统参数子集 / 固定字段列表

### T008 — 响应信封策略

支持五种判定：`error_response` 存在即失败（淘宝/拼多多）、`code != 0`（巨量，错误字段 `message`）、`error_response.{code,zh_desc,en_desc}`（京东）、`result != 1`（快手，业务数据在 `data`）、`error_code != 0 || !success`（小红书，业务数据在 `data`）。

后两种当前**完全检测不到失败**，会把错误信封当业务数据返回给模型 —— 这是最危险的一类缺陷，模型会拿到看似成功的垃圾数据。

## 验收

- 现有 358 个测试全绿（本 WP 不改变任何平台的实际行为）
- WP01 的 wire 断言工具能对接新策略层
- 策略层能表达上述全部差异维度，且各维度可独立组合

## 通用约束（所有平台 WP 适用）

1. **签名参与集合必须恒等于实际发送集合减去 `sign`。** 这是当前实现最大的结构性缺陷，WP02 的框架提供了通用断言，必须启用。
2. **签名与发送必须使用同一个字符串对象**（尤其 timestamp 与序列化后的业务参数 JSON）。禁止序列化两次。
3. **每项契约结论都要在契约声明文档里标注官方出处 URL**，并区分「官方明文」与「依据充分的推断」。
4. **官方文档缺失或自相矛盾的项**，按 spec.md §8 的处理方式执行，**不得用推测填充**。
5. 不得引入对真实凭证或外部网络的 CI 依赖。
