# 抖店归一化合同

2026-09-10 直接核对[订单列表 schema](https://op.jinritemai.com/docs/api-docs/15/1342)、
[售后详情 schema](https://op.jinritemai.com/docs/api-docs/17/1095)、
[买家实付 FAQ](https://op.jinritemai.com/docs/question-docs/89/2019)和
[商家实收 FAQ](https://op.jinritemai.com/docs/question-docs/89/2199)。完整请求、窗口、
权限与响应位置见 [doudian-contract.md](doudian-contract.md)。

## 订单

状态映射修正为 4=取消、5=完成，补充 105=已支付、101=部分发货；101 映射为统一
shipped，仍通过 status_raw=101 保留部分发货事实。支付日报按 paid_at 归属，曾支付后
取消的订单不能单凭最终取消状态从支付流水中消失。

amount_paid 是买家现金实付：pay_amount 减 promotion_pay_amount，两个字段必须有值、
为有效非负分值且优惠不大于平台支付金额。缺少支付优惠、旧工具仅有 amount，均返回
未知和 warning。amount_platform_payment 单独保留 pay_amount；商家新实收字段
actual_receive_amount_info.actual_receive_amount 放在 amount_merchant_received。
订单总价仅使用明确的 order_amount/total_amount，不拿平台支付金额冒充总价。

支持原生 sku_order_list，数量为 item_num、单价为 origin_amount、图片为 product_pic；
订单优惠使用 promotion_amount。updated_at 使用 update_time，不替代支付时间。

## 售后

列表 items[].aftersale_info 与详情 process_info.after_sale_info 分开处理。
列表 refund_amount 和详情 refund_total_amount 是申请/总退款口径，保存在
amount_requested。实际 amount 仅在资金退款状态 refund_status=3 时读取
real_refund_amount；完成时间只使用 refund_time。缺字段仍为未知，不能用申请额、
售后终结时间补齐。负的实际退款金额返回未知并标记 refund_amount_negative。
状态5表示追缴成功，统一标为 reversed，不能并入普通退款成功。

详情 after_sale_id 和 order_info.shop_order_id 是 int64，转成字符串关联列表ID。
列表没有真实付款金额/完成时间，即使售后状态显示成功，也有 refund_detail_required
警告。售后种类按 after_sale_type/aftersale_type 保留退货、仅退款、换货、价保、补寄、
维修的区别；原生数字 refund_type 表示处理方式，不能当作售后种类。

这些修正改变旧错误语义。已保存的旧归一化记录需要从原始数据重算；没有原始支付优惠
或售后详情时无法恢复真实数值。完整日报还依赖采集覆盖，不会因为归一化成功就宣布
历史/跨日事件已经取全。新增 dataclass 字段置于原有字段末尾，保留既有位置参数顺序。

## 验证

新增22个官方合同回归；最初14项失败准确暴露状态、支付优惠、退款ID/实际金额的问题。
独立审查新增原生商品价格/优惠和退款种类/负金额回归，均先复现失败再修复。
同时更新旧合成样本，使其提供已确认的支付优惠或真实退款字段；保留坏商品、坏元数据
不能丢失有效金额的回归。测试使用官方形状的固定样本，不是商家真实对账验收。
