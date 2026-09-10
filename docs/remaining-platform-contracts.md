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

订单平台实付字段是 `order.order_detail.price_info.order_price`（用户实付，分），支付时间 `payment_info.pay_time` 为秒。
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
响应外层官方拼写为 `jingdong_pop_order_search_responce`；业务成功须继续检查 `searchorderinfo_result.apiResult`，不能只看 HTTP 200。
`venderId/appKey/pin` 等被 schema 标为 SystemValue 的项与普通必填项不能混淆；下一实现轮须严格处理，而不是要求商家任意传主体值。

公共协议是 `method/access_token/app_key/sign/timestamp/v=2.0/360buy_param_json`；时间是格式化日期而非秒。
签名为 **MD5 大写(secret + 按 key 排序拼 key/value + secret)**，不是旧类中的 HMAC-MD5。
GET 查询串或 POST 表单，业务 JSON 必须封装成 `360buy_param_json` 字符串，不是旧 POST JSON 平铺。
本轮先将 SDK 五个读 operation 标 `partial/supported=false`，CLI 保留五个原工具名称并在网络前抛出明确 ToolError。
没有删除底层其他旧工具；它们仍是历史未验合同，不能用这些 transport 测试声称正式 POP 已支持。
已拿到的 schema 为下一轮真正实现、逐层错误处理、分页以及订单/退款金额字段核验提供了依据；**本轮没有宣称 JD 业务迁移完成**。

新 10 项合同测试先失败后通过；旧五工具的场景改为验证明确 unsupported 和无网络，保留其他工具的 API 错误传播回归。
本地证据 `jd-doc-32/33/298.*`、`jd-api-15660/15661/14061/14043.json`、`jd-shop-detail.json`。

## 快手小店：测试用户入口已确认，五个读合同已获得，迁移待实现

