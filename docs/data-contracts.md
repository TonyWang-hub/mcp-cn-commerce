# 归一化与日报数据契约

`shared.normalizer.Normalizer` 处理已从响应包装中提取的单条记录。
`shared.aggregation.build_daily_report` 处理多店铺记录列表，执行确定性的日期筛选、去重和汇总。
公共 MCP 工具 `build_daily_report` 暴露相同能力；它不会自行申请授权、调用平台或遍历分页。

## 金额与时间

- 统一金额为 CNY 整数分。使用 `Decimal(str(value))`，禁止二进制浮点乘 100 后截断；有小于一分的精度时返回 `None` 和 `fractional_fen`，不自行舍入交易金额。
- 订单、退款、商品、SKU、评价和店铺 ID 仅接受字符串或整数；布尔值、对象、列表和浮点数不会转成字符串冒充 ID，输出空字符串并给出身份字段警告。
- 缺失、脏值、非有限值、单位未知均返回 `None`。真实 `0` 保留为零。某个商品数量损坏不会清空整单金额。
- 记录的 `source_values` 保留金额及时间原始字段；`warnings` 为 `[{"field": "amount_paid", "code": "amount_unit_unknown"}]`。不要把含原始业务值的对象直接写入公共日志。
- 单位按照**字段**指定：`Normalizer(amount_units={"jd.payment": "yuan", "jd.orderTotalPrice": "fen"})`。`平台.字段` 优先于 `字段`，然后才是模块内明确列出的输入 schema。
- 内置 `_MONEY_SCHEMA` 描述这个模块接受的字段形状，**不代表已经核对了一个平台所有接口版本的单位**。京东、淘宝和广告字段没有通用单位默认值；必须按所用接口文档填 `amount_units`。其余平台换接口/版本同样要逐字段核对，不能根据字段名或金额大小猜单位。
- 旧的两参数 `normalize_price(value, platform)` 保留历史 helper 单位兼容；提供 `warnings` 时标记 `legacy_platform_unit`。新的记录归一化不使用这个平台级兜底。业务代码应提供 `unit="yuan"` 或 `"fen"`。
- 支持秒、毫秒、数字字符串、ISO 8601 和带偏移时间。自动识别数值绝对值至少 `1e11` 为毫秒；历史小值应显式设置 `timestamp_unit="seconds"|"milliseconds"`。
- 无时区时间不再直接贴 UTC 标签。直接调用 normalizer 时，未提供 `source_timezone` 会保留不带偏移的 ISO 字符串并给出 `timezone_missing`；日报拒绝将它归到某天。DST 重复或不存在的当地时间不会自动猜测。
- `pinduoduo` / `weixin_store` 可作为输入别名；输出统一使用原有 schema 标识 `pdd` / `weixin`，去重与店铺边界也按这套标识比较。

```python
from shared.normalizer import Normalizer

n = Normalizer(source_timezone="Asia/Shanghai", amount_units={"jd.payment": "yuan"})
order = n.normalize_order({
    "orderInfo": {
        "orderId": "JD-1",
        "orderState": "WAIT_SELLER_STOCK_OUT",
        "payment": "19.99",
        "paymentTime": "2026-09-10 09:30:00",
    }
}, "jd")
assert order.amount_paid == 1999
```

## 日报输入

Python：`build_daily_report(date, shops, *, timezone, top_n=3)`。
MCP：`build_daily_report(shops_json, report_date, timezone)`，其中 `shops_json` 是下例 `shops` 列表的 JSON 字符串。

每家店铺必须有 `platform`、`shop_id`，可有 `shop_name`。同一店铺的所有分页先合并到一条 shop；不同平台或不同店铺的相同订单 ID 互不冲突。

- `input_format="normalized"` 为默认，`orders` / `refunds` 接受统一 dataclass 或其字典。金额必须已经是整数分，时间应含明确 UTC 偏移。
- `input_format="raw"` 接受已提取的原始订单/退款列表，内部使用 `Normalizer(source_timezone=timezone, amount_units=shop.amount_units)`。这里显式指定的 `timezone` 也表示无偏移原始时间的来源时区；若来源时区不同，请先独立归一化再使用 normalized 模式。
- 抖店也接受本项目工具的实际投影：`get_order_list()["orders"]` 中 `amount` 是原 `pay_amount` 的**分**值，`product_info` 是商品列表且 `quantity` 是数量；`get_order_detail()["order"]` 的商品列表名为 `products`。这个 `amount` 付款别名仅适用于抖店，不会推广到其他平台。
- 抖店 `get_refund_list()["refunds"]` 的 `amount` 同样保留原退款分值；工具仅透传上游真实存在的 `completed_at` / `refund_time` / `success_time`。只返回 `create_time` / `update_time` 时不能推断退款完成时间，已完成退款对应日报保持不完整。
- `orders` 和 `refunds` 字段必须显式提供。缺失列表产生 `source_missing` 并令对应指标不完整，即使声明了 coverage=true；只有明确的空数组 `[]` 可以表示已确认没有记录。
- `coverage[日期].orders=true` 和 `.refunds=true` 是调用方对当日对应事件范围**全部分页成功拉完**的明确声明，默认不是 true。不能因为列表不为空或某页很短就推断取全。
- 订单指标以**付款时间**为日界，退款指标以**完成时间**为日界。如果平台列表仅按创建时间/申请时间筛选，必须补足跨日创建但当日付款/完成的记录，否则不能声明该事件范围 coverage 完整。
- `errors` 保存未解决的上游失败；存在任何失败时，该店铺完整指标不公布。修复并补抓失败分页后再清空。输出只转发错误码，不转发可能含凭证的任意上游错误正文。

