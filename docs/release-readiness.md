# Core 候选工程、真店与发布状态

记录日期：2026-09-11。本页将工程验证、商家样本验证、主线合入和正式包发布分别记录。文档校准与主线工作已获授权；是否已经完成某项发布动作，以实际工作流和包证据为准，不将其误记为还需商家账号才能开发。

## 版本与证据边界

| revision | contract_evidence | engineering_evidence | live_sample_evidence | release_state |
| --- | --- | --- | --- | --- |
| Core `6b6a7f9fbe336273e331ec70aa3322f37ae51580` | [当前 SDK 操作表](sdk-integration.md#catalogue-and-evidence-status)及平台专项合同 | [CI 34560300029](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34560300029) success；2225 tests + 20 subtests | 未执行真实商家验收 | Core 0.1.6 候选包有独立安装证据；该证据本身不证明 PyPI/tag 发布 |
| 配套 Pro `64dc3f5ac25531d6bc82eaa13cc0c75459e4ada8` | 私有配套包的授权/采集合同；不将 Pro 支持等同全部 MCP 目录 | [私有 CI 34561130526](https://github.com/TonyWang-hub/mcp-cn-commerce-pro/actions/runs/34561130526) success；1330 tests | 未执行真实商家验收 | Pro 0.1.0 私有候选基线；新客户发行分支另绑定实际 SHA/manifest |
| Core main `f3c7452dd3549d8b13cf9a1398c9a06b986fc087` | PR116 合入上述 Core 修复 | 引用上述修复基线结果；不声称此 merge SHA 的新 CI 已通过 | 未执行真实商家验收 | [PR116](https://github.com/TonyWang-hub/mcp-cn-commerce/pull/116) 已于 2026-09-11 06:49:44 UTC 合并；本轮文档/发行由新候选继续推进 |

2026-09-11 04:09:22 UTC 的私有交付归档 `mcp-cn-commerce-private-20260911T040922Z-64dc3f5a` 保存 `ACCEPTANCE.md`、`manifest.json`、`SHA256SUMS`、`checks.json`、`test-summary.json` 与 `hosted-ci/`。归档当时 PR116/Pro PR1 均为草稿，属于历史状态；PR116 现在已经合并，不能继续引用归档说“尚未合并”。私有 Pro 源码、凭据与安装授权不上传公共仓库。

归档中的四个 wheel/sdist 包完成 16 项构建、安装、依赖和握手检查；Core 有 24 项真实 stdio smoke，Pro 有双租户 20 tools 握手及 HTTP/SSE 工程验证。托管 CI 的多 Python 版本、锁定/最新支持依赖、格式/类型/静态检查及远程容器结果均绑定其具体 SHA。它们是真实进程/安装/传输验证，商家 HTTP 合同测试仍使用受控响应。本机没有执行或探测容器运行时。

本轮只校正文档，没有修改 Python、协议、版本或 CI，因此复用上述产品代码的全量工程证据，仅执行必要元数据、文档链接和 diff 检查。后续构建新包时须记录新 SHA 与新哈希，不能称旧包由新文档提交构建。更新中的 Pro 客户发行候选在其准确提交/manifest/CI 形成后另行记录，不将未绑定版本的结果混入此表。

## 当前可安排的限定 PoC

| 平台 / 数据域 | 已具备 | 尚未具备的真店证据 |
| --- | --- | --- |
| 抖店订单/售后 | 四个 SDK 原生查询；配套 Pro 采集、归一化、报告 | 应用/模式/权限、shop_id、两页与实际金额日期、真实刷新/失效；[逐项未执行记录](live-acceptance/doudian.md) |
| TOP 订单/退款 | 五个 documented SDK 查询；配套 Pro 采集、归一化、报告 | 实际方法/fields 权限、卖家主体、分页、payment 局限、退款日期和生命周期；[逐项未执行记录](live-acceptance/taobao.md) |
| 其他 documented SDK 操作 | 见[唯一能力表](sdk-integration.md#catalogue-and-evidence-status)，包括 JD 售后专项 | 仍须逐应用、店铺和操作证明；不能凭抖店/TOP 样本签成全平台通过 |

商家只提供现成 token 不证明其与 app/shop 的绑定，也不完成 Pro 授权和刷新验收。试点只读，使用已有获准样本；平台撤销、Pro 本地 revoke、刷新和重新授权分别记录。没有两页/跨日/到期样本时保留“未执行”。同库两受信身份的跨 tenant 验证与本地独立数据库演示分开。

报告汇总已观测记录：`observed_net_fen` 不是银行到账/利润，`amounts_complete` 不等于完整业务覆盖，`business_coverage=unverified` 保留。抖店的近 90 天创建范围、TOP payment 受退款影响等口径不会因成功采一页而消失。

## 合同与代码缺口：集中输入

| 缺口 | 精确材料 / 责任边界 | 到齐后可推进的验证 |
| --- | --- | --- |
| PDD 商家经营 schema | 账号持有人从目标获批应用取得六个方法的完整官方 schema/生成 SDK：订单列表/增量/详情、退款增量/详情、店铺；记录版本和权限包。方法名与已核公共协议见 [PDD 合同](pinduoduo-contract.md) | 必填/类型、成功/错误信封、分页/total、父单/售后/店铺身份、实际金额/单位、状态、时间单位/时区/边界/历史范围；收到前保持 unsupported |
| XHS Source | 官方明确订单查询 `startTime/endTime` 单位与包含性、详情 `refundTime` 单位与空/零语义、历史范围 | 固定 UTC 编码、24h/30min 边界、反向分页、跨日完成退款、缺日期拒绝；Long 类型和位数不作证明 |
| JD 售后资金 | 15040 `refoundAmount` 单位、`completeTime` 时区；持续发现成功退款的更新/完成窗口；21380 与列表同版本、分次/重开唯一键 | 同一退款版本与父单关联、实际/预估互斥、稳定分页、完成日归属；已有专项查询不等于退款 Source |
| JD 取消退款资金 | 实际完成资金方法/版本/权限包、退款 ID、父单、实际额/单位、成功状态、完成时间与持续扫描 | 取消与售后两类均覆盖；13148/13151 的申请额/审核状态不能代替实际资金 |
| 快手 Pro 主体 | 官方可验证的授权 open_id 与真实店铺绑定合同 | 安全发布凭证和每次读取主体一致；已有五个 SDK 合同不能替代授权证明 |
| 巨量/千川 | 当前报表版本/字段/分页、授权账户树、对应产品权限 | 明确 topic/metrics/账户范围后另写协议实现；广告主资料/余额不能代替 ROAS/计划报表 |
| 微信共享组件跨 tenant | 已知 Pro 委托/回调归属代码边界，由独立 Pro 设计任务处理 | 不能把已有自研和服务市场功能泛称共享组件跨 tenant 已闭合；这是代码边界，不是只差凭据 |
| 广泛经营数据域 | 商品/库存/物流/评价/营销/广告/账单分别取得当前方法合同与权限 | 独立确定支持范围与验收；155 工具目录不是这些数据域全部已验证 |

XHS/JD 完整字段清单、官方来源及已取得 SDK 指纹见[补证记录](platform-gap-evidence-20260911.md)。证据收集只接受官方正文、字段注解或平台书面说明，记录 UTC、版本/权限、URL 与 SHA-256；没有单位的示例数值不生成实现假设。收到完整合同后另写包含具体代码和失败测试的协议计划，不在文档校准中猜 Source 或改金额/时间换算。

账号持有人一次准备：开发者资格、应用类目/权限包、callback/IP 白名单、获准店铺及主体、已有可读样本、生命周期窗口；敏感材料留在部署侧。平台审批/资料等待、合作方身份回调适配和产品代码缺口分别记录，不以“等待账号”统称。

## 本轮就绪检查与后续发行

- [x] 当前 operation_catalog 以零网络方式核对；注册/合同/callable/live 分层描述。
- [x] README、SDK、平台/API 目录和咨询模板校准；保留历史取证时间及免费内测承诺。
- [x] 抖店/TOP 匿名验收记录已建立，结果全部真实标为未执行。
- [ ] 实际应用授权、至少两页与金额/日期后台对账、真实生命周期验收；没有输入就不签通过。
- [ ] 新候选的准确 SHA、包哈希和发行工作流结果由发行负责人归并；本表不预签。

本轮授权包含文档提交和主线推进，不需再次向用户索要实施许可。Core `.github/workflows/publish.yml` 与 `.github/workflows/mcp-registry.yml` 是既有发行链路：版本/tag/`shared.__version__`/`server.json` 一致，质量与安装检查通过后才上传与发布；实际发行由负责人按本轮授权执行。旧基线全绿、PR 合并和 PyPI/Registry 已发布是不同状态。

README 的“**免费使用 Pro 内测版，换取真实场景反馈**”继续有效。本地试用计时不代替该种子用户承诺；OEM/SaaS/再分发等法律授权由正式合作条款约定，不以私有仓库、安装包或工程检查代替。

## 本轮文档检查

2026-09-11 在 Core 文档工作树使用现有项目 Python，`PYTHONPATH` 指向该 Core：

| 检查 | 实际结果 |
| --- | --- |
| `scripts/check_tool_metadata.py` | 退出 0；8 平台、每平台 5 公共工具、155 注册工具一致 |
| 相对 Markdown 目标检查 | 13 个改动文档的本地目标存在；外部官方网页保持既有证据链接，未重新抓取作 live 证明 |
| 本地标题锚点检查 | 本轮文档中的本地标题链接可定位 |
| `git diff --check` | 通过 |
| 产品测试 / 平台调用 | 本轮未重跑全量产品测试，未调用商家平台；产品工程基线见上表 |

新候选的最终 CI、安装包和发行状态以发行 manifest 绑定的准确提交及实际工作流结果为准；本页旧基线数字不代替新候选结果。
