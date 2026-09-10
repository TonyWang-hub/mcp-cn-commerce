# 抖店订单与售后合同续验

核查时间：2026-09-10。直接读取官网公开前端所调用的
`/doc/external/open/queryDocArticleDetail?articleId=...` 返回 JSON；没有商家凭证，
没有向商家业务 API 发请求。知识库六月报告明确是受限网络下的推测示例，只用来寻找名称。

## SDD 本轮范围

修正已核实的订单列表、订单详情、售后列表、售后详情路由及业务参数；防止官方响应
解析失败后被当成空页。SDK 返回官方 data 信封，MCP 工具保持原命名和 orders/order/refunds
包装。共享 `servers.doudian.schema` 提供字段构造、验证和投影，供 Pro 复用。

先建立官方形状的 HTTPX 和工具回归（RED），再替换路由/分页参数/解析（GREEN），
最后运行完整回归。店铺基础信息没有找到通用合同，明确标不支持；不增加虚构接口。

## 已取得的官方来源

| 内容 | 官方页面 | 版本 / 更新时间（UTC） |
|---|---|---|
| 订单列表 | https://op.jinritemai.com/docs/api-docs/15/1342 （旧555重定向同内容） | V22.27 / 2026-08-31T09:29:18Z |
| 订单详情 | https://op.jinritemai.com/docs/api-docs/15/1343 | V29.58 / 2026-08-31T09:31:48Z |
| 售后列表 | https://op.jinritemai.com/docs/api-docs/17/1295 | V19.16 / 2025-04-27T06:02:11Z |
| 售后详情 | https://op.jinritemai.com/docs/api-docs/17/1095 | V19.36 / 2025-12-31T03:19:29Z |
| 买家实付计算 | https://op.jinritemai.com/docs/question-docs/89/2019 | V1.01 / 2023-03-06T07:40:31Z |
| 商家实收计算 | https://op.jinritemai.com/docs/question-docs/89/2199 | V1.01 / 2025-10-28T07:13:34Z |
| 售后列表金额口径 | https://op.jinritemai.com/docs/question-docs/93/7259 | V1.01 / 2025-02-11T03:01:20Z |
| 订单历史范围 | https://op.jinritemai.com/docs/question-docs/89/4130 | V1.01 / 2023-07-26T09:01:38Z |
| 公共协议 | https://op.jinritemai.com/docs/guide-docs/10/23 | 2024-06-24T12:02:00Z |

原始完整 JSON 暂存 `/private/tmp/doudian-contract-evidence-20260910/`，包括
`order-list.json`、`order-detail.json`、`refund-list.json`、`refund-detail.json`、
FAQ 和 `directory.json`。目录由官方当前前端实际使用的
`/doc/external/open/QueryDocDirTreeNew?dirId=3&withArticleList=true&articleOrderType=3`
获得。完整 schema 原文不作为商家实测数据提交。

## SDK 和采集器的原生合同

四个SDK操作名不变。`get_refund_detail` 本轮变成可调用，`get_shop_info` 标为不支持。
`operation_catalog("doudian")` 可在授权、刷新 token 及所有网络请求之前查看状态。
状态 `documented` 只表示本轮读取了请求/响应合同，`live_verified` 仍全部为 false。

| SDK operation | 签名 method / HTTP path | 请求核心字段 | SDK返回 data 中的记录位置 |
|---|---|---|---|
| get_order_list | order.searchList / /order/searchList | page、size、create_time_start/end 或 update_time_start/end | shop_order_list[]，total、page、size |
| get_order_detail | order.orderDetail / /order/orderDetail | shop_order_id（平台生成的店铺父订单号） | shop_order_detail |
| get_refund_list | afterSale.List / /afterSale/List | page、size；start_time/end_time或update_start_time/update_end_time | items[]，total、has_more、page、size |
| get_refund_detail | afterSale.Detail / /afterSale/Detail | after_sale_id；可选need_operation_record | process_info.after_sale_info；关联订单order_info |

