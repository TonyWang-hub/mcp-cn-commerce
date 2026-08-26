---
work_package_id: WP10
title: 拼多多-timestamp-单位
dependencies:
- WP02
requirement_refs:
- FR-011
tracker_refs: []
planning_base_branch: sdd/api-contract-conformance
merge_target_branch: sdd/api-contract-conformance
branch_strategy: Planning artifacts for this mission were generated on sdd/api-contract-conformance. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into sdd/api-contract-conformance unless the human explicitly redirects the landing branch.
subtasks:
- T026
phase: Phase 2 - Platforms
assignee: ''
agent: ''
history:
- timestamp: '2026-08-26T17:37:08Z'
  agent: system
  action: Prompt generated via /spec-kitty.tasks
authoritative_surface: servers/pinduoduo/
create_intent:
- tests/contract/test_wire_pinduoduo.py
- docs/api-contracts/pinduoduo.md
execution_mode: code_change
owned_files:
- servers/pinduoduo/server.py
- tests/contract/test_wire_pinduoduo.py
- docs/api-contracts/pinduoduo.md
- servers/pinduoduo/tests/test_pinduoduo.py
tags: []
---

# Work Package Prompt: WP10 – 拼多多-timestamp-单位

实现 FR-011。`servers/pinduoduo/server.py` 有自己的 `_call`。**拼多多只有一处不符。**

## endpoint 修正（审计新增，先做这一步）

13 个里 **8 个存在**，5 个不存在（均为**从未存在**而非下线 —— 名字在 344 条 / 8 年公告正文中 0 命中且不在 493 个现行接口清单中）。

**可改名的 3 个**：

| 我们调用的 | 官方正确的 |
|---|---|
| `pdd.logistics.trace.query` | **`pdd.logistics.ordertrace.get`** |
| `pdd.refund.list.get` | **`pdd.refund.list.increment.get`**（此名 2018-04-09 即已存在） |
| `pdd.promotion.list.get` | 无裸 `list.get`；按语义选 `pdd.promotion.goods.coupon.list.get` / `merchant.coupon.list.get` / `limited.discount.list.get` —— **需先定"promotion list"指优惠券批次还是限时限量购** |

**需删除的 2 个工具**：`pdd.goods.search`（**商家侧没有"搜全站商品"能力**，`goods.list.get` 只能列自己店铺的）、`pdd.goods.comments.get`（493 个现行接口 `comment`/`review`/`评价`/`评论` 零命中，8 年公告零命中，拼多多从未开放评价接口）。

**需移出的 1 个**：`pdd.ddk.goods.search` 属**多多客（多多进宝）联盟体系**，归分类 12 而非商品 API。需要完全独立的开发者身份（角色=多多进宝推手、应用类型=多多客联盟类应用、额外做 client_id ↔ 多多进宝账号绑定），**走商家 ISV 授权的 access_token 拿不到该权限**；业务语义是"选品赚佣金"而非"管理我的店"。应独立成 connector 或移除。

代码位置：`servers/pinduoduo/server.py` 行 203（goods.search）、233（refund.list.get）、262（logistics.trace.query）、296（goods.comments.get）、332（promotion.list.get）；`servers/pinduoduo/tests/test_pinduoduo.py` 同样引用了这些假 type。

### 两条平台侧约束需记入契约声明

1. **云外解密限额**：`pdd.open.decrypt.batch` 自 **2026-05-12** 起云外调用限 **1次/10秒 + 单应用单日 100 次**，官方明文"请勿将云外解密作为正式业务场景使用"。云外连接器每日仅能解密 100 条订单收件人信息。**只读经营分析不需要明文**，本 WP 不实现解密。
2. **字段变更**：2025-11-07 起联系人手机号只在 `contact_mobile` 返回，`receiver_phone`/`contact_phone` 不再包含，且该类订单 `receiver_name`/`receiver_address` 返回空值属正常 —— 解析逻辑要能接受空值。

## 官方契约 vs 现状

| 项 | 官方 | 现状 |
|---|---|---|
| timestamp | **UNIX 秒**（官方参数表明写「UNIX时间（秒）」，示例 `1480411125`）；容差 **10 分钟**，可用 `pdd.time.get` 校时 | epoch **毫秒** |
| 签名 | `UPPER(MD5(client_secret + Σ(key+value, ASCII升序) + client_secret))`，公共+业务参数**全部参与**，拼接处无任何字符 | ✅ **完全一致** |
| `sign_method` | **不是请求参数**（官方参数表无此项）；若发送则必须参与签名 | ✅ 没发 |
| `type` / `client_id` / `data_type` | ✅ | ✅ |
| 错误 | `error_response.{error_code, error_msg, sub_code, sub_msg, request_id}` | ✅ |
| 网关 | `https://gw-api.pinduoduo.com/api/router`（HTTP 版**已不允许调用**） | ✅ |

## 官方验证向量（WP01 已固化）

官方示例拼接串 → `E4DE3ED21002510DED352819E7AE6775`。

## 备注（不在本 WP 实现，供 WP12 与后续决策参考）

- 官方敏感接口清单只有 4 个，本仓库调用了其中 2 个：`pdd.order.list.get`、`pdd.order.information.get`
- **入云对「商家自研」是可选的**（官方原文「可以选择」）；只有「订单类应用」「企业 ERP 类」是「必须」
- 真正的硬限制在**解密接口**：`pdd.open.decrypt.batch` 官方明文「仅支持云内调用」，云外 1 次/10 秒；2026-05-12 起对「电商软件服务商」角色叠加单应用单日 100 次上限
- 结论：**订单接口云外可调，但收件人字段是密文**。只读分析场景应走脱敏接口 `pdd.open.decrypt.mask.batch`（**无云内限制**），本仓库不需要明文
- 订单在「已发货/已退款/审核中」状态下收件人信息直接为空；密文格式正在从「含检索串」灰度到「不含检索串」，需兼容两种

## 通用约束

1. 签名参与集合必须恒等于发送集合减去 `sign`（WP02 提供通用断言，必须启用）。
2. 签名与发送使用同一字符串对象；业务参数 JSON 只序列化一次并缓存。
3. 契约声明文档中每项结论标注官方出处 URL，区分「官方明文」与「推断」。
4. 官方缺失/矛盾项按 spec.md §8 处理，不得推测填充。
5. 交付需附 wire 层断言：参数名集合、传输位置、timestamp 格式。
