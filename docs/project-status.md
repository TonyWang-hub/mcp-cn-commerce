# 项目、版本与咨询进展

更新：2026-10-10。**Core `0.1.6` 已正式公开发布**：`v0.1.6` 指向发布源码 [`27be644`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/27be6444d19ab2d46a54d42cd11c5ecf769b6518)，发布时间为 2026-10-10 10:31:14 UTC；GitHub Release、PyPI 和 MCP Registry 的具体版本及 latest 均为 `0.1.6`。PyPI 下载 bytes、GitHub Release asset digests 与Release `SHA256SUMS` 的发行制品三方核对通过；另对 `CORE_ACCEPTANCE` 中的 source/run 记录完成核对。Fresh Python 3.12.13 venv 的 PyPI 安装、`pip check`、CLI 和 neutral-cwd 24 个 stdio 情境均通过，详见[正式发布记录](release-readiness.md)及[机器可读收据](core-release-publication-20261010.json)。** `7e10d2f` 是发布前的工程验收/本地制品准备快照，其 CI 与本地制品哈希仍只属于该提交；Oct 8/9、`34082f0` 和 `c32e004` 证据也仍绑定各自历史源码。后续文档提交使用各自 SHA 和 CI，不表示发布源码仍是 `main` HEAD。真实商家 API 和后台对账尚未验收；安装与 stdio 冒烟不代表真店验收，Core 发布也不代表 Pro 正式客户交付。

## 代码在哪里，如何取得