SDK的业务参数是原生字段。MCP工具继续接受原有 `start_time`/`end_time` 日期字符串，
新增 `time_type=create|update`；无时区日期按 Asia/Shanghai 转换为整数秒。
订单的 `order_id` 输入只是 `shop_order_id` 的兼容别名，不能当成商家自定义外部单号；
同时提供两个不同值时拒绝。MCP通用店铺基础信息工具保持名称，返回显式unsupported而不发请求。

### 分页、时间和完整性

- 两个列表都是从第0页开始，`size`为1至100的整数。订单返回`total`，可以在固定查询条件下
  用已采集数量与total核对；售后额外有`has_more`。每一页必须保留相同窗口和排序。
- 订单创建时间字段为 `create_time_start`/`create_time_end`，秒；更新时间使用
  `update_time_start`/`update_time_end`。更新轮询应选 `order_by="update_time"`，
  `order_asc=true`。订单列表没有支付时间过滤器。
- 订单列表只覆盖近90天创建的订单；详情没有此历史限制。因此，一个更早创建且今天更新/支付
  的订单不能单靠今天的列表轮询保证找到。需要持续历史库、消息或已知订单号补查；超过90天的
  首次历史回填需商家后台导出。不能把“近90天订单列表翻完”标成无限历史的支付日报覆盖完整。
- 售后申请窗口 `start_time`/`end_time` 使用秒，官方明确为包含开始、不包含结束。
  更新窗口使用 `update_start_time`/`update_end_time`，并必须配合
  `order_by=["update_time asc"]` 或desc；官方警告缺少此排序会漏轮询数据。
  更新结束字段的描述误写了“包含开始值”，本次无法确认其右边界，应重叠边界并按ID及版本去重。
- 售后 `page * size` 最大50000，超过需切分时间范围。默认仅查询近6个月；更早必须显式传时间。
  `aftersale_status_to_final_start_time/end_time` 是售后终结筛选，只支持近6个月终结数据，
  不是退款成功时间筛选。
- 官方schema没有给出订单的固定单次最大时间跨度、稳定快照保证、更新时间筛选下total一致性保证
  或请求期间新增/修改订单的强一致性。建议短窗口重叠补拉、ID去重、记录每页total和重复页、
  空页/has_more矛盾，并在条件变化或无法闭合时返回不完整。该建议是本项目采集策略，不能标成官方保证。

### 金额与日期，供Pro归一化复用

| 记录路径 | 意义 / 单位 | 处理 |
|---|---|---|
| shop_order_list[].order_id / shop_order_detail.order_id | 平台店铺父订单ID | 是订单去重层级；sku_order_list[].order_id是商品子单，不能都算订单数 |
| 同一店铺单.pay_amount | 平台支付金额，分，包含支付渠道优惠 | 不直接命名为买家实付 |
| 同一店铺单.promotion_pay_amount | 支付渠道优惠金额，分 | 买家实付 = pay_amount - promotion_pay_amount；字段缺失不能默认零 |
| 同一店铺单.actual_receive_amount_info.actual_receive_amount | 新版商家实收字段 | 与买家实付分开，不拿它替代GMV口径 |
| 同一店铺单.pay_time/create_time/update_time/finish_time | 支付/创建/更新/订单完成时间，秒 | 日报按选择的业务日期归属；更新和完成不代替支付 |
| 同一店铺单.order_status | 1待支付、105已支付、2备货、101部分发货、3全发货、4取消、5完成 | 之前把4标已收货、101标取消的描述已修正；取消单仍需检查是否曾支付 |
| items[].aftersale_info.aftersale_id | 售后ID | 用于调用详情的after_sale_id |
| process_info.after_sale_info.after_sale_id | 详情返回int64；列表ID和详情请求ID为string | 服务端统一转字符串关联；前端须防止超过JavaScript安全整数范围造成精度丢失 |
| items[].order_info.shop_order_id | 关联店铺父订单ID | 用于订单/退款关联，不用SKU ID当父订单 |
| items[].aftersale_info.refund_amount | 售后申请/总退款金额，分，与详情refund_total_amount口径一致 | 不当实际退款金额；列表投影amount=None并detail_required=true |
| process_info.after_sale_info.real_refund_amount | 实际退款金额，分；成功后才记录扣除支付补贴回收后的值 | 只在refund_status=3且实际值存在时计入退款成功指标 |
| process_info.after_sale_info.refund_time | 最终原路退到用户账户的成功时间，Unix秒 | 用于成功退款日归属；不能用apply_time或update_time补缺 |
| 同一售后详情.refund_status | 1待退款、2退款中、3成功、4失败、5追缴成功 | 5是追回款项，不应归入普通退款成功 |
| 同一售后详情.after_sale_status | 售后流程状态；12成功、14换补修收货、51取消成功、53逆向结束等 | 与资金退款状态是两个维度，售后流程结束不自动表示已退款 |
| 同一售后详情.aftersale_status_to_final_time | 平台综合判断的售后终结时刻 | 不替代refund_time，换货/补寄/维修也可能结束但没有退款 |