```python
from shared.aggregation import build_daily_report

shops = [{
    "platform": "doudian",
    "shop_id": "shop-001",
    "shop_name": "示例店铺",
    "input_format": "raw",
    "orders": [{
        "order_id": "order-001",
        "order_status": 2,
        "pay_amount": 1999,
        "pay_time": "2026-09-10 09:00:00",
        "product_info": {"list": [{
            "product_id": "product-001", "product_name": "示例商品",
            "price": 1999, "combo_num": 1,
        }]},
    }],
    "refunds": [],
    # 示例假定这两天已完成所需全部分页；真实调用不能照抄声明。
    "coverage": {
        "2026-09-10": {"orders": True, "refunds": True},
        "2026-09-09": {"orders": True, "refunds": True},
    },
    "errors": [],
}]
report = build_daily_report("2026-09-10", shops, timezone="Asia/Shanghai")
assert report["total_summary"]["gmv"] == 1999
```

## 输出与指标口径

输出可供 `templates/daily-report` 使用：`date`、`shops[].summary`、`shops[].yesterday`、`shops[].top_products`。
同时提供 `total_summary`、`yesterday_summary`、`completeness`、`errors` 和 `warnings`。

| 字段 | 确定含义 |
| --- | --- |
| `order_count` | `paid_at` 落在指定时区日期内的唯一付款订单数，不以创建时间或当前状态代替付款事件 |
| `gmv` | 这些订单的 `amount_paid` 之和，整数分；未减退款，不表示结算到账收入 |
| `avg_order_value` | GMV / 付款订单数，展示值按 half up 舍入到分；零订单时为 null |
| `refund_count` | `completed_at` 在当日、状态 completed 的唯一退款单笔数，可来自前日订单 |
| `refund_order_count` | 当日完成退款涉及的唯一原订单数 |
| `refund_amount` | 当日完成退款金额之和，不用申请时间代替完成时间 |
| `refund_rate` | 当日付款订单中，当日已经完成过退款的订单占比；**不是最终生命周期退款率**，也不等于退款笔数 / 付款单数 |
| `same_day_refunded_order_count` | 上述退款率分子，可用于跨店铺加权合计 |
| `top_products[].sales` | 当日付款订单中可确认的商品数量；只有所有商品行都可计算时才发布完整排名 |
| `top_products[].gross_item_amount` | 单价 × 数量；尚未分摊订单优惠、运费，因此商品 `gmv` 保持 null |
| `new_customer_count` / `repeat_customer_count` | 缺少历史客户数据，始终 null |
| `low_stock_alerts` | 没有库存输入，null，不表示“无库存风险” |

同 ID 且内容完全一致的重复记录去重；同 ID 内容冲突的记录全部隔离，并将相关完整性降为失败。
未知付款时间、退款完成时间、订单归属冲突、缺失记录 ID 不能静默跳过并声称汇总完整。

`complete` / `yesterday_complete` 分别表示付款和退款核心指标是否具备完整数据。
`shops[].completeness[日期].metrics` 给出每项指标是否可发布；例如金额未知时订单数仍可完整，GMV 必须为 null。
只要一家店铺相关指标不完整，跨店铺相应总数也为 null。已确认取全且没有记录时才输出真实零。

`observed_summary` / `observed_yesterday` 只描述已得到的有效记录或金额，
应在界面明确标成“已获取部分”，**不能被模板拿来填完整总数**。
金额未知记录的数量可由 `known_paid_amount_count` / `known_refund_amount_count` 看出。
商品行不完整时 `top_products=[]`，可查看 `observed_top_products`，但不能称其为全店 Top N。
报告不提供自动原因归因；没有广告、流量、库存和评价证据时，不应编造下降原因。

## 看板告警生命周期

`MonitoringDashboard(max_alerts=1000, max_alert_rules=1000)` 对历史告警和规则数量分别设上限。
同规则持续超阈值只更新一个 active 告警；恢复后改为 resolved，再次越阈值创建新事件。
相同规则重复添加不会增加状态。删除规则会关闭对应 active 事件，`clear_alerts()` 清理历史和活动事件，`reset()` 同时清理规则。
超过历史容量优先淘汰 resolved 事件；活动状态单独受规则容量约束。
