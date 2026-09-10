# 其余平台官方合同与接入矩阵（R16）

核查日期：2026-09-10。范围：京东 POP、快手小店、小红书商家、微信小店、巨量引擎/千川。

## 本轮规格

依次核对每个平台的开发者身份、测试入口、商家/广告账户授权主体、code/token/refresh/subject 字段以及 SDK 当前只读方法。
以官网当前正文或官方 SDK 为证据；目录和示例运输不自动证明业务合同完整。对查证错误的映射先写失败测试，再改正或明确 unsupported。
CLI 保留原工具名称；预期不支持应使用 MCP ToolError 透传具体原因。Pro 只有取得完整授权和主体合同才新增 adapter。
不更改 normalizer、TOP/Youzan、采集/报表/调度模块；不操作用户浏览器、不发外部消息、不发真实商家写请求或启动 Docker。
各平台变更使用 focused HTTPX/协议测试和相应质量检查；整体 Pro 验收由集成任务统一完成。

## 证据保存

当前公开页面、接口正文及响应记录保存在 `/private/tmp/remaining-platform-evidence-20260910`。
历史笔记与旧缓存仅帮助找到来源，不作为当前权限、测试资源可用性的证明。

## 支持与阻塞矩阵

逐平台核验结果及实际检查记录在下文填入；未完成核验的条目不构成支持声明。

## 小红书商家：有官方共享测试店，商家 OAuth V2 已实现

