# 有赞显式只读SDK合同

核查2026-09-10。SDD范围：新增无环境读取、单授权快照、有HTTP/限流注入的YouzanClient，
接入已有create_platform_client与operation_catalog，只增加5条已核实读取路由。
先建立两店铺并发与官方形状RED，后实现请求/响应验证。授权/刷新/商家身份由Pro负责。
本轮不新增CLI、写接口、normalizer或collector；全部live_verified=false。

## 官方来源

目录来自https://doc.youzanyun.com/llms.txt及其trade/store索引，原始完整markdown保存在
`/private/tmp/taobao-youzan-contract-evidence-20260910/youzan-*.md`。

| operation | 官方正文 | HTTP path |
|---|---|---|
| get_order_list | https://doc.youzanyun.com/v2/doc/cloud/token/P5Ojw8J96iVoyHkw4C5c0iRLnHd.md | /api/youzan.trades.sold.get/4.0.4 |
| get_order_detail | https://doc.youzanyun.com/v2/doc/cloud/token/N1PewEBlii4MlBk4mw5cwezYnke.md | /api/youzan.trade.get/4.0.2 |
| get_refund_list | https://doc.youzanyun.com/detail/API/0/3694.md | /api/youzan.trade.refund.search/3.0.1 |
| get_refund_detail | https://doc.youzanyun.com/detail/API/0/4069.md | /api/youzan.trade.refund.get/3.0.1 |
| get_shop_info | https://doc.youzanyun.com/v2/doc/cloud/token/NAYrwNQqNiwFtVkXG8Xcc115nLc.md | /api/youzan.shop.get/3.0.0 |

官方示例为POST https://open.youzanyun.com，业务JSON放body，access_token放query，无额外签名。
网关要求success=true及code=200；部分退款schema把code列为string，兼容字符串"200"。
SDK保留完整success/code/data信封，不用失败data构造空列表。凭证要求显式access_token；
可保留app_key/app_secret供宿主一致配置，但业务请求不发送它们、不自行刷新token。

## 分页和原生形状

- 订单页号page_no为1..100，page_size为1..100（默认20）；创建/更新/完成/支付窗口分别是
  start_created/end_created、start_update/end_update、start_success/end_success、start_pay/end_pay。
  日期字符串必须成对，结束晚于开始，官方最大3个月。日期保留官方字符串，不误作秒或毫秒。
  同时给多种窗口会改变排序优先级（完成时间优先），采集器应显式选择一个业务窗口。
- 订单列表data.full_order_info_list[]的每个元素含full_order_info，后者含order_info/pay_info/orders；
  data.total_results是总数，没有has_next。详情data.full_order_info结构相同，入参tid。
  列表/详情有索引延迟，官方建议收到消息30秒后读取。2020年前数据需旧4.0.0，当前目录未接入。
- 售后列表page_no<=100，page_no*page_size<=3000，超过要切时间段；请求create_time_start/end、
  update_time_start/end为Unix秒整数。无时间默认近3个月创建；返回data.refunds[]与data.total。
  售后详情入参refund_id，可选query_option；返回data就是售后单。
- get_shop_info不需要业务参数，data.id是kdt_id。订单node_kdt_id是门店/网店，root_kdt_id是总部；
  单店时二者为该店。不能把总部权限和某个子店的日报范围混为一谈。
- 官方没有跨页强一致快照保证。达到页数/深度上限、时间窗/总数变化或无法补齐时，采集必须
  明示不完整；不能因为返回200而声明全量验收。

## 业务金额/时间提示

订单详情full_order_info.pay_info.real_payment是整单实付（元字符串），payment明确为应付。
列表只有payment且描述为最终支付价格，不能假定与详情real_payment同义；实付统计应补详情。
order_info.pay_time/update_time分别为支付/修改日期字符串。多阶段阶段款及现金/标记支付的
指标归属仍需商家账务样本确定，不能凭接口Mock得出资金结算结论。

售后列表refund_fee是申请金额（元字符串）。详情refund_fee为含邮费的退款金额（元），
refund_fund_list[].refund_fee为分，status=2才是资金成功（0处理中、1失败）。
refund_account_time是到账时间；refund_success_time是售后成功时间。资金日报不能拿created、
modified或售后成功时间补缺到账时间；分期/多通道退款还需核对各资金流水。

## 应用权限与验收

5个API均计费。订单/售后/店铺的能力包和店铺类型在各官方正文末尾列出；商家应用仍须取得
对应包、订阅授权及适用店铺类型。shop.get的“单店信息同步/连锁店铺信息同步”包包含AI效率工具、
三方连接器等应用类目，不代表当前应用已授予权限。Pro OAuth已核实authority_id为kdt_id，
首读可以用get_shop_info {}核对实际data.id；用户端预期ID不能代替这个平台返回值。

待实际应用token、测试店铺权限及订单售后样本完成：首次读取、双页对账、字段缺失、权限失效、
额度、支付/到账金额核对。本轮仅合同读取与本地可执行验证，未调用商家API。

## 验证记录

2026-09-10有赞SDK先22例RED，再全部GREEN，覆盖5条官方形状路由、两授权并发隔离、
凭证快照、外部HTTP资源所有权、限流注入、未知/写操作拒绝、分页/时间边界与错误响应。
SDK当前有9个平台、44条可调用只读映射（有赞5条），CLI保持原8个平台。
TOP/有赞/旧SDK相关focused套件224例通过；完整测试两Python版本各1744+20subtests，
构建、质量检查、安装后24个真实MCP场景及十条SDK请求结果见[TOP验证记录](taobao-contract.md#验证记录)。
包内SDK调用使用固定响应，商家API未调用。3个月窗口在本SDK按日历月计算；官方月边界、
空数组序列化和并发变化下的完整性仍需实际样本核对。
