# Implementation Plan: API 契约符合性修复

**Branch**: `sdd/api-contract-conformance` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `kitty-specs/api-contract-conformance-01M0ZHQN/spec.md`

## Summary

把 8 个平台连接器的 wire 契约修正到符合各平台官方文档，并先建立不依赖真实凭证的契约测试框架。

核心技术判断：**问题不是 8 个各自独立的 bug，而是一个错误的抽象。** `shared/cn_commerce_base.py` 用一套统一的系统参数 / 签名 / 错误信封假设覆盖全部平台，而该假设仅对拼多多成立。因此实现路径不是"逐个打补丁"，而是**把统一假设替换为 per-platform 契约策略**，再让每个平台声明自己的策略。

## Technical Context

**Language/Version**: Python 3.11+（`pyproject.toml` `requires-python = ">=3.11"`；CI 矩阵 3.11 / 3.12 / 3.13）
**Primary Dependencies**: `mcp>=2.1.1,<3`（MCP Python SDK v2，`MCPServer` API）、`httpx>=0.27,<1`（出站 HTTP）
**Storage**: N/A —— 连接器无持久化状态；仅 `weixin_store` 在进程内缓存 access_token
**Testing**: pytest + pytest-asyncio + pytest-cov。本 mission 新增一层 contract 测试：官方签名向量断言 + wire 层出网参数断言；现有单测保持 mock 在 `_call` 层不变
**Target Platform**: 任意支持 Python 3.11+ 的 OS；8 个 stdio MCP server（`mcp-cn-*` console scripts）
**Project Type**: single —— Python 包，`shared/`（共享基类）+ `servers/<platform>/`（每平台一个 server）
**Performance Goals**: 无吞吐目标（只读查询型）。但需尊重各平台限流：抖店应用维度 20 QPS、小红书应用 100 QPS + method 200 QPS、拼多多解密接口云外 1 次/10 秒
**Constraints**:
- CI 不得依赖真实凭证或外部网络（NFR-001）
- **签名参与集合必须恒等于实际发送集合减去 `sign`** —— 当前实现最大的结构性缺陷正是二者不一致
- 所有契约结论必须可追溯到官方出处 URL，并区分官方明文与推断（NFR-002）
- 不得回归现有 CI（NFR-003）
**Scale/Scope**: 8 个平台 server、147 个工具、`shared/cn_commerce_base.py` 约 7000 行；本 mission 触及其中的 `_request` / `_sign` / 错误解析路径与 8 个 server 的请求组装

## Charter Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

项目 charter 尚未 synthesize（`.kittify/charter/` 为 init 默认值，未产出 DRG），因此**无项目特定治理门禁可校验**。本 mission 自带的等效约束已写入 §Technical Context 的 Constraints 与 spec.md 的 NFR。

如需启用治理门禁，可运行 `spec-kitty charter synthesize` 后重新走 Charter Check；本 mission 不以此为前置。

## Project Structure

### Documentation (this mission)

```
kitty-specs/api-contract-conformance-01M0ZHQN/
├── spec.md              # 已完成
├── plan.md              # 本文件
├── contracts/           # Phase 1：每平台一份契约声明（官方出处 + 明文/推断标注）
│   ├── oceanengine.md
│   ├── taobao.md
│   ├── doudian.md
│   ├── xiaohongshu.md
│   ├── jd.md
│   ├── kuaishou.md
│   ├── pinduoduo.md
│   └── weixin_store.md
└── tasks/               # Phase 2：WP 定义
```

### Source Code (repository root)

```
shared/
└── cn_commerce_base.py        # 统一假设所在；改为 per-platform 契约策略

servers/
├── oceanengine/server.py      # 裸用 base；需去签名 + header token + 报表迁移
├── taobao/server.py           # 裸用 base；session + 时间格式
├── jd/server.py               # 覆写 _sign；需改摘要 + param_json 入签
├── kuaishou/server.py         # 覆写 _sign；path/命名/param 打包/判错
├── doudian/server.py          # 自有 request()；补必填参数 + 签名串
├── pinduoduo/server.py        # 自有 _call；时间戳单位
├── xiaohongshu/server.py      # 自有 _call；单一网关重写
└── weixin_store/server.py     # 自有 _request；已正确，仅 stable_token 升级

tests/
├── contract/                  # 新增：本 mission 的验收层
│   ├── vectors/               # 官方签名算例（淘宝/京东/拼多多）
│   └── test_wire_*.py         # 各平台出网参数断言
├── test_integration.py        # :128-132 需按巨量官方契约重写
└── ...                        # 其余现有测试不变
```

