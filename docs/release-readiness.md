# Core 工程候选与发布状态

更新：2026-10-10。**Core `0.1.6` 本轮工程验收与本地制品准备使用的固定源码快照为 [`7e10d2f`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/7e10d2f80a0bafa333c10282edbc7af6f0b2cbb9)，该提交已合入公开 `main`，自身的 [11 项 CI 检查全部通过](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/38038270963)。wheel/sdist 已按该 SHA 完成本地准备核对，但尚未正式发布。PyPI / 公开稳定 Release 仍为 `0.1.5`，`0.1.6` Release 草稿仍指向历史 `c32e004`；真实店铺验收尚未执行。** 本页分别记录本轮固定源码、本地准备、历史工程证据、正式发布与商家数据验收；后续状态文档提交有自己的 SHA 和 CI 记录，不表示重建了该快照或 main 仍停在 `7e10d2f`。

## 版本与公开工程证据

| 对象 | 精确版本 / 提交 | 实际状态 |
| --- | --- | --- |
| 本轮验收/本地准备固定源码快照 | [`7e10d2f`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/7e10d2f80a0bafa333c10282edbc7af6f0b2cbb9)，版本 `0.1.6` | 已合入公开 `main`；[该提交自己的 CI 38038270963](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/38038270963) 的 11 项检查全部通过 |
| 先前已验收 Core 源码快照（历史） | [`34082f0`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/34082f0c17149bc054306f382ee2d33934da7ff7)，版本 `0.1.6` | [CI 37914052744](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/37914052744) 的 11 项检查全部通过；结果绑定该提交 |
| 2026-10-08 核对的公开 Core `main` 历史快照 | [`1449f49`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/1449f494aa68d5261fc0c57c44bfce6a409a5611)，版本 `0.1.6` | 仅记录该日状态，不能套用其他提交的 CI 结果 |
| 2026-10-08 提交前的 Core 工作区 | `1449f49` + 当时未提交改动，版本 `0.1.6` | 下述本地回归和安装验收通过；该次验收未包含远程 CI 或公开发行 |
| 先前已验 Core 候选 | `0.1.6`；[`c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e) | [CI 34572407075](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572407075) success；验收结果绑定此完整 SHA |
| 已验 main 合并快照 | [`67c8fc9c0eb0e83cd8f819a686fe8c092f0d9f7c`](https://github.com/TonyWang-hub/mcp-cn-commerce/commit/67c8fc9c0eb0e83cd8f819a686fe8c092f0d9f7c) | [CI 34572676414](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34572676414) success；[PR116](https://github.com/TonyWang-hub/mcp-cn-commerce/pull/116) 和 [PR117](https://github.com/TonyWang-hub/mcp-cn-commerce/pull/117) 已合并；结果绑定此快照 |
| PyPI / 公开稳定 Release | `0.1.5` | [PyPI](https://pypi.org/project/mcp-cn-commerce/0.1.5/) 与 [Release](https://github.com/TonyWang-hub/mcp-cn-commerce/releases/tag/v0.1.5) 是历史公开版本，不含本次候选全部修复 |
| `0.1.6` 发布阶段 | 本轮验收/本地准备固定源码为 `7e10d2f`；wheel/sdist 已按该 SHA 完成本地准备核对；Release 草稿仍指向历史 `c32e004` | 尚未正式发布到 PyPI；发布前须核对实际 tag、制品哈希、CI 与 MCP Registry 状态，草稿不等于公开稳定包 |
| 当前配套 Pro / Client 组合 | Pro `0.1.5b2` / Core `0.1.6` / Client `0.1.0b1`；固定 Core 源码快照 `7e10d2f` | Pro 自身 9 项工程 CI 检查通过，已合入 Pro `main`；商家 `live_verified=false`，业务验收与后台对账未完成，合成演练已通过，尚未提供正式客户制品；正式客户制品需正式签名密钥、许可和接收方信息 |
| 历史 Pro Release | `v0.1.1b1` | 旧 Release / 制品，不代表当前 Pro 源码或候选构建；不将旧验收记录归给新候选 |
| 商家 live | 全部 SDK `live_verified=false` | 尚无真实商家授权、业务样本和后台对账的通过记录 |

README 的[完整 SHA 安装步骤](../README.md#安装)固定到本轮验收/本地准备源码快照 `7e10d2f`。`34082f0` 及其 CI、`c32e004` 与 `67c8fc9` 均保留为[各自绑定的历史工程证据](#已完成的工程验证)，复现时须固定对应完整 SHA；普通 `pip install mcp-cn-commerce` 与 `releases/latest` 仍取到公开稳定版 `0.1.5`。2026-10-08 的提交前本地验收单独保留在[历史记录](#2026-10-08-本轮本地变更验收)中。

## 2026-10-10 Core main 与本地发布准备

本节绑定本轮验收/本地制品准备使用的 Core 提交 `7e10d2f80a0bafa333c10282edbc7af6f0b2cbb9`（版本 `0.1.6`，source tree `61e035590a1f68654b2e8e4aafd3b550cde3692b`），该提交已合入公开 `main`。该提交自己的 [CI 38038270963](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/38038270963) 有 11 项检查全部通过；CI 和制品哈希都只绑定这个固定源码 SHA。后续文档提交有自己的 SHA/PR/CI 记录，不应被描述成以该 SHA 重建的源码或证明 main 仍停在 `7e10d2f`。

| 检查 / 阶段 | 实际结果 |
| --- | --- |
| 源码与版本 | 从精确提交导出干净源码；动态包版本、`server.json` 版本、wheel/sdist 元数据均为 `0.1.6` |
| 托管 CI | [Test 38038270963](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/38038270963) 的 11 项检查全部通过，绑定上述完整 SHA |
| 本地 wheel | `mcp_cn_commerce-0.1.6-py3-none-any.whl`，229,663 bytes，SHA-256 `f9ea5fcfc8183672e5b73ff65173b27b8e77c174fdcc6a7264ca82b691791dd3` |
| 本地 sdist | `mcp_cn_commerce-0.1.6.tar.gz`，352,066 bytes，SHA-256 `c1111e1ee421c65289fd709b20f3037ff10f9e8f2e23538d41220d478d162b43` |
| 制品准备核对 | 离线构建与 `twine check` 通过；仅含 wheel/sdist 的干净目录通过 Core public-boundary 检查 |
| 发布状态 | 仅为本地准备；未正式发布。公开稳定版本仍为 `0.1.5`，`0.1.6` Release 草稿仍指向历史提交 `c32e0049b55ed4e600aecd0a862d46ab9ba7ac9e` |
| 商家验收 | 所有 SDK `live_verified=false`；没有真实店铺样本和后台对账通过记录 |

逐项命令、来源和边界见[机器可读的本地准备报告](core-release-preparation-20261010.json)。上表制品哈希只属于从 `7e10d2f` 导出的这次本地构建，不是已发布制品的 URL、签名或发行证明；正式发布时须重新核对实际 tag、构建产物、哈希、PyPI 与 MCP Registry 状态。真实商家验收仍需获准的商家样本和后台核对。

## 2026-10-10 配套 Pro / Client 状态

当前配套组合为 Pro `0.1.5b2` / Core `0.1.6` / Client `0.1.0b1`，固定使用 Core 源码快照 `7e10d2f`。该 Pro 版本已合入 Pro `main`，自身 9 项工程 CI 检查通过。

| 范围 | 状态 |
| --- | --- |
| 工程版本 | Pro `0.1.5b2` / Core `0.1.6` / Client `0.1.0b1`，固定 Core `7e10d2f` |
| 合入与工程检查 | 已合入 Pro `main`；自身 9 项工程 CI 检查通过 |
| 商家 live 与业务验收 | `live_verified=false`；真实商家业务范围、接口样本和后台对账尚未验证 |
| 客户制品准备 | 合成演练通过；`customer_ready=false`，正式客户制品仍需正式签名密钥、许可和接收方信息 |
| 历史 Pro Release | `v0.1.1b1` 是历史制品，不代表当前版本组合或客户交付状态 |

工程 CI 通过表示该组合的工程检查通过，不表示完成真实商家验收、业务对账或正式客户交付。当前 Pro 组合的状态不附带私有 PR、CI 或制品链接，也不公开 Pro 私有源码或提交 SHA。

## 2026-10-09 已合入源码的工程验收

本节绑定 Core 提交 `34082f0c17149bc054306f382ee2d33934da7ff7`（源码版本 `0.1.6`），2026-10-10 核对时已合入公开 `main`。后续提交须保留各自的验收证据。

| 检查 | 实际结果 |
| --- | --- |
| 工程修复合入 | 能力描述与不支持操作守卫、配对依赖更新、9 处 `actions/setup-python@v7` 更新及 Pydantic 子依赖锁定修复均已合入 |
| 托管 CI | [Test 37914052744](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/37914052744) 的 11 项检查全部通过：Python 3.11/3.12/3.13、锁定与最新支持依赖安装、Docker、lint、typecheck、code-quality、public-boundary、manifest-validate |
| 最终运行依赖 | MCP/mcp-types `2.3.0`、httpx2/httpcore2 `2.13.1`、Pydantic `2.13.5`；由 Pydantic 元数据精确约束 `pydantic-core==2.46.5`，移除冗余顶层 pin |
| 独立干净安装 | Python 3.12.3，使用预先获取的缓存离线解析安装；30 项显式锁定全部匹配，实际外部运行依赖 31 项（含隐式 `pydantic-core`），`pip check` 通过 |
| 漏洞审计 | `pip-audit 2.10.1` 严格审计实际安装的 31 项运行依赖（含隐式 `pydantic-core`），退出码 0、0 项已知漏洞；结果绑定该依赖集合和审计时间 |
| 发布与商家验收 | 修复已合入源码；PyPI / 公开稳定 Release 仍为 `0.1.5`，`0.1.6` Release 仍是草稿；真实商家验收未执行 |

下方 2026-10-08 的测试数量、源码指纹及制品哈希只属于那次提交前本地验收，不作为 `34082f0` 的新构建哈希。Pro / Client 使用独立提交、Core 固定版本和自身 CI；本节不表示其已对 `34082f0` 复验，也不表示已完成真实商家或正式客户交付验收。

## 2026-10-08 本轮本地变更验收

该次提交前验收源码为 `1449f494aa68d5261fc0c57c44bfce6a409a5611` 加当时工作区改动；记录不包含后续提交的远程 CI。`servers/` 与 `shared/` 下 50 个 Python 文件的内容指纹为 `fe0f45d6e2426c6cc92734ae450a24c61f819ce16f4645d64f550b28bff6e02f`（路径排序后对 `路径 + NUL + 内容 + NUL` 计算 SHA-256），用于区分当前运行源码和历史提交。

| 检查 | 实际结果 |
| --- | --- |
| 问题复现 | 原 HEAD 的三个巨量报表触发禁止创建客户端的 sentinel，3 项失败；修复后 3 项均在客户端创建前报 migration 错误 |
| 完整 Core 回归 | Python 3.12.3、MCP 2.2.0：`python -m pytest -q`，**2291 passed + 20 subtests passed**；补充安装脚本回归为 13 passed + 20 subtests passed |
| 格式、类型和静态检查 | Black、Ruff、mypy、Pylint、Bandit 全部通过；后三项包含 CI 要求的 `scripts/check_public_boundary.py` 范围 |
| 工具兼容与能力 | 8 平台、每平台 5 个共享工具、155 注册项；全部名称及输入输出 schema 与原 HEAD 一致；15 个 `supported=false` 项均不发送平台请求；业务描述公开合同/支持/live 状态 |
| 构建和公开包边界 | `python -m build`、`python -m twine check`、`python scripts/check_public_boundary.py --dist ...` 均通过；生成 wheel 与 sdist |
| 干净安装 | Python 3.12.13：锁定 wheel、最新支持依赖 wheel、锁定 sdist，真实解析安装及三个 `pip check` 均通过；每环境 24 个 stdio 情境，共 **72/72** |
| 依赖版本 | 锁定环境 MCP/mcp-types 2.2.0；最新环境 MCP/mcp-types 2.3.0；各环境 httpx 0.28.1、httpx2/httpcore2 2.13.1、Pydantic 2.13.5 / pydantic_core 2.46.5 |
| 文档样例 | [数据契约](data-contracts.md)两段 Python 原样执行成功：GMV 1999 分、1 笔付款订单、`complete=true`；中英文 README 与 LLM 安装指南的 JSON/TOML 样例解析通过 |
| 独立审查 | 能力守卫的实际 MCP ToolManager 调用、委派阻断路径、依赖和文档均完成审查；发现的格式与文档问题已修正，无剩余阻断项 |

最终 wheel/sdist 的 SHA-256、安装版本和命令退出状态见[提交前本地验收记录](core-readiness-20261008.json)。命令使用相对路径和 `<validation-dir>` 占位符；原始日志与制品保留在本地验收目录，不作为公开附件。上述哈希对应该次本地构建，后续构建须重新计算。制品用于本地安装核对，不表示公开版本已变更。

该次本地执行范围为 macOS / Python 3.12；当时未执行新的远程 Python 3.11/3.13 矩阵、容器作业或 Registry publisher 校验。商家 HTTP 合同测试使用受控响应，安装情境没有使用真实凭证或发送商家请求；所有 `live_verified=false`。这些结果不替代正式发布或真店验收，也不归给 `c32e004` 的旧 CI。

## 已完成的工程验证

- Core 历史候选 `c32e004` 完整回归为 **2225 tests + 20 subtests**，JUnit 汇总为 **2245**；该提交和已验 main 快照 `67c8fc9` 的上述 CI 均成功。数字不代表 2026-10-08 的公开 main 快照或本轮本地改动已验收。
- 历史 workflow 记录覆盖 Python 版本矩阵、格式/类型/静态检查、锁定与最新支持依赖安装、wheel/sdist、真实 MCP stdio、manifest 校验及托管容器作业。真实进程握手不等于商家 HTTP 已联调，也不替代当前提交的新验收。
- 历史 Pro 提交候选（本轮前）：Pro `0.1.5b2` / Core `0.1.6` / Client `0.1.0b1` 曾固定 Core `4e9309f`；那一版自身 9 项工程 CI 检查通过，当时尚未合入 Pro `main`，也未对 Core `34082f0` 复验。该记录仅反映本轮前的候选状态，不代表当前配套组合；当时商家 live 尚未验收，正式客户制品仍需签名密钥、许可和接收方信息。历史 Pro `v0.1.1b1` 的测试统计只属于旧制品。
- 商家接口合同测试使用受控响应；当前没有真店通过记录。本轮包含实现、依赖与文档修改，其回归和安装结果单独记录在本轮验收项中。

较早的 `6b6a7f9` / Pro `64dc3f5` 等结果保留在[历史验收记录](verification-results.md)中；`c32e004`、`67c8fc9` 与公开 main 快照 `1449f49` 也分别记录。新的包哈希、安装结果和发布状态必须绑定实际发行 manifest；不把旧制品或旧 CI 说成本轮本地改动的验收。

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