| 内容 | 当前状态 | 入口 |
| --- | --- | --- |
| 当前公开 `0.1.6` 发布源码 | [`27be644`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/27be6444d19ab2d46a54d42cd11c5ecf769b6518)，tag `v0.1.6` | [GitHub Release](https://github.com/TonyWang-hub/mcp-cn-commerce/releases/tag/v0.1.6)、[main Test CI 38045028472](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/38045028472)、[Build & Release CI 38045046835](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/38045046835) |
| 发布前工程验收/本地准备快照（历史） | [`7e10d2f`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/7e10d2f80a0bafa333c10282edbc7af6f0b2cbb9)，包版本 `0.1.6` | [该固定提交自己的 CI](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/38038270963)；本地准备制品哈希见历史记录 |
| 先前已验收的 Core 源码快照（历史） | [`34082f0`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/34082f0c17149bc054306f382ee2d33934da7ff7)，包版本 `0.1.6` | [该提交自己的 CI](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/37914052744)；结果只绑定该提交 |
| 2026-10-08 核对的公开 Core `main` 历史快照 | [`1449f49`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/1449f494aa68d5261fc0c57c44bfce6a409a5611)，包版本 `0.1.6` | 仅记录该日状态，不套用其他提交的 CI 结果 |
| 先前验收的 Core 候选 | `c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e`，包版本 `0.1.6` | [固定源码](https://github.com/TonyWang-hub/mcp-cn-commerce/tree/c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e)、[历史验收记录](release-readiness.md#已完成的工程验证) |
| PyPI / 公开稳定 Release | `0.1.6`；当前 latest | [PyPI 0.1.6](https://pypi.org/project/mcp-cn-commerce/0.1.6/)、[Release v0.1.6](https://github.com/TonyWang-hub/mcp-cn-commerce/releases/tag/v0.1.6) |
| `0.1.6` 发布阶段 | 已正式发布；tag 指向 `27be6444d19ab2d46a54d42cd11c5ecf769b6518`；PyPI 与 MCP Registry specific/latest 均为 `0.1.6` | [CHANGELOG](../CHANGELOG.md)、[正式发布记录](release-readiness.md)、[机器可读收据](core-release-publication-20261010.json) |
| 当前配套 Pro / Client 组合 | Pro `0.1.5b2`、Core `0.1.6`、Client `0.1.0b1`；固定 Core 源码快照 `7e10d2f`，Pro 自身 9 项工程 CI 检查通过，已合入 Pro `main` | 商家 `live_verified=false`；业务验收与后台对账未完成，合成演练已通过，尚未提供正式客户制品；正式客户制品仍需正式签名密钥、许可和接收方信息 |
| 历史 Pro Release | `v0.1.1b1` 是较早的历史制品，不代表当前 Pro 源码或当前候选包 | 不将该 Release 的版本、安装包或验收记录归给当前候选 |

README 的源码安装步骤验证并检出 `v0.1.6` tag；该 tag 固定到发布源码 `27be6444d19ab2d46a54d42cd11c5ecf769b6518`。后续状态文档提交按各自 SHA 与 CI 记录，不表示发布源码仍为 `main` HEAD。`7e10d2f`、`34082f0`、`c32e004` 的工程结果仍是各自有效的历史记录，复现时需固定对应完整 SHA 和项目虚拟环境。普通 `pip install mcp-cn-commerce` 取得公开稳定版 `0.1.6`；安装包也不会自动授予平台 API 权限。

## 已经验证什么

- `0.1.6` 已从发布源码 `27be6444d19ab2d46a54d42cd11c5ecf769b6518` 正式发布。PR 149 CI 11/11、main Test CI 11/11、Build & Release CI 13/13 均成功；PyPI 下载 bytes、GitHub Release asset digests 与Release `SHA256SUMS` 三方一致，`CORE_ACCEPTANCE` 的 source/run 记录也已核对。Fresh Python 3.12.13 PyPI venv 安装、`pip check`、CLI 及 neutral-cwd `smoke_install` 的 24 个 stdio 情境通过；这些结果不代表商家 API 验收。
- 固定源码快照 `7e10d2f` 自己的 [11 项托管 CI 检查全部通过](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/38038270963)；该 SHA 的 wheel/sdist、Twine 和公开边界检查也完成本地准备核对，尚未发布。证据见[本轮工程与本地准备记录](release-readiness.md#2026-10-10-core-main-与本地发布准备)。
- 先前 Core `34082f0` 的 [11 项托管 CI 检查](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/37914052744)仍绑定其历史提交，不转作 `7e10d2f` 的验证证据；原独立安装与漏洞审计结果见[历史验收记录](release-readiness.md#2026-10-09-已合入源码的工程验收)。
- 2026-10-08 提交前、基于 `1449f49` 的本地工作区验收：2291 tests + 20 subtests 通过；质量门禁、wheel/sdist 检查与三个干净环境共 72 个 stdio 情境通过。该记录是本地 Python 3.12 验收，未生成新的 CI 或公开发行，详见[本轮记录](release-readiness.md#2026-10-08-本轮本地变更验收)。
- Core `c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e` 的 [CI 34572407075](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572407075) 成功；当时记录为 2225 tests + 20 subtests（JUnit 汇总 2245）。该数字绑定这个历史提交。
- 合并快照 [`67c8fc9c0eb0e83cd8f819a686fe8c092f0d9f7c`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/67c8fc9c0eb0e83cd8f819a686fe8c092f0d9f7c) 的 [CI 34572676414](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572676414) 也成功。此证据绑定该快照，不扩展到当前 HEAD。
- 当前 Pro `0.1.5b2` / Core `0.1.6` / Client `0.1.0b1` 组合固定 Core 源码快照 `7e10d2f`；Pro 自身 9 项工程 CI 检查通过并已合入 Pro `main`。商家 `live_verified=false`，业务验收与后台对账尚未完成，合成演练已通过，尚未提供正式客户制品；正式客户制品仍需正式签名密钥、许可和接收方信息。历史组合见[发布状态记录](release-readiness.md)。
- 8 个 MCP 平台入口和 155 个注册工具是目录统计；**注册不等于每个操作都已核对合同、可由 SDK 调用或已通过真实接口**。支持范围以[SDK 操作表](sdk-integration.md#catalogue-and-evidence-status)为准。
- 抖店、TOP 的真实验收记录当前均为未执行：[抖店](live-acceptance/doudian.md)、[TOP](live-acceptance/taobao.md)。授权、分页、真实金额/日期、后台核对和授权生命周期仍需获准的商家输入。

## 公开需求与咨询

以下 issue 于 2026-10-08 核对，状态均为 OPEN。**咨询、试用意向及提交者自行环境中的描述，都不是本项目已签约、已接入客户或完成真店验收的证明。** 表格只列公开需求和必要的能力边界，不复制联系方式、凭证或商家原始数据。

| 公开 issue | 提交者表达的需求 | 当前项目对应范围与后续 |
| --- | --- | --- |
| [#88 — Pro 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/88) | 商家管理抖店、拼多多、天猫三家店，关注投流 | 巨量/千川当前核对范围是广告主信息和余额，广告报表尚有缺口；PDD 经营 SDK 读取仍关闭。先确认所需广告数据域和实际应用权限；维护者已回复，提交者尚未再回复或补充材料 |
| [#93 — Pro 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/93) | 约 15 店，涉及天猫/淘宝、京东、拼多多、抖音、小红书、得物，关注数据管理和业务监控 | 后续已确认淘系优先、得物暂不需要；目前用 ERP Skills 查看出库订单判断业绩。建议先以 TOP 为主选择 2 家淘系店，条件允许再加 1 家抖店；用连续 7 天日报与 ERP 出库口径逐项对照，不能称为现成完整周报产品。真实 PoC 尚未执行 |
| [#98 — Pro 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/98) | 80+ 店，主要拼多多和抖店；需要订单、资金账单、每日推广金额、可提现金额等 | 该范围横跨多个未闭合数据域；PDD 业务 schema 未取得，广告报表和账单也不能按旧工具注册推定已支持。需按平台、接口、权限及样本拆分，暂无项目验收 |
| [#102 — 淘宝 Key 与个人店申请问题](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/102) | 询问如何申请淘宝 Key、个人店是否可申请 | 平台资格取决于当时的应用类型、卖家身份和实际获批权限；不能承诺个人店一定能取得订单权限。维护者已回复，提交者尚未再回复或补充材料 |
| [#107 — Pro 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/107) | 品牌商家希望聚合京东 POP、天猫、抖音、有赞、微信小店和小红书的多店日报 | 可按逐操作合同和来源分范围核对；有赞独立于微信小店，京东退款、小红书持续采集仍有限制。不能承诺六渠道完整日报已经交付 |
| [#110 — Pro 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/110) | 桌面电商 AI / ISV 关注多用户、多商户、多店和 1–2 平台试点 | 当时核对的私有 Pro 候选为 `0.1.5b1`（Core `0.1.6`、Client `0.1.0b1`）；需先限定平台、操作、接入方式和样本。PDD 业务合同及广泛数据域尚未闭合；未形成真实店铺验收或正式客户制品 |
| [#114 — Pro 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/114) | 开发者计划约 7 店测试京东、淘宝、拼多多、抖音；提交者提到其环境中 PDD 已跑通 | 这是提交者自行环境中的描述，不是本项目 PDD 合同或样本证据。可核对目标应用的官方方法/schema、权限和匿名样本；不能据此将 Core PDD 经营 SDK 标为支持 |
| [#139 — Pro 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/139) | 询问多店铺管理，未说明店数和平台 | 先补充平台、店数、目标数据域、部署方式和获准样本，再判断可验证范围；目前没有可据以承诺的具体平台合同 |

标准种子用户内测承诺继续免费。正式商业合作、OEM/SaaS/再分发权利和支持安排须以双方确认的条款为准，不从公开咨询推导已经成交。

## 下一批可验证事项

1. 对 #93 提出的 TOP 优先流程，先确认目标应用权限、卖家授权、所需字段与可脱敏 ERP/后台样本，再按 1–2 平台、2–3 店、连续 7 天日报做只读核对；尚无样本时保持“未执行”。
2. 真实店铺验收仍需获准的两页、父/子单、支付优惠、部分/失败/跨日退款和授权刷新/撤销/重新授权样本。不要用模拟响应补签。
3. 补齐 PDD 业务 schema、XHS 查询/退款时间单位、JD 售后与取消退款资金合同；快手主体、微信共享组件委托以及广告账户/报表仍单独记录。
4. 获取获准商家样本后完成真实 API 和后台对账验收；安装、CI 与 stdio 冒烟均不能代替真店验证。

缺口详情见[发布就绪记录](release-readiness.md#合同与代码缺口)与[平台补证](platform-gap-evidence-20260911.md)。公开 issue 只交换非秘密问题和可分享合同；AppSecret、token、code、买家资料和支付原文留在受控部署侧。
