# TOP / 有赞归一化与固定窗口采集合同

2026-09-10，先规格和失败回归，再实现。依赖同日已经逐字段读取的
[TOP接口合同](taobao-contract.md)与[有赞接口合同](youzan-contract.md)。原始官方正文在
/private/tmp/taobao-youzan-contract-evidence-20260910；本轮再次核对请求排序、退款字段和金额说明。
所有金额输出为整数分；缺失、歧义与非法金额保留None及固定warning，不拼出交易发生时的事实。

## 归一化

- TOP trade.payment（元）会受售后影响，保存为amount_platform_payment；amount_paid始终未知并标记
  buyer_payment_unknown。received_payment仅映射商家已收。tid是父单，orders.order为SKU数组，
  num_iid/sku_id/price（元）/num分别保留；TRADE_CLOSED是付款后退款关闭，不等同未付款取消。
- TOP退款只有SUCCESS且dispute_type属于REFUND/REFUND_AND_RETURN才计refund_fee（元）为amount；
  end_time是退款完结时间，不宣称渠道到账。非退款诉求、缺失类型不能因SUCCESS计现金退款。
  created/modified分别为申请/版本时间，不用modified补end_time。列表已含上述字段；无需用不含
  modified的refund.get去拼接一个无法验证版本的“详情快照”。
- 有赞订单识别full_order_info（亦可位于data内），order_info的tid、created、update_time、pay_time
  与node_kdt_id保留。pay_info.real_payment（元）才映射实付；payment在列表/详情语义不同，不映射
  为历史实付或订单总价。total_fee为商品总价、post_fee为运费，orders中item_id/sku_id/price/num。
  real_payment只表示平台的整单实付，支付类型还包括储值卡、E卡、礼品卡、余额、抵扣、组合支付；
  不能据此推导银行现金流、商家结算额或资金渠道净额。报表只能沿用“平台买家实付”口径。
