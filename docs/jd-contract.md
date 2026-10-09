# JD POP 三个只读方法实现规格

核查日期 2026-09-10；本轮在 R16 已取得证据基础上继续实现，不以 unsupported 代替已可实现工作。
官方链接与本地证据总表见 [remaining-platform-contracts.md](remaining-platform-contracts.md)。

## 对 R16 内部 schema 解读的纠正

官网 `/api/detail` 的 `paramOrderJSFQuery` 是 Java 服务对象；`apiMulti=1` 时官网请求表展平叶子参数，
剔除 `SystemValue=true` 和含默认值的字段。当前官方 `sdkExampleTemplate?id=15660/15661/12866`
也确认订单使用 setStartDate/setOrderId 等平铺 setter，店铺查询无参数 setter。
结合通用协议的 360buy_param_json 例子，HTTP 业务 JSON 应直接包含 start_date/order_id 等字段，
**不能给 HTTP 业务体额外加 paramOrderJSFQuery**。venderId 由授权系统提供，SDK 不允许调用方覆盖。
source_id 在 schema 的 defaultValue 明确为 JOS、官方 SDK 示例不传；本 SDK 仍要求集成方显式
传入 source_id（例如确认使用官方默认来源时传 JOS），不暗中填任意来源。

## 本轮计划与验收

1. 新增受控 HTTPX 失败回归：三方法官方名字、POST form、平铺 JSON、秒格式日期签名、两个授权并发隔离。
2. 参数白名单、source_id/optional_fields 缺失、正数 ID、字符串页码、最大100、固定窗口最多一个月；
   shop 查询无业务参数。SDK operation 保持统一名称，订单列表/详情/店铺变为 documented/live=false。
3. 精确处理 error_response、顶层 code/errorMessage、官方 responce 包装以及订单内 apiResult；
   HTTP200+success=false 必须失败；缺少成功证明或分页计数不能当空成功。
4. 保留 CLI 工具名称，订单工具增可选参数以提示必需来源和字段；没有提供新必填值时明确 ToolError，
   不发旧错误请求；售后两个工具继续拒绝，不将服务单当资金退款。
5. 受控完整分页沿用同一窗口、原样返回总数/orderInfoList，由调用方检测跨页总数/去重；
   本轮不宣称平台有快照隔离，不实现 Pro collector 或归一化。
6. focused/full Core、Black/Ruff/mypy/Pylint，通过后独立提交。需要真实应用、POP店铺授权和权限才能 live 验收。

订单正文方法 jingdong.pop.order.search、jingdong.pop.order.get；店铺 jingdong.vender.shop.query。
MD5 大写(secret+排序 key/value+secret)，所有字段先签原值再表单编码；timestamp 是 yyyy-MM-dd HH:mm:ss。
API 日期格式官方已确认，时间戳按中国站 Asia/Shanghai 输出；业务日期按此格式透传，未宣称所有响应日期的时区已由字段正文保证。

响应路径：jingdong_pop_order_search_responce.searchorderinfo_result.{apiResult,orderTotal,orderInfoList}；
详情 jingdong_pop_order_get_responce.orderDetailInfo.{apiResult,orderInfo}；
店铺 jingdong_vender_shop_query_responce.shop_jos_result.{shop_id,vender_id,shop_name}。
官方 success 字段类型 Boolean，示例同时出现字符串 true/false，二者显式解析；错误文本作为错误，不能用于成功补偿。


## 当前已实现与明确限制

当前三条 SDK 与 CLI 均使用官方 POST 表单路径，GET/POST 公共签名不包含 sign_method 这个非必要字段。
每次重试重新取时间戳并签名；只有已验证只读方法允许网络重试。SDK 不刷新令牌，外部 HTTP client 不被关闭。
source_id/optional_fields 为显式字符串，页码/页大小必须是正十进制字符串；明文/开放买家 ID 仅按官方字段可选传。
查询窗口在本 SDK 中强制成对，即便官方 WAIT_SELLER_STOCK_OUT 容许缺省窗口，也不在这里使用随请求时间变化的默认窗口。
请求表展平与 source_id/venderId 规则的证据包括当前官网 JS `jd-api.js`、三份 `jd-sdk-example-*.json`；
官方 SDK 下载需先登录应用且取决于权限组，见 [SDK 指南](https://jos.jd.com/commondoc?listId=167)，本轮未下载私有应用包。

orderTotal 在官方 schema 为 Number、示例为数字字符串，两者都验证为非负计数；保留原始类型和所有业务字段。
列表必须有 orderInfoList 数组；详情必须有 orderInfo 对象；店铺必须含正数 shop_id/vender_id。
apiResult.success 只接受 Boolean true 或字符串 true，且显式非零错误码不能同时当成功；当前自动生成的官方详情示例
混放 true/999999/系统异常，其字段彼此冲突，本实现会拒绝，不把不一致示例作为成功样本。
HTTP200 网关/业务错误抛 CommerceAPIError，未知/缺字段抛 ValueError，不默认返回空页。

旧商品/物流/营销 CLI 的业务方法没有完成本轮官方核验；虽然统一底层签名/表单已改正，它们仍不属于商家验收范围。
售后服务单依旧不能作为成功退款资金接口，因此 get_refund_list/get_refund_detail 保持 unsupported。

## 给采集/归一化层的字段事实

- 订单 actualPay：买家实付，元、两位小数，可能数据延迟，不支持京喜订单。
- shouldPay：提交订单时买家应付元金额。orderPayment 已在2024年10月停止维护，不能拿旧字段当实付。
- totalOriginalPrice：商品原价合计元；totalSellerReceivable：商品应收元，不含运费、服务费、佣金，存在6秒–1分延迟，部分状态/京喜大店不支持。
- totalSellerDiscount：商家承担优惠元，含价格保护等实时项；payDiscount：支付工具营销优惠元；不能自行把它们加减拼成其他口径。
- paymentConfirmTime：付款确认时间；未付返回0001-01-01 00:00:00，送礼/收礼订单可能继承早于下单时间的支付日期。
- payType 含先货后款（货到/月结/先用后/分批）及混合支付，不能无条件当银行现金。
- orderEndTime：订单完成时间，售后不改变；不是退款完成时间。modified 是版本时间，不能替代支付日期。
- orderState 用英文/拼音枚举；返回赠礼/京喜/虚拟/部分特殊业务范围需按官方 API 类型和权限处理，页码闭合不保证所有交易类型覆盖。
- paymentDetailList 指向 jingdong.pop.order.ocs.query 的支付项明细；本轮尚未核实该 API，未用其猜测退款金额。

本轮没有修改 normalizer、Pro collector、privacy、reporting 或授权 provider；后续这些适配是明确代码待办，不能都归因于凭据缺失。


## 实际验收记录

新 SDK 合同首次26失败/1通过，实施后27通过；新增CLI受控链路首次3失败，实施后合计30通过。
相关SDK/京东/协议focused **211 passed**，CORE完整 **1999 passed、20 subtests passed**（2026-09-10）。
Black/Ruff/mypy通过，4个本轮源码文件Pylint10.00；两个独立token并发、两页固定窗口、错误信封均经HTTPX实际HTTP编码截获验证。
日志 `/private/tmp/jd-native-final-20260910.log` 与 `jd-native-focused-final-20260910.log`。
这些是受控网络合同测试，不是正式商家API实测；没有生产凭据、订单或店铺权限的live声明。
