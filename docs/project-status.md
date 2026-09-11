# 项目、版本与咨询进展

更新：2026-09-11。**代码已经上传并合入公开 main；Core 0.1.6 处于已验工程候选阶段，PyPI / 公开稳定 Release 仍为 0.1.5。真实商家验收尚未执行。**

## 代码在哪里，如何取得新修复

| 内容 | 当前状态 | 入口 |
| --- | --- | --- |
| Core 标准版源码 | 公开 main 已包含稳定性修复、显式凭证 SDK、已核平台合同和文档校准 | [main](https://github.com/TonyWang-hub/mcp-cn-commerce/tree/main)、[PR116](https://github.com/TonyWang-hub/mcp-cn-commerce/pull/116)、[PR117](https://github.com/TonyWang-hub/mcp-cn-commerce/pull/117) |
| 可复现工程候选 | `c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e`，包版本 0.1.6 | [固定源码](https://github.com/TonyWang-hub/mcp-cn-commerce/tree/c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e)、[项目虚拟环境安装](../README.md#安装) |
| 公共安装版本 | PyPI 和公开稳定 Release 当前是 0.1.5，不包含上述全部新修复 | [PyPI 0.1.5](https://pypi.org/project/mcp-cn-commerce/0.1.5/)、[Release v0.1.5](https://github.com/TonyWang-hub/mcp-cn-commerce/releases/tag/v0.1.5) |
| 0.1.6 发布 | 工程候选，按发布草稿准备；尚未正式发布到 PyPI / MCP Registry | [CHANGELOG](../CHANGELOG.md)、[工程和发布状态](release-readiness.md) |
| Pro 与 PartnerClient | 配套私有 Pro 0.1.1b1 与独立 Python 客户端已完成工程验收；按内测/合作安排交付 | [公开 Pro 咨询入口](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/new?labels=pro-inquiry&title=%5BPro%5D%20Inquiry) |

`main` 已合入不等于 PyPI 已发新包。复现本次工程结果请固定完整 SHA，不将旧 PyPI 包、不断变化的 main 和候选构建混为一谈。安装包也不自动授予平台 API 权限。

## 已经验证什么

- Core 候选 [CI 34572407075](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572407075) 与 main `67c8fc9` 的 [CI 34572676414](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572676414) 均成功：2225 tests + 20 subtests（JUnit 共 2245），并有安装、真实 MCP 传输及质量检查。
- 配套 Pro 与独立 Python PartnerClient 的工程结果已完成；详细汇总见[验收状态](release-readiness.md)。这不要求公众访问私有仓库，也不代表商家 live。
- 8 个 MCP 平台入口和 155 个注册工具是目录统计；**不等于 155 个当前官方合同或真实接口全部可用**。支持范围以 [SDK 操作表](sdk-integration.md#catalogue-and-evidence-status)为准。
- 抖店、TOP 的真实验收记录当前均为未执行：[抖店](live-acceptance/doudian.md)、[TOP](live-acceptance/taobao.md)。授权、分页、实际金额/日期、后台核对、刷新/失效仍需获准的真实输入。

## 公开需求与咨询

以下根据公开 issue 截至本次更新的内容整理，四项状态均为 OPEN。**咨询、试用意向或提交者自行测试的描述，都不是本项目已签约、已接入客户或完成真店验收的证明。** 本页汇总不替代 issue 里的原始讨论。

| 公开 issue | 提交者表达的需求 | 当前项目对应范围与下一步 |
| --- | --- | --- |
| [#93 — [Pro] 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/93) | 商家管理约 15 店，涉及淘系、京东、拼多多、抖音、小红书、得物，关注数据管理和业务监控 | 多店管理与报告有工程能力；需先选可验证的平台/数据域。得物没有已实现接入，不承诺其列出的全部渠道已覆盖 |
| [#107 — [Pro] 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/107) | 京东 POP、天猫、抖店、有赞、微信小店、小红书的经营聚合、跨店比较和日报监控 | 可按订单/退款口径分平台验证；有赞是独立 SDK 接入，不等同任意微信小程序。JD 退款 Source、XHS Source 等缺口仍影响六平台完整日报 |
| [#110 — [Pro] 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/110) | 桌面电商 AI / ISV 的多用户、多商户、多店；先淘系/抖店/PDD，拟用 1–2 平台真实店铺测试后讨论合作 | 已有配套授权、隔离、采集/报告、HTTP/MCP 与 Python 客户端工程；需合作方受信身份、回调适配和限定样本验收。PDD 业务 schema 及广泛数据域尚未闭合，不提前承诺全部商业集成范围 |
| [#114 — [Pro] 咨询](https://github.com/TonyWang-hub/mcp-cn-commerce/issues/114) | 开发者计划约 7 店测试，涉及京东、淘宝、拼多多、抖音；原文自述拼多多已跑通 | 这是提交者自己环境的反馈，尚无可复核的本项目合同/样本证据，不能据此将 Core PDD 经营 SDK 标为支持。可集中提供可分享的官方方法/schema、应用范围和匿名样本以核对 |

继续保留免费 Pro 种子用户内测承诺，以真实场景反馈推进产品。正式商业合作、OEM/SaaS/再分发权利和支持安排须以双方确认的条款为准，不从公开咨询推导已经成交。

## 下一批可验证事项

1. 先选择 1–2 个合同已明确且实际获准的平台，优先抖店/TOP；统一确认应用资格、API 权限、授权主体、callback/IP 白名单和现有样本。
2. 按相同部署和证据核对至少两页、父/子单、支付优惠、部分/失败/跨日退款、真实刷新/撤销/重新授权，以及同库两身份的隔离。未提供的样本保持未验证。
3. 收齐 PDD 业务 schema、XHS 查询/退款时间单位、JD 售后与取消退款资金合同等明确材料，再按协议实现计划补能力。快手主体、微信共享组件委托和广告账户/报表仍单独记录。
4. 0.1.6 正式公开发布时，另核对版本、tag、包哈希、CI 与 PyPI/Registry 状态；工程候选或 Release 草稿不能提前标为稳定包。

缺口详情见[发布就绪记录](release-readiness.md#合同与代码缺口)与[平台补证](platform-gap-evidence-20260911.md)。公开 issue 仅提交非秘密问题和可分享合同；AppSecret、token、code、买家和支付资料留在受控部署侧。