[开发者角色说明](https://open.kwaixiaodian.com/zone/docs/dev?pageSign=8291dd5521eb4230e01d789ede994f631635130386865)区分商家自研、第三方服务商和邀约合作伙伴。
商家开发者需对应店铺主体，ISV 是软件服务企业身份；合作伙伴邀约不是普通商家测试申请通道。
[开发流程](https://open.kwaixiaodian.com/zone/docs/dev?pageSign=4852036ba63c13df7f5fd2ddc38169581614263613785)明确审核应用可添加至多 5 个测试用户，
每用户每天 2000 次，主/子账号共同占用一个名额，默认测试授权 10 天；控制台复制 token 有效 48 小时。
这需要已审核应用、测试账号和相应权限；不是匿名发放的独立测试店。
[调用说明](https://open.kwaixiaodian.com/zone/docs/dev?pageSign=8cca5d25ba0015e5045a7ebec6383b741614263875756)明确
`https://gw-merchant-staging.test.gifshow.com` 只用于内部测试、不对外开放；公共正式 API 推荐 `https://openapi.kwaixiaodian.com`。

[授权说明](https://open.kwaixiaodian.com/zone/docs/dev?pageSign=e1d9e229332f4f233a04b44833a5dfe71614263940720)：
网页 `https://open.kwaixiaodian.com/oauth/authorize` 使用 `app_id/redirect_uri/scope/response_type=code/state`。
GET `https://openapi.kwaixiaodian.com/oauth2/access_token` 使用 `app_id/app_secret/grant_type=code/code`，code 两分钟且仅一次。
POST `/oauth2/refresh_token` 使用 `grant_type=refresh_token/app_id/app_secret/refresh_token`；`result=1` 为成功。
AT 的 expires_in 是秒；刷新响应的 RT 剩余期限也是秒；轮换后的 RT 继承最初授权截止时间，不能无限延长；旧 RT 短暂 5 分钟兼容。
`open_id` 是“用户对该开发者的唯一身份标识”，并没有当前商家店铺 ID 的同值保证。

全部五个 API 通过官网文档接口匿名 HTTP 200 获得当前正文、57 个嵌套结构以及官方 Java SDK 1.0.7698；不存在本轮匿名文档阻塞。
证据报告 `ks-schema-findings.md` 和 `ks-schema-manifest.json` 保存了时间、来源及 SHA-256。

| 当前官方方法 | 请求/响应及分页 |
| --- | --- |
| [open.order.cursor.list](https://open.kwaixiaodian.com/zone/docs/api?name=open.order.cursor.list&version=1) | 必填 `orderViewStatus/pageSize/beginTime/endTime/cursor`；页大小<=50、窗口<=7天、时间毫秒；响应 `data.orderList/cursor`，初次 cursor 空、`nomore` 结束 |
| [open.order.detail](https://open.kwaixiaodian.com/zone/docs/api?name=open.order.detail&version=1) | `oid: Long`；响应 `data.orderBaseInfo/orderItemInfo/...`；详情关联售后只包含最新一个，不能用它证明售后全量 |
| [open.seller.order.refund.pcursor.list](https://open.kwaixiaodian.com/zone/docs/api?name=open.seller.order.refund.pcursor.list&version=1) | 必填毫秒 `beginTime/endTime`、`type=8等待/9全部/pageSize/currentPage/pcursor`；窗口<=1天、近90天、size<=100；`data.refundOrderInfoList/pcursor`，`nomore` 结束；page/size/totalPage 仅第一页有效 |
| [open.seller.order.refund.detail](https://open.kwaixiaodian.com/zone/docs/api?name=open.seller.order.refund.detail&version=1) | `refundId: Long`；`data.refundId/oid/status/refundFee/endTime/...`；换货 handlingWay=3 不能因为成功状态计退款 |
| [open.shop.info.get](https://open.kwaixiaodian.com/zone/docs/api?name=open.shop.info.get&version=1) | 无业务参数，`param={}`；`shopName/shopType/shopScoreInfo`，**没有 shopId/sellerId** |

五接口均 GET，将公共参数和 JSON 字符串 `param` 编码到 URL query，版本 1；方法名对应去点为斜杠的正式 path。
公共参数是 `appkey/timestamp(毫秒)/access_token/version/param/method/signMethod/sign`。
官方 SDK 签名是按 key 排序拼 `key=value`、`&` 连接、末尾 `&signSecret=...`；MD5 为小写 hex，HMAC_SHA256 为 Base64。
signSecret 与 OAuth appSecret 不同；旧客户端的 secret+kv+secret、大写 MD5 和旧 `/open/api/...` 路径不符合该合同。
本轮 SDK 五 operation 标 partial/unsupported，防止将错误旧调用暴露给 Pro；CLI 历史工具仍待同一迁移，不属于可执行商家验收范围。

订单查询 queryType=1 创建近90天；2 更新近90天且创建近240天。更新查询仍不等于支付日查询，不能由页闭合推导现金日完整。
订单视图状态与业务 status 是两套枚举；业务状态 10 待付、30 已付、40 已发、50 签收、70 成功、80 关闭。
售后 status=60 成功、70 关闭；handlingWay=1 退货退款、10 仅退款、3 换货；金额与完成时间应由下一轮逐字段归一化核验。
订单权限 merchant_order、售后 merchant_refund；店铺 schema 的 permissionScope 与 permissions 数组有差异，暂不推定 OR/AND。
授权 open_id、订单 sellerOpenId（String）和售后 sellerId（Long）不能合并成同一个主体命名空间。
因此暂不增加 Pro 快手 provider；商家授权测试仍需完成 open_id 与真实店铺主体对应的官方证明或受控核验。

## 巨量引擎 / 巨量千川：广告账户产品，不能冒充订单接口

[巨量引擎入门](https://open.oceanengine.com/labels/7/docs/1696710497745920)要求企业开发者认证、应用审核和接口权限；
[千川入门](https://open.oceanengine.com/labels/12/docs/1697459426498638)使用千川服务类型的应用，与 Marketing API 的应用类型分开，不能凭一个应用推断跨产品权限。
开发者身份、授权用户、投放账户、代理商和店铺授权节点不是一个主体。
公开正文提供可视化 API 调试入口，但仍要求 app/token/业务账户授权；本轮未找到可匿名领取广告账户或千川测试店的公开资源。
这不是证明官方没有合作测试资源；下一步应以企业开发者/应用身份申请可视化联调权限或联系对应平台运营。

[授权申请](https://open.oceanengine.com/labels/7/docs/1803016515293203)由应用管理生成授权链接，包含 app_id、redirect_uri、state、scope 等；
本轮正文未明确展示一个可直接固定的网页授权 origin/path，故未凭记忆实现 Pro URL。
[换码](https://open.oceanengine.com/labels/7/docs/1696710505596940)为 POST JSON `https://api.oceanengine.com/open_api/oauth2/access_token/`，
`app_id/secret/auth_code`，code 十分钟且一次；[刷新](https://open.oceanengine.com/labels/7/docs/1696710506097679)为同 host `/open_api/oauth2/refresh_token/`。
成功 `code=0/data`，AT/RT 各有相对秒 expires_in/refresh_token_expires_in；轮换两种令牌，需要并发刷新保护。
[授权账户](https://open.oceanengine.com/labels/7/docs/1696710506574848)为 GET `/open_api/oauth2/advertiser/get/`，access_token 查询参数，
响应 list 包含 ID、account_role、is_valid 及企业限制；不能从拿到 token 直接假设某个 advertiser_id 可访问。

[千川授权说明](https://open.oceanengine.com/labels/12/docs/1697468161181703)明确授权店铺或代理商层级，后续实时查询子账户；
[千川账户列表](https://open.oceanengine.com/labels/12/docs/1697467748096067)包含 account_id/account_type 和历史 advertiser_id/account_role。
授权用户不固定等于一间店铺，授权树会变化。现有 Pro ProviderToken 单店模型必须先明确绑定角色、节点及子账户 ACL 才能安全增加 provider；本轮没有混用广告 token 作为商家 token。

| SDK 能力 | 当前核验及处理 |
| --- | --- |
| get_advertiser_info | [GET /open_api/2/advertiser/info/](https://open.oceanengine.com/labels/7/docs/1696710508983311)，**host ad.oceanengine.com**，advertiser_ids 数组1–100；Access-Token header；已修正域名并标 documented/live=false |
| get_account_balance | [GET /open_api/2/advertiser/fund/get/](https://open.oceanengine.com/labels/7/docs/1696710526192652)，同 ad host，advertiser_id 数值；余额各字段单位为元，是广告资金，不是店铺营收；已修正域名并标 documented/live=false |
| get_campaign_report / get_ad_detail_report | 当前目录没有核实旧 `2/report/advertiser/get/`、`2/report/ad/get/` 的有效业务正文；需要迁移当前自定义报表合同，SDK 明确 partial/unsupported，不声称接口已经下线 |
| get_qianchuan_report | 已取得[当前全域推广数据报表](https://open.oceanengine.com/labels/12/docs/1823297941140569)：GET `https://api.oceanengine.com/open_api/v1.0/qianchuan/report/uni_promotion/data/get/`；旧 `2/qianchuan/report/ad/get/` 和通用日期字段不能替代新合同，SDK partial/unsupported |
| 订单/退款/店铺 | 广告产品不提供本项目商家订单/退款操作；保持显式 unsupported，不用报表或 advertiser info 冒充 |

千川当前报表必填 advertiser_id、data_topic、dimensions[]、metrics[]、start_time/end_time（yyyy-MM-dd HH:mm:ss）；
还支持 filters(field/operator/values)、order_by、page 和指定大小10/20/50/100/200。
响应 `data.rows[].dimensions/metrics` 和 `page_info.page/page_size/total_page/total_number`；指标可用性和窗口依赖具体 topic，必须结合官方 metadata 核验，不能自行填想象的营收字段。
本轮仅将两条已核实的读请求改用官方 ad 域名，其他历史 CLI 仍待独立迁移；没有执行广告账户生产请求。
原始证据 `oe-doc-*.json/.txt`、`qc-doc-*.json/.txt`；公开文档 API `/skiff/api/doc/client/node/get/` 当前匿名成功，routing identify_key 来自官网公共页面。

## 本轮可执行支持与外部事项

| 平台 | 本轮实现/可受控验证 | 已知代码待办 | 真实验收需要 |
| --- | --- | --- | --- |
| 小红书 | Pro code/refresh+sellerId 绑定；四个业务 SDK 已有官方映射 | 更新窗口覆盖、退款完成时间单位与真实信封复核 | 开发者应用、订单/售后包；官方共享测试店测试 code 或正式主账号授权 |
| 微信小店 | 五个只读 SDK；店铺 GET 修正、售后 cursor/时间修正 | 稳定 token 自研或 component/authorizer ISV provider；详情归一化 | 小店自研 AppID/secret，或上架服务+店铺购买授权；必要出口 IP 白名单 |
| 京东 POP | 现已拒绝已知错误旧读调用；完整新 schema 已取得 | 通用签名/编码、三条订单店铺合同迁移；售后与退款资金语义 | JOS 审核应用、source_id 官方业务来源、POP 店铺授权与匹配权限；预发测试资格需申请 |
| 快手小店 | 五方法完整正文+官方 SDK 证据，SDK 拒绝旧错误调用 | 签名/方法/游标迁移、open_id 与店铺主体绑定合同 | 审核应用、signSecret、merchant_order/refund 权限和已添加测试用户/正式授权 |
| 巨量/千川 | 广告账户资料和余额域名修正；不兼容报告 SDK 拒绝 | 广告/店铺节点授权模型；当前报表 topic/metrics 迁移 | 企业开发者、对应产品应用权限、有效授权账户树；无已确认匿名测试账户 |

所有 documented 均仅指官方文档与受控请求合同；所有 live_verified 均 false。
本轮不把已取得 schema 但未实现的工作转写成“需要商家凭据才能完成”，代码迁移与账号卡点分别列明。


R16 收束实跑：新增 KS/OE 合同 10 项先失败后通过，相关 SDK/协议/OE 工具 254 项通过；
CORE 完整套件 **1976 passed、20 subtests passed**（2026-09-10），未运行生产接口。
Black/Ruff/mypy 通过，本轮 JD/OE/SDK 模块 Pylint 10.00。无 Pro 全量或 Docker 验收声明。