**Structure Decision**: 沿用现有 single-package 布局（`shared/` + `servers/`），不新增顶层目录。契约测试作为 `tests/contract/` 子目录加入，由现有 `pyproject.toml` 的 `testpaths = ["tests", "servers"]` 自动纳入。契约声明文档放在 mission 目录下而非 `docs/`，因其为验收依据而非用户文档；WP10 再把结论沉淀进 `docs/platforms.md`。

## Complexity Tracking

无 Charter Check 违规需要论证（charter 未 synthesize）。

一处需要显式记录的复杂度取舍：

| 取舍 | 为何需要 | 被否决的简单方案 |
|---|---|---|
| 引入 per-platform 契约策略层，而非在各 server 内各自覆写 | 8 个平台的差异是**横切的**（时间戳、签名、传输位置、错误信封各自成族），逐 server 覆写会把同一族差异散落 8 处，且无法对"签名集合 == 发送集合 − sign"这类跨平台不变式做统一断言 | 「每个 server 自己覆写 `_request`」—— 被否决：`weixin_store` 已如此，代价是 base class 的限流/重试/追踪全部绕过，等于放弃基类价值 |

## Implementation Concern Map

> 关注点按**架构维度**划分，而非按平台 —— 因为同一维度的差异横跨多个平台，按平台切会导致同一处抽象被反复改写。

### IC-01 — 契约声明与验收框架

- **Purpose**: 建立不依赖真实凭证的验收手段，使后续所有关注点都有客观通过标准。
- **Relevant requirements**: FR-001, FR-002, FR-003
- **Affected surfaces**: `tests/contract/`（新增）、`kitty-specs/.../contracts/`（新增）、`tests/test_integration.py`
- **Sequencing/depends-on**: none —— 其余全部关注点的前置
- **Risks**: 若框架的断言粒度过粗，后续平台修复会"通过但仍不符"；粒度过细则每次平台文档微调都要改测试。取舍点在于只断言**契约层**（参数名集合、位置、格式、签名字节），不断言业务字段。

### IC-02 — 系统参数模型（名称、位置、必填性）

- **Purpose**: 把 base class 硬编码的 `app_key` + `access_token` + `timestamp` + `sign` + `sign_method` 一套参数，替换为各平台声明式的系统参数表。
- **Relevant requirements**: FR-004, FR-006, FR-007, FR-008, FR-009, FR-010
- **Affected surfaces**: `shared/cn_commerce_base.py:2846-2905`（`_request` 的 auth_params/attempt_params 组装）、8 个 server
- **Sequencing/depends-on**: IC-01
- **Risks**: 参数名差异极细碎且无规律（`appkey` vs `app_key`、`signMethod` vs `sign_method`、`client_id` vs `appId` vs `app_key`、`session` vs `access_token` vs `accessToken`）。必须由声明式表驱动，不能靠字符串拼接的隐式约定。

### IC-03 — 鉴权凭证的传输位置

- **Purpose**: 支持三种互不兼容的凭证位置：query 参数（淘宝/京东/拼多多/快手/抖店/微信）、HTTP header（巨量 `Access-Token`）、POST body（小红书 `accessToken`）。
- **Relevant requirements**: FR-004, FR-008
- **Affected surfaces**: `shared/cn_commerce_base.py` `_request`、`servers/oceanengine/`、`servers/xiaohongshu/`
- **Sequencing/depends-on**: IC-02
- **Risks**: 巨量是"header + 完全无签名"的特例，与基类"必签名"的前提直接冲突；这是 `test_integration.py:128-132` 会撞红的根源。

### IC-04 — 签名算法族

- **Purpose**: 实现四种互不相同的签名构造，并保证「签名集合 == 发送集合 − sign」不变式。
- **Relevant requirements**: FR-002, FR-006, FR-007, FR-009, FR-010, FR-011
- **Affected surfaces**: `shared/cn_commerce_base.py:3007-3022`（`_sign`）、`servers/{jd,kuaishou,doudian}/server.py` 的 `_sign` 覆写
- **Sequencing/depends-on**: IC-02
- **Risks**: 差异维度相互交叉 ——
  - 拼接形态：无分隔符 `kv`（淘宝/京东/拼多多）vs `k=v&` 连接（快手）vs 固定顺序硬编码（抖店）vs `method?query` 前缀（小红书）
  - secret 位置：首尾包裹（淘宝 md5 / 京东 / 拼多多 / 抖店，**含抖店的 hmac 分支**）vs 仅作 HMAC key 不包裹（淘宝 hmac 分支）vs 末尾追加字面量 `&signSecret=`（快手）vs 直接拼接（小红书）
  - 摘要与大小写：MD5 大写（淘宝/京东/拼多多）vs MD5 小写（快手/小红书）vs HMAC-SHA256（抖店）
  - 签名密钥来源：`app_secret`（多数）vs **独立的 `signSecret`**（快手）
  - 参与范围：全部参数（淘宝/京东/拼多多）vs 仅 4 个系统参数（小红书）vs 固定 5 个（抖店）vs 系统参数 + `param`（快手）

  这是全 mission 最易写错的一块，必须逐平台用官方向量或官方工具验。

