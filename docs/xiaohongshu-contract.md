# 小红书订单及新售后读合同

合同核查日期 2026-09-10，实现验证日期 2026-09-11。这是公开合同与受控 HTTP 测试，不是商家 live 验收，也不表示 Pro 已支持小红书持续采集或完整日报。

## 来源与版本

当前官网导航指向以下正文；所有请求匿名 HTTP 200，原 JSON、请求 URL、获取时间与 SHA-256 保存于 `/private/tmp/xiaohongshu-collection-evidence-20260910`。

| 方法 | 正文 | 官方更新时间 UTC |
| --- | --- | --- |
| `order.getOrderList` | [27241，gateway 103/1661](https://open.xiaohongshu.com/api/doc/infoNew?gatewayId=103&gatewayVersionId=1661&apiId=27241) | 2026-08-18 07:38:09 |
| `order.getOrderDetail` | [27242，gateway 103/1661](https://open.xiaohongshu.com/api/doc/infoNew?gatewayId=103&gatewayVersionId=1661&apiId=27242) | 2026-09-04 09:43:20 |
| `afterSale.listAfterSaleInfos` | [30115，gateway 165/2804](https://open.xiaohongshu.com/api/doc/infoNew?gatewayId=165&gatewayVersionId=2804&apiId=30115) | 2026-09-04 05:31:31 |
| `afterSale.getAfterSaleInfo` | [30038，gateway 165/2804](https://open.xiaohongshu.com/api/doc/infoNew?gatewayId=165&gatewayVersionId=2804&apiId=30038) | 2026-09-04 05:30:40 |

[系统参数](https://open.xiaohongshu.com/document/developer/file/40)规定所有业务 POST JSON 到 `https://ark.xiaohongshu.com/ark/open_api/v3/common_controller`。底层 schema 的 `/api/openapi/aftersale/...` 不是对外请求 URL。系统 `timestamp` 为 Unix 秒字符串，`version=2.0`。签名采用[官方算法](https://open.xiaohongshu.com/document/developer/file/39)：MD5 小写，仅系统 method/appId/timestamp/version 加 appSecret，不签业务参数或 accessToken。

[官方 Java SDK](https://open.xiaohongshu.com/document/developer/file/42)当前链接已实际下载，未执行；页面更新记录至 2026-09-03。无依赖 JAR 的 SHA-256 为 `ae2233f44571b8d28879eb5dff157e3ce0243cc60f89d02a992def98eb21fbb6`。它包含当前四接口的 request/response 类和 `OrderClient/AfterSaleClient`，时间字段仍仅为 Long，不能据此补出业务时间单位。

## SDK 修正规格

- 四个只读 operation 接受下表中的原生字段；旧 snake_case 参数名保留为别名。同一字段同时传原生名和别名时拒绝，未知字段也拒绝，不允许覆盖系统凭证。
- `startTime/endTime` 与数值别名均按原生整数原样发送。订单日期字符串不再自动附加 Asia/Shanghai 或转换成秒；订单业务时间单位尚未得到明确正文证明。调用者必须先取得平台确认的原生值，SDK 不替其宣称固定时间窗口已验。
- `timeType=1` 表示创建，`2` 表示更新，兼容入口默认 1。订单官方窗口分别 24 小时、30 分钟，但未知业务单位时不实施虚假的秒级窗口校验；`endTime>startTime`、页码与类型仍严格检查。订单响应时间 `createdTime/paidTime/updateTime` 则明确为毫秒，不能混淆两组字段。
- 新售后时间明确毫秒，两端包含。创建最多 86,400,000 ms，更新最多 1,800,000 ms。别名可接收带明确时区的 ISO 日期转换为毫秒；无时区日期拒绝。`orderId` 查询可以不传时间组；传时间组时起止必须齐全，缺省 `timeType` 为 1；不会为单独 `orderId` 查询生成时间条件。
- 页码从 1 开始，SDK 默认大小 20；订单 `pageNo<=100`，大小 `<=100`；售后 `pageNo*pageSize<=50000`。这不是自动分页器。订单更新扫描须先取总数/最大页，再按最后页至第一页处理；SDK 保留 `total/maxPageNo/orderList` 原值，不能把 page 1 当扫描起点强制连续递增。
- 售后保留 `afterSaleBasicInfos/totalCount/pageNo/pageSize`，详情保留 `afterSaleInfo`。`statuses` 是流程状态过滤，`returnTypes` 是售后类型过滤；没有默认只查成功的过滤。售后详情只取指标所需对象，不请求协商记录。
- 成功要求明确布尔 `success=true`、有效零错误码及对象 `data`；官方指南是 `error_code`，当前新售后 schema/SDK 兼容 `code`。若两个码同时存在都须为零。`common_controller` 包装新售后 `success/code/data` 时，两层分别检查；缺少成功标记、任何一层失败、非对象 data 均拒绝。失败用固定错误消息和安全数字错误码，不透传平台错误原文；返回的成功对象维持原信封，不做二次 data 解包。

| Operation | 原生参数（括号内为别名） |
| --- | --- |
| `get_order_list` | `startTime(start_time)`、`endTime(end_time)`、`timeType(time_type)`、`pageNo(page)`、`pageSize(page_size)`、`orderStatus(order_status)`、`orderType(order_type)` |
| `get_order_detail` | `orderId(order_id)` |
| `get_refund_list` | 起止、类型、分页同上，另有 `orderId(order_id)`、`statuses(refund_status)`、`returnTypes(return_types)` |
| `get_refund_detail` | `returnsId(refund_id)` |

原生筛选数组接受整数列表，旧售后筛选别名额外兼容逗号分隔字符串。数值拒绝布尔、浮点和 signed 64-bit 溢出；不按位数改变时间单位。原生状态值 0 不会被当作空值丢弃。售后详情不开放 `requestHeader` 或 `needNegotiateRecord`；未核实接口仍保持零网络拒绝。MCP 的订单/售后列表工具额外暴露 `time_type`，默认 1。

## 金额与采集边界

订单详情 `totalPayAmount` 是平台实付分，含运费和定金，不再加一次定金。`totalShippingFree` 是实付运费分；`merchantActualReceiveAmount` 是平台商家实收口径，不能替代买家支付或银行结算。SKU 的 `totalPaidAmount` 是该聚合 SKU 的总实付；`pricePerSku` 是不含税申报价，不能直接当销售单价。

新售后 `expectedRefundAmountYuan` 是申请/预期额，`refundAmountYuan` 是实际已退元、含定金；只有 `refundStatus=2` 证明退款成功。流程 `status=4` 可以是已完成换货，不能等同资金退款。`refundTime` 当前仅描述完成时间，未明示单位；不从位数、更新时间、消息投递时间或本机时间替代它。

订单详情 `sellerId` 的商家 ID 可与授权 `shopId` 校验；[授权指南 341](https://open.xiaohongshu.com/document/developer/file/341) 描述 `shopId` 为 24 位十六进制字符串。售后详情没有足够的独立店铺归属字段，未来采集需按其 `orderId` 读取父订单、验证 ID 关联与 `sellerId`，再归属商店；不得仅相信本地凭证标签。

必须另行确认订单查询起止单位及边界、退款完成时间单位、历史可查询范围。官方未承诺分页快照；固定总数、逐页指纹、唯一 ID 与 list/detail 版本检查仍不等于支付日期覆盖证明。外币 `curreny/totalPayCurrencyAmount` 的币种关系、换货补发和预售历史支付也需单独核对，不能并入单币种全覆盖声明。

## 验证记录

实现使用先失败后通过的真实 SDK → HTTPX MockTransport 测试：`tests/test_xiaohongshu_sdk_contract.py` 首次 50 failed / 7 passed，修复后 57 passed。覆盖签名、原生整数不缩放、别名冲突、时区、创建/更新边界、分页上限、筛选、详情 ID、两层成功/失败信封与错误信息脱敏。相关旧测试同步移除了猜测订单秒级查询、无成功信封和混传不同 operation 参数的样例。

所有 `live_verified` 保持 false。Pro 原生投影、归一化和 Source 未在本修复范围内，未知完成日期不得进入按退款完成日统计的完整性结论。