当前SDK保留原生完整data。`servers.doudian.schema.project_order`仅增添命名清楚的便利字段，
原始支付字段仍保留；`project_refund`明确保留申请金额与缺少详情的事实。
跨平台归一化和日报最终金额口径由Pro后续接入，不在本轮悄悄更换共享normalizer。

## 鉴权与尚未核实事项

公共请求仍是POST，路径对应方法，规范化业务JSON放body，其他公共字段放query，
HMAC-SHA256签名以app_key/method/param_json/timestamp/v的固定顺序。调用指南明确优先Unix秒，
也兼容GMT+8日期格式；各API公共参数模板仍显示旧日期样例，因此保留当前秒时间戳实现。

完整当前API目录的店铺类目中没有通用 `/shop/basicInfo` 或 `/shop/getShopInfo`。
目录里的 `/instantShopping/shop/getShopInfo` 属于即时零售业务，不能据此替代普通抖店。
本轮不宣称所有可能隐藏/历史权限下的店铺信息接口都不存在；只把未取得通用合同的操作拒绝。
商家身份先以OAuth授权返回的shop_id绑定，并用已授权订单列表执行首个真实业务读取。

仍需实际应用资质、接口权限包、已授权店铺凭证、订单/售后样本来验收：真实首次查询、
两页以上结果与商家后台核对、字段权限完整性、权限失效及限流返回、支付/退款金额日对账。
官方文档的固定限额数值不能代替该应用控制台的实际额度。

## 本轮实际验证

2026-09-10：先运行错误路由/参数/响应形状的RED，再实现修正；补充缺少业务ID的
malformed-200 RED，以及官方售后详情int64 ID回归。最终结果：

- DD合同24例与SDK74例共98例通过。
- Python 3.12.3与3.14.6完整套件分别1684 passed、20 subtests passed。
- 全仓Black/Ruff通过；mypy覆盖servers/shared/tests共64个源文件通过；
  DD客户端/服务/schema和SDK的Pylint 10.00/10，Bandit无问题。
  全仓Pylint最初只发现其他7个server.py的同名导入别名，已交由并行集成修改与重验。
- 独立构建wheel与sdist，并通过twine check；新wheel实际安装进独立Python 3.12环境。
  在非源码目录运行全部24个真实MCP stdio场景：8平台注册表入口、独立CLI入口、缺凭证处理均通过。
- 安装后的wheel另跑四条DD SDK官方形状HTTPX请求，通过且没有导入MCP server模块。
  工具元数据仍为8平台、155工具；git diff --check通过。

测试响应为按官网schema构造的固定数据；上述MCP握手和包验证不包含商家业务API验收。
完整测试与构建日志位于`/private/tmp/doudian-contract-*-final.log`及
`/private/tmp/mcp-doudian-contract-*-final.log`；安装包位于
`/private/tmp/mcp-doudian-contract-dist-final-20260910/`。未启动本机容器。
