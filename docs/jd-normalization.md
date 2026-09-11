# JD POP 订单源归一化规格

2026-09-10；依赖 [JD SDK 合同](jd-contract.md)及当前官方
[订单列表](https://jos.jd.com/apilistnewdetail.html?apiId=15660)、
[订单详情](https://jos.jd.com/apilistnewdetail.html?apiId=15661)、
[店铺资料](https://jos.jd.com/apilistnewdetail.html?apiId=12866) schema。
原始 JSON 位于 /private/tmp/remaining-platform-evidence-20260910/jd-api-15660.json、
jd-api-15661.json、jd-shop-detail.json；无商家凭证和 live 验收。

现代原生 orderInfo 的 actualPay 才是平台买家实付（元），freightPrice 为运费元。
shouldPay 是应付，orderPayment 已停维护，totalSellerReceivable 是商品应收而不是已收；
totalOriginalPrice 仅商品原价合计，不作为含费用的订单总金额，均不冒充 amount_paid。
支付时间仅 paymentConfirmTime，0001-01-01 00:00:00 是未支付哨兵，映射未知；
收礼订单支付时间可早于 orderStartTime，不据此拒绝合法订单。
modified 是源更新时间，不替代付款时间。状态只描述流程，不产生支付日期或成功退款。
等待出库包括货到付款、月结、先用后付和分批支付；只有已知 actualPay 和有效付款确认时间
同时存在时才映射 paid，否则保留 status_raw 并标 unknown。
15661 的 actualPay 明确不支持京喜订单。tradeOrderId 在15660/15661均明确仅京喜供销二段订单
返回；列表或匹配详情带此非空标记时金额强制未知并发出 buyer_payment_unknown，不能用占位金额。
该标记不是全部京喜订单的完整分类；未取得其他京喜业务类型映射，不推测 orderType 代码。
原生 itemInfoList[].wareId/skuId/itemTotal 分别为商品/SKU/数量；
详情 jdPrice 是下单时不变的 SKU 京东价，元单位由官方 totalOriginalPrice（元）=
ΣSKU京东价*SKU数量公式推导，保留该推导依据。数据仍为平台口径，不是银行现金或结算。

`pro.sources.jd.JdSource` 只支持 orders；refunds 明确 unsupported，售后服务单不当作退款资金。
query dateType=1 创建、0 修改，sortType=0 显式升序；page/page_size 是十进制字符串，
页1起/大小<=100，最多1日历月的单窗口，创建近2年/修改近3个月。
source_id 固定显式传 JOS：15660/15661 原始 schema 的 source_id.defaultValue 为 JOS，
这是本 Source 对该官方来源的选择；不允许客户端覆盖系统 venderId。
本项目设10000页本地预算，不是官方深度保证。窗口右端是否包含未确认，按重叠补查去重；
total 和唯一ID闭合不是平台快照或完整支付覆盖证明。

`JdSource.fetch(grant,job,page,size,call,*,source_timezone=None)` 要求操作者显式业务时区，
不把签名采用中国时间当作所有响应字段的时区证明。先调用 get_shop_info 无业务参数，
比较返回shop_id与grant.shop_id，再以返回vender_id核对每条订单venderId；
venderId不是shop_id。故需orders:read和shop:read。每页重新验证，不能把商家身份放进
LLM参数或跨进程全局变量。订单逐条补详情，ID/vendor/modified须一致；缺失源时间拒绝。
支付字段延迟、相同源版本下金额变化、快照不稳定仍是需要补采/对账的缺口。

只存指标白名单、原生版本和平台确认店铺绑定；不存买家、备注、商品自由文本或raw异常。
本页验证独立 Source；运行时入口是否配置完成应以 Pro capabilities、时区配置和当前授权为准。
JD OAuth主体绑定与刷新provider尚未实现，不因受控Source测试通过就声称商家可直接授权使用。
既有调用者显式指定金额单位的历史 normalizer 输入形状保留兼容；含 venderId/modified/
actualPay/paymentConfirmTime 任一现代标记即使用本合同，禁止回退历史应付字段充当实付。

测试首先取得 Core 新合同15失败/4通过、Pro 23失败；独立审查的待出库状态及京喜例外
新增回归10失败后修复。当前 Core JD新合同28项；与既有归一化及 DD/TOP/Youzan 组合共282项。
Pro JD源44项，连同 privacy/commerce/warehouse 共173项。两种查询模式均经过真实 Commerce→SDK→HTTPX MockTransport→
指标投影→加密 Warehouse，测试包括第二实例恢复、固定total、缺失/冲突时间、店铺/vendor混淆、
明细ID/版本冲突与显式空页。时钟浮点集成回归另经1失败→6通过，兼容真实 time.time()。
Black、Ruff、mypy通过，修改的生产模块Pylint10.00。以上均非真实京东商家 live 验收。
独立审查已复跑 Core28项及 Pro京喜列表/详情/同时存在三种情况；待出库支付证据问题已关闭。