### IC-05 — 时间戳语义

- **Purpose**: 支持四种时间语义并保证签名与发送使用同一字符串。
- **Relevant requirements**: FR-006, FR-007, FR-009, FR-011
- **Affected surfaces**: `shared/cn_commerce_base.py:2899`、`servers/{doudian,pinduoduo,xiaohongshu}/server.py`
- **Sequencing/depends-on**: IC-02
- **Risks**: 四种语义 —— UNIX 秒（拼多多/抖店/小红书）、UNIX 毫秒（快手）、`yyyy-MM-dd HH:mm:ss` GMT+8（淘宝）、`yyyy-MM-dd HH:mm:ss.SSSZ` 显式时区（京东）。京东那条尤其关键：官方 SDK 依赖 JVM 默认时区，容器跑 UTC 会有 8 小时偏差直接被网关拒绝 —— 我们必须显式带 `+0800`，不能依赖进程时区。容差窗口也不同（京东 6 分钟、拼多多/抖店 10 分钟）。

### IC-06 — 响应信封与错误解析

- **Purpose**: 支持五种互不相同的成功/失败判定与错误字段。
- **Relevant requirements**: FR-004, FR-008, FR-009, FR-010, FR-012
- **Affected surfaces**: `shared/cn_commerce_base.py:2928-2932`、各 server 的响应处理
- **Sequencing/depends-on**: IC-02
- **Risks**: 现状是所有平台都按 `error_response.{code,msg}` 解析，导致巨量（`code`/`message`）、京东（`code`/`zh_desc`/`en_desc`）的错误信息全部退化成 `"unknown"`，而快手（`result==1`）和小红书（`error_code==0 && success==true`）的失败**根本检测不到**、还会把错误信封当业务数据返回给模型。后者是最危险的一类 —— 模型会拿到看似成功的垃圾数据。微信小店额外需要覆盖 HTTP 403（IP 白名单，不走 errcode）。

### IC-07 — endpoint 与 method 寻址

- **Purpose**: 修正三种寻址模型：per-API REST path（抖店/快手/微信/巨量）、单一网关 + body 内 `method`（小红书）、单一 router + query 内 `method`（淘宝/京东/拼多多）。
- **Relevant requirements**: FR-005, FR-008, FR-010
- **Affected surfaces**: `servers/{kuaishou,xiaohongshu}/server.py` 的全部工具函数、`servers/oceanengine/server.py`
- **Sequencing/depends-on**: IC-02
- **Risks**: 快手与小红书现有 path（`/open/api/...`、`/api/...`）是虚构的，需按官方 method 名逐个重建 —— 小红书 47 个 method 名已从官方机器可读接口取得，快手需从官方 Java SDK 的 `getApiMethodName()` 取。这是**逐工具**的改动面，不是一处改动。

### IC-08 — 巨量报表 v3.0 迁移

- **Purpose**: 5 个已于 2024-05-06 官方下线的 endpoint 迁至 `v3.0/report/custom/get/`。
- **Relevant requirements**: FR-005
- **Affected surfaces**: `servers/oceanengine/server.py` 的报表类工具
- **Sequencing/depends-on**: IC-02, IC-03
- **Risks**: **本 mission 唯一涉及业务语义重写的关注点。** 旧接口的 `fields` / `group_by` 平铺参数，在 v3.0 变成 `data_topic` + `dimensions` + `metrics` 三段式，且合法的维度指标组合需先调 `report/custom/config/get/` 查询。工具的入参签名（暴露给模型的那层）也会随之变化 —— 需决定是保持工具接口稳定并在内部转译，还是把 v3.0 的表达能力透出给模型。建议前者以避免破坏既有用法。

### IC-09 — 对外声明与文档一致性

- **Purpose**: 使 README / docs / FAQ 的能力声明与实际状态一致。
- **Relevant requirements**: FR-013
- **Affected surfaces**: `README.md`、`README_en.md`、`docs/platforms.md`、`docs/FAQ.md`
- **Sequencing/depends-on**: IC-02 ~ IC-08（须待实际状态确定后再改口径）
- **Risks**: 涉及对外表述，需人工确认措辞。已知需更正项：`8/8 全部完成` 口径、`docs/platforms.md` 中淘宝签名方式与代码不一致、FAQ 中巨量资质要求应为「企业认证 + 企业打款认证」而非「Developer account with approved app」。