适用产品是 `open.xiaohongshu.com` 的电商开放平台及 ARK/千帆商家授权，不是 `openaccount.xiaohongshu.com` 的基础账号登录。
[新手指南](https://open.xiaohongshu.com/document/developer/file/32)要求先认证开发者资质；商家自研需店铺主账号绑定，个人/个体店铺不能走该自研资质流程。
[应用类目](https://open.xiaohongshu.com/document/developer/file/33)明确列出订单处理、企业 ERP、跨境 ERP 等类目及相应订单/售后权限包。

[应用测试](https://open.xiaohongshu.com/document/developer/file/34)提供**线上共享测试店**，仅开发测试或下线状态的应用可以在应用管理中获取；上线后取消。
测试店账号是子账号，不能自行完成主账号授权，须使用控制台申请测试 code 的按钮，再调 `oauth.getAccessToken`。
code 有效 10 分钟。测试商品价格固定为 0.1 元，测试支付退回须正常申请退款；测试数据不隔离，不能修改其他开发者的数据。
该入口需要开发者账号、审核后的对应应用及控制台权限；本轮仅读取说明，未申请店铺、下单或发写请求。

[自研商家授权](https://open.xiaohongshu.com/document/developer/file/341)原则上限同主体或关联主体的 10 个企业店铺；
[三方服务商授权](https://open.xiaohongshu.com/document/developer/file/342)要求应用上线并注册服务，可以采用仅分享链接或服务市场公开的服务。
正式网页入口为 `https://ark.xiaohongshu.com/ark/authorization?appId=...&redirectUri=...&state=...`，由店铺主账号确认。
令牌及刷新请求均 POST JSON 到 `https://ark.xiaohongshu.com/ark/open_api/v3/common_controller`：

| 项目 | 当前合同 |
| --- | --- |
| 换码 | `method=oauth.getAccessToken`，业务参数 `code` |
| 刷新 | `method=oauth.refreshToken`，业务参数 `refreshToken` |
| 系统参数 | `appId`、`timestamp`（秒级十进制字符串）、`version=2.0`、`method`、`sign`；[签名说明](https://open.xiaohongshu.com/document/developer/file/39) |
| 签名 | MD5 小写，材料 `method?appId=...&timestamp=...&version=2.0` 后直接接 appSecret；不发送 appSecret |
| 成功信封 | `success=true,error_code=0,data` |
| 主体 | `data.sellerId` 是店铺标识（示例为 24 位 hex 字符串），不是普通用户 openId |
| 过期 | `accessTokenExpiresAt`、`refreshTokenExpiresAt` 是绝对毫秒时间；默认 AT 7 天、RT 14 天，以返回值为准 |
| 刷新窗口 | AT 剩余大于 30 分钟时返回原令牌；最后 30 分钟及 AT 过期后可刷新；成功轮换后重置授权期限，旧 AT 最多继续 5 分钟 |
| 权限证明 | 换码响应未列 scope；不从成功换码推断订单、售后 API 权限 |

Pro 的 `XiaohongshuProvider` 实现 code/refresh，重复核验 `sellerId`，保持 `self_use=False`（自研商家同样需要 code）及 `live_verified=False`。
新 22 项受控 HTTPX 测试通过，相关授权回归共 152 项通过；没有真实商家授权验收。

SDK 已有 `order.getOrderList/getOrderDetail`、`afterSale.listAfterSaleInfos/getAfterSaleInfo` 四个只读映射。
当前官方目录及正文经公开 `GET /api/doc/second/listNew?apiNavigationId=15|16` 与 `/api/doc/infoNew?gatewayId=...&gatewayVersionId=...&apiId=...` 取得：
订单正文 ID 27241/27242（gateway 103/1661），新售后 30115/30038（gateway 165/2804）；后两者更新于 2026-09-04。
订单创建窗口至多 24 小时、更新窗口至多 30 分钟，时间为秒；新售后创建/更新同样为 24 小时/30 分钟，时间是**毫秒**。
新售后列表 `data.afterSaleBasicInfos`、`totalCount/pageNo/pageSize`；页码起 1、页大小至多 100、`pageNo*pageSize<=50000`。
列表 `expectedRefundAmountYuan` 是预期申请额，不能记成实际退款。
详情 `data.afterSaleInfo.refundAmountYuan` 是实际退款总额（元、含定金），`refundStatus=2` 才是退款成功；`refundTime` 表示完成时间，但当前正文没有明确单位，需要官方确认或官方 SDK 补证，禁止推测后直接做日报。
业务网关外层信封与底层服务 schema 的 `code`/`error_code` 差异须在真实响应中确认。

## 微信小店：可调用官方读接口；自研/ISV 身份分别处理

[当前开发者指南](https://developers.weixin.qq.com/doc/store/shop/dev_before/guide.html)（页面变更 2026-04-29）明确区分：
商家自研在“小店后台 → 服务市场 → 经营工具 → 自研”获取小店 AppID/AppSecret，以稳定版 token 调用；
ISV 需入驻服务市场、上架服务，商家购买后静默授权权限集，再通过第三方平台拉取 `authorizer_appid/refresh_token` 并生成 `authorizer_access_token`。
不能把公众号测试号、小程序测试 AppID、微信支付沙箱凭据当作微信小店店铺凭据。
本轮查阅的指南与接口正文没有提供匿名申请的专用测试店入口；这表示**尚未找到公开入口**，不是声称官方绝无测试资源。
后续需要小店管理员的真实小店 AppID/AppSecret 或服务商平台资质、已上架服务和店铺订购授权；有 IP 白名单时须配置运行主机出口 IP。

| SDK operation | 官方方法及响应 | 窗口/权限 |
| --- | --- | --- |
| `get_order_list` | POST `/channels/ec/order/list/get`；`order_id_list/has_more/next_key` | `create_time_range` 或 `update_time_range`，秒级且至多 7 天；page_size<=100；权限集 131 |
| `get_order_detail` | POST `/channels/ec/order/get`，`order_id`；`order` | 权限集 131；ID 列表需逐项拉详情 |
| `get_refund_list` | POST `/channels/ec/aftersale/getaftersalelist`；`after_sale_order_id_list/has_more/next_key` | `begin/end_create_time` 或 `begin/end_update_time` 成对；24 小时；示例为秒级时间戳；无 page/page_size 字段；权限集 131 |
| `get_refund_detail` | POST `/channels/ec/aftersale/getaftersaleorder`，`after_sale_order_id`；`after_sale_order` | 权限集 131 |
| `get_shop_info` | **GET** `/channels/ec/basics/info/get`；`info.username` 原始店铺 ID | 权限集 129/131/192 任一；错误码 43001 表示要求 GET |

官方正文：[订单列表](https://developers.weixin.qq.com/doc/store/shop/API/channels-shop-order/api_getorderlist.html)、[订单详情](https://developers.weixin.qq.com/doc/store/shop/API/channels-shop-order/api_getorder.html)、[售后列表](https://developers.weixin.qq.com/doc/store/shop/API/channels-shop-aftersale/aftersale/api_getaftersalelist.html)、[售后详情](https://developers.weixin.qq.com/doc/store/shop/API/channels-shop-aftersale/aftersale/api_getaftersaleorder.html)、[店铺信息](https://developers.weixin.qq.com/doc/store/shop/API/storemanage/api_mmecapi_basicinfo.html)。
列表分页须固定同一时间窗口和过滤器，原样回传 `next_key`；不能将页码换算成 cursor。订单错误 606006 表示本次参数与上一页不一致，31042 要求缩小时间窗口。
没有 total；结束条件是 `has_more=false`，ID 列表成功不代表详情完整或支付日期覆盖完整。

订单现金字段是 `order.order_detail.price_info.order_price`（用户实付，分），支付时间 `payment_info.pay_time` 为秒。
但 `payment_method=2` 的 pay_time 是先用后付确认时间；3 抽奖零元和 4 积分兑换未发生实际支付，pay_time 是下单时间，不能无条件归入日现金收入。
售后 `status` 是字符串：`MERCHANT_REFUND_SUCCESS`、`MERCHANT_RETURN_SUCCESS` 表示成功退款，`MERCHANT_EXCHANGE_SUCCESS` 仅换货；`refund_info.amount` 的单位为分。
各详情字段是否足以确定实际退款完成日期，留给归一化阶段严格核验，不把更新时间当作退款完成时间。

本轮修正 SDK/CLI 店铺信息旧错误路径与 POST 方法，并将 CLI 售后列表改为秒级时间和 `next_key`；兼容保留旧参数，但 page>1 明确拒绝，page_size 不发送给官方。
9 项新增合同测试先失败后通过；连同原微信工具测试和 SDK 测试共 102 项通过。`documented` 仅表示文档/受控请求合同，所有 `live_verified` 仍为 false。


## 京东 POP：官方 schema 已取得，旧读合同已封闭，业务迁移仍待实现

这是 JOS 京东 POP 商家店铺接口，不是京东秒送/即时零售开放平台。
[新手指南](https://jos.jd.com/commondoc?listId=298)说明开发者注册与应用审核流程；商家、ISV 或个人账号能注册不代表获准使用 POP 商家订单权限。
应用测试状态每天 500 次调用，上线后按应用规则调整；测试状态是一种应用配额，不是匿名测试店。
[协议文档](https://jos.jd.com/commondoc?listId=33)目前确实列出正式 `https://api.jd.com/routerjson` 与预发 `https://api-dev.jd.com/routerjson`。
本轮没有找到可匿名领取 POP 预发 appKey/token/商家数据的入口；京东秒送的沙箱不可作为 POP 的测试资源证明。

[OAuth 文档](https://jos.jd.com/commondoc?listId=32)明确网页授权为 `https://open-oauth.jd.com/oauth2/to_login`，
`app_key/response_type=code/redirect_uri/state/scope`；换码 `/oauth2/access_token` 使用 `app_key/app_secret/grant_type=authorization_code/code`，
刷新 `/oauth2/refresh_token` 使用 `grant_type=refresh_token/refresh_token`。
返回 `access_token/refresh_token/expires_in`，expires_in 为秒，scope 为逗号分隔；`xid`（正文表另写 xId）是用户身份，不等同店铺 ID。
文档要求到期前 24 小时内刷新、过期后不能刷新，成功后保存新 AT/RT；单月刷新次数也有限制。
RT 的独立截止时间及用户 xid 与当前店铺 vender_id/shop_id 绑定的完整合同尚未闭合，故没有增加 Pro JD provider。

通过官网当前 JS 中公开的 `https://joshome.jd.com/doc/getChannelInfoListByTreeId?id=...`、`/classification/list?id=...` 与
`/api/detail?id=...&apiName=...`，**匿名取得完整正文与 schema**，不是登录阻塞。
订单 API 正文在 2026-08-17/31 更新，优先于旧协议页中的 2012 示例。

| 目标 | 当前官方方法/文档 | 与旧实现的实质差异 |
| --- | --- | --- |
| 订单列表 | [jingdong.pop.order.search](https://jos.jd.com/apilistnewdetail.html?apiId=15660) | 必填业务容器 `paramOrderJSFQuery`；其中 `order_state/optional_fields/source_id/page/page_size`，页码/大小是字符串，大小<=100；旧实现的平铺字段和 `jd.*` 方法名不符合该正文 |
| 订单详情 | [jingdong.pop.order.get](https://jos.jd.com/apilistnewdetail.html?apiId=15661) | 同一请求容器，`order_id` 为 Number，需 `optional_fields/source_id`；字段选择和响应对象为当前 camelCase schema |
| 售后服务列表 | [jingdong.asc.query.list](https://jos.jd.com/apilistnewdetail.html?apiId=14061) | 请求 `serviceAllQuery`、`pageRequest.pageNumber/pageSize` 及操作人员等业务字段；这是售后服务，不直接证明实际退款资金列表 |
| 售后服务详情 | [jingdong.asc.query.view](https://jos.jd.com/apilistnewdetail.html?apiId=14043) | 请求 `baseRequest` 等嵌套结构；还要继续核实与退款资金明细 API 的关系，不能将 service 完成一概当作退款完成 |
| 当前店铺 | [jingdong.vender.shop.query](https://jos.jd.com/apilistnewdetail.html?apiId=12866) | `venderId` 被标为系统字段；返回 `vender_id/shop_id/shop_name`；其授权注入和 xid 绑定还需联调确认 |

列表时间是 `yyyy-MM-dd HH:mm:ss`；创建/更新时间模式由 `dateType` 控制，1 创建，其他/默认更新；
创建查询近两年，按更新时间的可见范围仅三个月，单窗口最多一个月；排序 `sortType=1` 为降序，其他/默认升序。
响应外层官方拼写为 `jingdong_pop_order_search_responce`；业务成功须继续检查 `orderInfoResult.apiResult`，不能只看 HTTP 200。
`venderId/appKey/pin` 等被 schema 标为 SystemValue 的项与普通必填项不能混淆；下一实现轮须严格处理，而不是要求商家任意传主体值。

公共协议是 `method/access_token/app_key/sign/timestamp/v=2.0/360buy_param_json`；时间是格式化日期而非秒。
签名为 **MD5 大写(secret + 按 key 排序拼 key/value + secret)**，不是旧类中的 HMAC-MD5。
GET 查询串或 POST 表单，业务 JSON 必须封装成 `360buy_param_json` 字符串，不是旧 POST JSON 平铺。
本轮先将 SDK 五个读 operation 标 `partial/supported=false`，CLI 保留五个原工具名称并在网络前抛出明确 ToolError。
没有删除底层其他旧工具；它们仍是历史未验合同，不能用这些 transport 测试声称正式 POP 已支持。
已拿到的 schema 为下一轮真正实现、逐层错误处理、分页以及订单/退款金额字段核验提供了依据；**本轮没有宣称 JD 业务迁移完成**。

新 10 项合同测试先失败后通过；旧五工具的场景改为验证明确 unsupported 和无网络，保留其他工具的 API 错误传播回归。
本地证据 `jd-doc-32/33/298.*`、`jd-api-15660/15661/14061/14043.json`、`jd-shop-detail.json`。