- 有赞退款列表refund_fee为申请元金额，不能映射实际退款。详情refund_fee（元）只用于和资金明细
  核对；refund_fund_list非空、流水refund_no不重复、全部status=2、全部refund_mode=0，且分值合计
  与顶层元金额相等时才发布amount。此外每条pay_way必须属于官方列明的非零渠道枚举。
  原路退回储值/E卡/礼品/会员余额，或明细混合多个已确认渠道，仍属于平台记录的已完成退款，
  保留分值；不能因非现金渠道把该金额丢弃。缺失、0默认未支付、非法或未确认渠道统一
  amount=None与refund_channel_unknown，不只加总混合明细的已知部分。本轮refund_mode=1现金退、
  2标记退仍明确不支持，不把人工记录推导为已确认原路退款。因此整体渠道覆盖仍未验证。
  报表口径是“平台记录的买家实付与已完成退款”，不声称银行入账或商家最终结算。
  卡本金/赠送金的会计分拆另需资金账单。换货SUCCESS不计金额。
  渠道/模式/状态取自[官方退款详情](https://doc.youzanyun.com/detail/API/0/4069.md)的
  refund_fund_list；实付和支付类型取自[官方订单详情](https://doc.youzanyun.com/v2/doc/cloud/token/N1PewEBlii4MlBk4mw5cwezYnke.md)。
  completed_at仅取refund_account_time，不用refund_success_time补齐。列表申请额由采集器另存
  amount_requested，详情自身不假定具有申请口径。缺失或矛盾资金信息保留None与固定warning。
- 通用Normalizer不默认为naive日期补时区。TOP采集器按公共协议GMT+8显式解释。YouzanSource
  要求调用方显式传source_timezone；当前公开业务正文未核实统一时区，Asia/Shanghai只能是经
  部署确认的配置假设，不能写成官方保证。不依赖宿主本地时区。

## 采集器边界（Pro）

静态async fetch(grant,job,page,size,call)返回SourcePage。page为0起逻辑步骤，cursor仅保存
page/size/total/phase。每job一个固定窗口，列表与游标total必须一致，长度/ID/边界/详情版本冲突失败。
SDK网络由宿主的call完成；该函数负责租约、许可、超时与当前授权。页原子发布与去重由Warehouse完成。

TOP先请求native page_no=1取得total，再从ceil(total/size)向1逆向消费；探测页不单独发布。
订单update调用get_increment_orders（单窗口<=1天，建议30分钟），create调用get_order_list。
订单仅支持近3个日历月内创建交易，订单窗口也按此上限拒绝过早查询；退款API仅修改时间筛选，
退款create模式明确不支持，不偷换成更新时间。TOP未指定type时只涵盖接口默认交易类型，不代表
所有特殊交易；返回count闭合也只证明当前API筛选。没有跨页稳定快照保证，等量替换仍需业务对账。

有赞page_no=page+1，最多100页；订单窗口<=3个日历月，2020年前订单当前API不支持；退款
page_no*page_size<=3000，显式时间过滤不把默认近3个月错误说成硬保留期。订单每条补详情
real_payment，退款每条补资金详情；ID、父单、列表/详情modified版本与店铺必须一致。
有赞订单要求node_kdt_id精确匹配grant.shop_id，不能仅凭root_kdt_id总部匹配将多个门店合计贴到
一个授权店铺。退款列表node/kdt及详情kdt均核对。商家总部全组织授权范围尚不在本轮模型内。

合同测试和HTTPX受控SDK验证与商家实测分开记录；本轮live未验，不声明报表资金日完整性。

## 实际验证记录

CORE首次合同回归31失败、7通过，实施后包含既有DD与normalizer回归106通过。
自审发现未知/非法有赞refund_type仍可被return_goods推断为现金退款，新增4项失败回归后，
仅已确认BUYER_APPLY_REFUND/SELLER_REFUND/SYSTEM_REFUND详情允许资金计算；未知类型保留未知。
最终新合同43项通过，CORE完整套件1806 passed、20 subtests passed（2026-09-10同一协作快照）。
Black/Ruff/mypy通过，normalizer模块Pylint 10.00；没有回退DD 45f7875。

Pro Source首次27失败，再经真实CommerceService→GrantService→SDK→HTTPX MockTransport发现并修复
隐私投影遗漏num_iid、dispute_type、received_payment、return_goods、refund_mode。资金不完整/金额
矛盾/渠道未知分别使用固定refund_funds_incomplete/refund_amount_mismatch/refund_channel_unknown。
新Source回归44项，联合privacy/warehouse/commerce共173项通过。覆盖TOP倒序分页及SQLite重开、
两个租户并发不同token、Youzan列表详情版本核对、三月日历边界、上限、缺total、重复/空页、
未配置时区、禁止原始错误与自由文本warning入库；Black/Ruff/mypy通过。

所有HTTP均由MockTransport截获。未拿Mock成功声称真实商家token、店铺权限或资金到账已验。

同日独立审查补充：原路退款并不等于银行现金退款。统一平台实付/完成退款口径后，
59个官方非零支付渠道分别验证单一/混合明细，储值、礼品、余额等保留确认金额；
缺失/0/未知/非法渠道、失败资金和人工退款模式保持未知。新阳性先96项失败，修复后
TOP/有赞归一化186项、加DD共208项通过；Pro source/privacy/warehouse/commerce 179项通过，
包括真实CommerceService→SDK→HTTPX→隐私投影→Warehouse的直付、礼品、未知和混合渠道。
Black/Ruff/mypy通过，normalizer Pylint 10.00。两名独立审查者核对官方渠道与源范围后通过。
中途全Core运行1869 passed、20 subtests、30项JD旧契约失败，已交JD并行修复者处理；
这次不把该全仓快照记为全绿。最终发行仍须另跑当前提交的完整流水线。
