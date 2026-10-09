# 京东与小红书采集合同补证（2026-09-11）

本记录补充 [京东合同](jd-contract.md) 与 [小红书合同](xiaohongshu-contract.md)。此前的 [平台总表](remaining-platform-contracts.md) 记录的是早期核查状态，不能覆盖两份专门合同中的后续修正。

核查范围是公开官方正文、官网生成的 SDK 示例及已下载的官方 Java SDK；没有调用商家业务接口、联系平台支持或执行退款操作。`documented` 与受控测试均不代表真实店铺验收，`live_verified` 仍为 false。

## 小红书：两个精确字段缺口仍存在

2026-09-11 再次匿名读取官网当前两份 schema，HTTP 200；不是文档访问权限问题。

| 字段 / 契约 | 当前官方事实 | 仍不能推出的结论 |
| --- | --- | --- |
| [`order.getOrderList.startTime/endTime`](https://open.xiaohongshu.com/api/doc/infoNew?gatewayId=103&gatewayVersionId=1661&apiId=27241) | `integer/int64`，说明仅是时间范围起点 / 终点。`timeType=1` 创建最多 24 小时；2 更新最多 30 分钟，从末页向前取 | 两个请求字段使用 Unix 秒还是毫秒、边界是否两端包含；响应 `createdTime/paidTime/updateTime` 明示毫秒不构成请求字段单位证明 |
| [`afterSale.getAfterSaleInfo.afterSaleInfo.refundTime`](https://open.xiaohongshu.com/api/doc/infoNew?gatewayId=165&gatewayVersionId=2804&apiId=30038) | `number`，说明是退款完成时间。`refundStatus=2` 成功；`refundAmountYuan` 是实际已退元、包含定金 | `refundTime` 的单位和零值 / 缺失语义；不能以位数、消息时间或更新时间替换 |
| [订单接入方案 47](https://open.xiaohongshu.com/document/developer/file/47) | 创建历史初始化、更新增量，以及 24 小时 / 30 分钟窗口 | 未给出上述请求字段单位、边界及历史最远可查范围 |
| [SDK 指南 42](https://open.xiaohongshu.com/document/developer/file/42)及官方无依赖 Java JAR | `GetOrderListRequest` 与 `GetAfterSaleInfoResponse.OpenAPIAfterSaleInfo` 有对应 Long 字段；SDK 更新记录确认新增过退款完成时间 | Long 类型没有单位注解，类型与示例数值均不能证明秒 / 毫秒 |
| [退款成功消息 131](https://open.xiaohongshu.com/document/developer/file/131) | 消息 `updateTime` 明示毫秒，`refundFee` 明示元且不含运费 | 消息更新时间不是详情 `refundTime` 的字段合同，金额也不能替代含定金的实际退款总额 |

因此无法从 UTC 作业窗口确定订单查询原生值，也不能将成功退款可靠放入完成日。已有四个 SDK 原生读方法仍有用：整数原样发送，售后列表的已证实毫秒窗口校验保留。当前不能通过增加一个固定乘 1000 的 Source、时间量级猜测或日期回退来“补齐”采集。

## 京东：找到售后资金接口，取消退款仍不是完成资金合同

本次检查官方分类目录的商家售后服务 437、自主售后 439、退款 456，并核对五份 API 详情和对应官网 SDK 示例。

| 官方 API | 已证实的用途与字段 | 对资金采集的限制 |
| --- | --- | --- |
| [`jingdong.asc.serviceAndRefund.view` / 15040](https://joshome.jd.com/api/detail?id=15040) | `pageResult.data[]` 内 `afsRefundId`、`sameOrderServiceBill.serviceId/orderId`；`status=13` 退款成功，14 失败；`completeTime` 是退款完成时间，类型 Date；`refoundAmount` 描述实际退款金额。页号从 1 开始，大小 1–50，`totalCount` | 金额字段没有明示元 / 分；查询条件只有申请时间（最多 7 天）、审核时间（最多 10 天）或订单号，未提供退款完成 / 更新扫描契约。不能把申请日窗口当完成日覆盖 |
| [`jingdong.b2c.shop.aftersales.refund.get` / 21380](https://joshome.jd.com/api/detail?id=21380) | POP 售后退款详情；用 `afsServiceId` 请求。`result.data.afsActualRefundDetail.actualRefundAmount` 是实际退款总额，明确元。`afsEstimateRefundDetail` 是商家可见最大可退金额，正文说明两者不同时出现。返回 `orderId` | 不含退款完成时间、退款 ID 或服务单 ID 回显。金额包含多类费项（余额、礼品卡、京豆、优惠券等），不能称银行现金到账。取消订单退款明确指向 13148 |
| [`jingdong.afsservice.refundinfo.get` / 12718](https://joshome.jd.com/api/detail?id=12718) | 服务单退款信息；有财务明细、单据编号、`refundMoney`、`createdDate`；`suggestAmount` 是商家建议退款额 | 创建时间不是完成时间，无明确资金成功枚举、金额单位说明；银行账号 / 姓名等不应进入指标投影 |
| [`jingdong.pop.afs.soa.refundapply.queryPageList` / 13151](https://joshome.jd.com/api/detail?id=13151) | POP 取消订单退款审核单列表；`applyRefundSum` 单位分，`status` 明确审核状态；申请、审核、更新条件；页号 1–100、大小 1–50；`totalCount` | 没有实际完成退款金额、资金成功状态、资金完成时间。`checkTime` 是审核时间，`modified` 是更新时间；财务审核通过不等于用户退款成功 |
| [`jingdong.pop.afs.soa.refundapply.queryById` / 13148](https://joshome.jd.com/api/detail?id=13148) | 按退款单 ID 查取消订单退款审核详情，同样返回申请额和审核状态，`orderId` 可关联父订单 | 21380 将取消退款引到此接口，仍不能弥补实际资金完成字段缺失；它不是已核实的全部成功退款详情接口 |

15040 与 21380 为后续售后专项接入提供了可实施合同，不能继续笼统写成“京东完全没有退款资金接口”。但它们也不能组成所有退款类别的持续完成日采集：取消订单类别缺少成功资金字段；售后扫描缺少已证实的更新 / 完成发现策略。订单完成时间、服务单完成时间、审核时间不作退款完成时间的替代。

官网 `apiMulti=1` 与 Java / Python SDK 示例确认这些请求用叶子字段（如 `afsServiceId`、`pageNumber`、`applyTimeBegin`）；不能额外包 `param.data` 或 `serviceBaseQuery`。`venderId/appKey/pin` 为系统注入项，调用方不能覆盖。21380 的 `operatorRemark` 有官方默认值，SDK 示例不传。21380 业务成功示例是 `success=true,errorCode=200`；15040 是 `success=true,code=00000`，不能套用订单 `apiResult`。

21380 自动生成的响应示例同时列出实际退款与预估退款对象，与正文“不会同时出现”相冲突；只应将示例用于结构导航，成功样本应按正文分成互斥分支。13148 / 13151 的示例也混合成功标志与错误码，不能照抄为有效成功响应。

官网权限包查询也已匿名核对：[21380 的权限包](https://joshome.jd.com/api/listOwnedAuthPackage?josApiId=23968&page=1)列出 `1707 客服工单-售后场景`（应用类型：客服工单、咚咚插件）与 `583 ERP基础包`（当前页面应用类型：订单管理，仅限课程履约类）。[15040 的权限包](https://joshome.jd.com/api/listOwnedAuthPackage?josApiId=10113&page=1)列出 583、3451 商品供应链分销权限包、582 会员营销高级包、597 互动营销高级包、646 店铺会员，适用应用类型各不同。两接口目录共有 583，不等于任意 ERP 应用可申请；真实资格必须以目标应用后台实际授权和当前应用类型为准，不能用公共分类名承诺开通。

## 已交付的受控查询

Core SDK 新增 `get_aftersale_list`（15040）及 `get_aftersale_refund_detail`（21380），均 `documented/live_verified=false`。请求继续使用 JOS POST 表单、平铺叶子 JSON 和每次请求重新签名。列表接受原生 `orderId` 或成对 `applyTimeBegin/applyTimeEnd`（最多 7 天）、`approveTimeBegin/approveTimeEnd`（最多 10 天），以及显式整数 `pageNumber/pageSize`；页大小最多 50。详情接受正 int64 `afsServiceId` 与可选正整数 `skuNum`。不提供 `buId`、系统主体字段、扩展 JSON 或任意容器。

Pro 复用 `query_shop` 的只读查询路径，两操作要求 `refunds:read`。投影保留售后 ID、父订单 ID、原生状态 / 完成时间、分页，以及明确元口径的实际退款或最大可退字段；列表的未知单位 `refoundAmount` 不进入指标输出，买家、备注、原因、商品名及支付费项自由文本均不输出。保留原生日期字符串，不隐含时区，不将售后列表和详情拼成一条有完成日保证的资金记录。Pro `JdSource.policy.sources` 仍仅含 `orders`。

受控 SDK 测试在开放目录后先复现 53 failed / 6 passed，补齐验证后 59 passed；Pro 真实 Runtime→CommerceService→SDK→HTTPX MockTransport 查询先复现 6 failed / 4 passed，补齐授权和投影后 10 passed。真实店铺验收仍是后续步骤。

## 集中补充清单

不需要逐项交付，可一次提供以下材料。先提供官方正文导出、官方 SDK 字段注解或平台书面回复即可推进合同开发；真实凭据是另一个阶段的验收输入。

| 需要的输入 | 必须回答的精确问题 | 为什么阻塞 | 输入到齐后执行的测试 |
| --- | --- | --- | --- |
| 小红书字段合同 | `order.getOrderList.startTime/endTime` 单位、起止包含性；`afterSale.getAfterSaleInfo.refundTime` 单位、空 / 零语义；创建 / 更新的历史最远可查范围 | 无法正确构造固定窗口和计算退款完成日 | SDK→HTTP 编码验证确认单位；相邻窗口边界去重；精确 24h / 30min 及超限；跨日完成退款；缺日期拒绝；页数变化 / ID 冲突拒绝；父订单 `shopId` 对授权 `sellerId` |
| 京东售后资金补证 | 15040 `refoundAmount` 单位、`completeTime` 日期时区；成功退款如何按更新 / 完成时间发现、历史范围、重开 / 多次部分退款关联和唯一键；21380 是否有可证明同一退款版本的字段或配套查询 | 已有实际额和完成时间来自不同响应，不能证明跨页 / 跨接口同一版本，也不能凭申请 / 审核页闭合证明完成日全量 | 15040 + 21380 + 父订单关联；成功 13 / 失败 14、实际 / 预估互斥；金额口径一致；多次退款 / 重开版本；跨页稳定总数、短页、重复、恢复；缺日期与版本冲突拒绝 |
| 京东取消退款资金接口 | POP 取消订单的实际成功退款查询方法及版本、权限包；退款唯一 ID、父订单 ID、实际金额及单位、资金成功枚举、完成时间及格式 / 时区；可持续扫描的查询字段、窗口、分页、历史范围 | 13148 / 13151 仅证明申请额与审核流程；缺失这个类别不能称全部退款 | 取消 / 售后两类覆盖；申请额≠实际额；审核通过但退款失败；部分退 / 分次退；UTC 跨日；重复 / 总数变化 / 断点恢复；订单归属验证 |
| 小红书真实验收资格 | 有订单 / 新售后 API 包的开发者应用；官方共享测试店的有效测试 code，或店铺主账号授权；可读订单、退款成功 / 失败 / 换货样本 | 合同受控测试不能证明当前应用权限和真实响应形状 | 两授权隔离、刷新、撤销；固定窗口真实分页；订单及退款金额 / 时间与店铺后台核对，不执行商家写操作 |
| 京东真实验收资格 | 经审核的 JOS 应用、应用类型及 15040 / 21380 的实际授权包证明、POP 店铺授权；两接口公开列表共有 583，但页面有应用类型限制，不能默认适用。若需官方应用 SDK，提供由该应用权限生成的包；可读的售后和取消退款样本 | [SDK 指南](https://jos.jd.com/commondoc?listId=167)明确 SDK 按应用权限组生成；拥有普通京东账号不等于这些接口可调用 | 授权 `shop_id/vender_id` 与订单 `venderId`；退款父订单关联；成功 / 失败 / 部分退样本；权限不足、撤销和日期边界；与后台财务记录核对 |

不要把密钥或完整买家资料提交到仓库；证据样例仅需保留字段、类型、状态及一致的匿名 ID。商家原生接口权限包与 Pro 的 `orders:read/refunds:read/shop:read` 是两层授权，不能互相替代。

## 证据复现

本轮原始响应和 manifest 在 `/private/tmp/platform-gap-evidence-20260911`，包含 URL、HTTP 状态、UTC 获取时间、字节数与 SHA-256。缓存目录是本机复现附件；下表中的官方 URL 和指纹可供独立重新获取，缓存不会被当作提交中的长久附件。

| 文件 | SHA-256 |
| --- | --- |
| `xhs-order-list.json` | `d28e0da120a8a0d34ed2ba1d0279b38dc690c015d6e92c4977b040fe1e5e6dca` |
| `xhs-refund-detail.json` | `df2272fad2b1dc3b7c152c8a7615ffa4c0fc4ea9747cdeab5d7da435d2ad6061` |
| `jd-api-21380.json` | `c520430460a3a276705f4cc8fb24a79034d671f71c154896dc63200c56320356` |
| `jd-api-15040.json` | `5bc8f822a80858fc691ec0de2601d685539aa5fea8f275d11d6b95bd5659e5a4` |
| `jd-api-12718.json` | `72479de525106c7dc3f26a8d8fe62c614711ff3b9a9daa02709821e381b48917` |
| `jd-api-13148.json` | `236c9722dd2a142b82caeae52a8300928503faaf1307b7efd2139eccd5ddea41` |
| `jd-api-13151.json` | `b8f29541f2a6992251e0b6d78ea0fd70276ee7d766d14c04a3a3f4438344a90e` |

小红书 Java SDK 原始包及提取字段仍在 `/private/tmp/xiaohongshu-collection-evidence-20260910`，无依赖 JAR SHA-256 为 `ae2233f44571b8d28879eb5dff157e3ce0243cc60f89d02a992def98eb21fbb6`。本次未安装工具链、未启动容器、未运行官方 JAR。
