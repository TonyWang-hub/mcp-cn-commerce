# Core 工程候选与发布状态

更新：2026-09-11。**代码和文档已经在公开 main；0.1.6 工程候选已通过验证，PyPI / 公开稳定 Release 仍为 0.1.5。真实店铺验收尚未执行。** 本页区分源码上传、工程测试、正式发布和商家数据验收。

## 版本与公开工程证据

| 对象 | 精确版本 / 提交 | 实际状态 |
| --- | --- | --- |
| 已验证的候选源码 | Core `0.1.6`；[`c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e) | [CI 34572407075](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572407075) success |
| 已合并 main 快照 | [`67c8fc9c0eb0e83cd8f819a686fe8c092f0d9f7c`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/67c8fc9c0eb0e83cd8f819a686fe8c092f0d9f7c) | [CI 34572676414](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572676414) success；[PR116](https://github.com/TonyWang-hub/mcp-cn-commerce/pull/116) 和 [PR117](https://github.com/TonyWang-hub/mcp-cn-commerce/pull/117) 已合并 |
| PyPI / 公开稳定 Release | `0.1.5` | [PyPI](https://pypi.org/project/mcp-cn-commerce/0.1.5/) 与 [Release](https://github.com/TonyWang-hub/mcp-cn-commerce/releases/tag/v0.1.5) 是历史公开版本，不含本次候选全部修复 |
| 0.1.6 发布阶段 | 工程候选 / 发布草稿准备 | 尚未正式发布到 PyPI 或 MCP Registry；发布草稿不等于公开稳定包 |
| 商家 live | 全部 SDK `live_verified=false` | 尚无真实商家授权、业务样本和后台对账的通过记录 |

本次源码可按 [README 的完整 SHA 安装步骤](../README.md#安装)复现，使用项目虚拟环境。普通 `pip install mcp-cn-commerce` 与 `releases/latest` 当前取到的是旧稳定版，不能作为本次修复验收的安装方式。main 会继续变化，复现候选使用固定 SHA 与配套构建 manifest。

## 已完成的工程验证

- Core 完整回归 **2225 tests + 20 subtests**，JUnit 汇总为 **2245**；候选和合并 main 的上述两次 CI 均成功。
- Python 版本矩阵、格式/类型/静态检查、锁定与最新支持依赖安装、wheel/sdist、真实 MCP stdio、manifest 校验及托管容器作业均有对应 workflow 证据。真实进程握手不等于商家 HTTP 已联调。
- 配套私有 Pro `0.1.1b1` 候选的工程回归为 **1432**，独立 Python PartnerClient 为 **203**；配套 Core/Pro/Client 交付完成 **26 项安装/握手检查与 7 项质量检查**。这些是配套交付的验收汇总，不是额外的 Core 测试数，公开用户无需访问私有源码或 CI 才能核对上面的 Core 证据。
- 商家接口合同测试使用受控响应；当前没有真店通过记录。仅文档同步不重复全量产品测试，不修改产品协议、版本或 CI。

较早的 `6b6a7f9` / Pro `64dc3f5` 等结果保留在[历史验收记录](verification-results.md)中，不替代本页新候选的准确提交。新的包哈希、安装结果和发布状态必须绑定实际发行 manifest；不把旧包说成由新文档提交构建。

## 真店验收与支持边界

| 范围 | 已有工程能力 | 未完成验收 |
| --- | --- | --- |
| 抖店订单/售后 | 四个 SDK 原生读查询；配套采集、归一化与报告 | 实际应用模式/权限、shop_id、两页、支付优惠/真实退款/跨日、真实刷新与失效；[当前记录：未执行](live-acceptance/doudian.md) |
| TOP 订单/退款 | 五个 documented SDK 读查询；配套采集、归一化与报告 | 实际方法/fields 权限、卖家主体、逆序分页、payment 口径与生命周期；[当前记录：未执行](live-acceptance/taobao.md) |
| 其他 SDK 操作 | 见[逐操作能力表](sdk-integration.md#catalogue-and-evidence-status)，包括 JD 两项售后专项 | 按应用、店铺、操作和样本分别证明；不凭一两个平台的结果签成全部平台通过 |

只提供 token 不能证明 app/shop 绑定或 Pro 授权刷新链路。授权、真实刷新、平台撤销、Pro 本地 revoke 和重新授权分别验收；缺两页/跨日/到期样本时保留未执行。同库两受信身份的跨 tenant 验证不能用两套独立数据库演示替代。

报告汇总已观测记录：`observed_net_fen` 不是银行到账/利润；`amounts_complete` 不等于完整业务覆盖，`business_coverage=unverified` 保留。抖店近 90 天创建范围、TOP payment 受退款影响等限制不会因成功采一页消失。

## 合同与代码缺口

| 缺口 | 当前边界与下一份有效证据 |
| --- | --- |
| PDD 商家业务 schema | 六个经营 SDK 操作保持 unsupported；需要目标应用权限下的完整官方 schema/生成 SDK，含响应信封、字段、分页、金额、时间、主体。见 [PDD 合同](pinduoduo-contract.md) |
| XHS Source | 订单请求 `startTime/endTime` 单位/包含性、退款详情 `refundTime` 单位/空零语义与历史范围仍缺证明；Long 类型和位数不能替代合同 |
| JD 完整退款 | 已有 15040/21380 售后专项查询；实际金额单位/完成时间、持续发现与同版本关联仍需补证；取消退款 13148/13151 的申请额和审核不能替代实际完成资金 |
| 快手 Pro 主体 | SDK 五项读合同已有；授权 open_id 与真实店铺绑定的官方证明仍缺失 |
| 巨量/千川 | 当前 SDK 已核广告主信息/余额；报表版本、topic/metrics、分页和授权账户树需补齐 |
| 微信同组件跨 tenant | Pro 委托/回调归属还有代码边界；已有自研和服务市场功能不能泛称这一模式已完成 |
| 广泛经营数据域 | 商品、库存、物流、评价、营销、广告、账单等需逐操作验证；155 工具目录不等于这些域全部当前可用 |

XHS/JD 的精确字段、来源和 SDK 指纹见[集中补证](platform-gap-evidence-20260911.md)。需要官方正文、字段注解或平台书面说明；没有单位的示例数值不生成实现假设。应用资质/权限、callback/IP 白名单、获准店铺/主体、可读样本与生命周期窗口一次准备；密钥、code、买家资料留在受控部署侧，不进入公开 issue。

## 项目需求与发布说明

公开咨询进展见[项目状态](project-status.md)：咨询或申请试用表示需求意向，不代表已签约、接入或完成真店验收。优先安排 1–2 平台的限定只读 PoC，再按结果确认后续范围。

Core 按 MIT 开源。Pro 继续履行 README 的免费种子用户内测承诺；正式商业集成、OEM/SaaS/再分发权利按相应合作条款确认。公开 Core 仓库不分发私有 Pro 源码、安装凭据或商家原始数据。
