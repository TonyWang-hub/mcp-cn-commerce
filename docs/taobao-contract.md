# TOP订单及售后合同

核查2026-09-10。SDD范围：在既有5个只读operation与MCP工具中补必填fields、分页/日期验证、
响应信封验证；先以官方形状建立RED再实现，保持TOP MD5/HTTPS/session协议。
本合同迁移阶段未自动切换CRM应用的simple接口或改变采集器；后续已有共享归一化及Pro采集。所有live_verified仍false。

## 官方来源与调用合同

| 操作 | 官方正文 | 请求/返回 |
|---|---|---|
| get_order_list | https://developer.alibaba.com/docs/api.htm?apiId=46 | taobao.trades.sold.get；fields必填；start_created/end_created；trades_sold_get_response.trades.trade[] |
| get_order_detail | https://developer.alibaba.com/docs/api.htm?apiId=54 | taobao.trade.fullinfo.get；fields、tid必填；trade_fullinfo_get_response.trade |
| get_increment_orders | https://developer.alibaba.com/docs/api.htm?apiId=128 | taobao.trades.sold.increment.get；fields、start_modified/end_modified必填；trades_sold_increment_get_response.trades.trade[] |
| get_refund_list | https://developer.alibaba.com/docs/api.htm?apiId=52 | taobao.refunds.receive.get；fields必填；start_modified/end_modified；refunds_receive_get_response.refunds.refund[] |
| get_refund_detail | https://developer.alibaba.com/docs/api.htm?apiId=53 | taobao.refund.get；fields、refund_id必填；refund_get_response.refund |

完整官方HTML/可读文本缓存`/private/tmp/taobao-youzan-contract-evidence-20260910/taobao-*`。
SDK保留整个TOP信封；MCP默认只请求业务ID、金额、状态和时间等非收件人字段。

列表page_no从1开始，page_size最大100。默认total_results计数分页；use_has_next=true时
不返回total_results，须以has_next判断终止。不能将缺少total解释成0。
创建列表仅3个月内数据，创建时间倒序；增量列表仅3个月内交易，单次修改窗口必须大于0且
不超过1天，官方建议30分钟内。增量按modified倒序，官方要求从最后页向第一页翻取防漏。
API本身不提供稳定快照，变化中的结果不能凭单页或最终total声称完全一致。

时间是GMT+8的`yyyy-MM-dd HH:mm:ss`字符串。退款列表正文未明确给出历史跨度或强一致性
保证，不能把订单的3个月上限当成其官方限制。默认交易type并非所有类型，国际/特殊/服务
订单需要应用明确选择对应type，保留SDK原生type字段供采集器配置。

## 金额与权限边界

[官方金额说明](https://developer.alibaba.com/docs/doc.htm?articleId=108471&docType=1&treeId=780)
更新2025-10-15：trade.payment一般为主单付款金额，元字符串；子单divide_order_fee为
分摊主单优惠后的金额；received_payment是商家已收到打款。官方同时说明退款会影响payment，
因此最新payment不一定保留原始支付快照，不能无条件再减退款计算历史净额。
platform_subsidy_fee是部分天猫购物券的平台出资，与买家实付不同。

订单tid是父单号，orders.order[].oid为子单。pay_time、modified、end_time分别是付款、
修改、结束时间。订单TRADE_CLOSED可能是付款后退款，不等于未付款取消。
退款refund_fee为退还买家的元字符串，status=SUCCESS才是退款成功；end_time是退款完结
时间，不用modified替代。是否等同支付渠道最终到账仍需资金业务证据，不能推断。

[CRM类应用处理方案](https://developer.alibaba.com/docs/doc.htm?articleId=120254&docType=1)
明确部分CRM应用回收上述full订单权限，替代为simple接口。本目录的documented表示读过
合同，不表示所有应用拥有权限。须按实际应用类目、交易权限包、卖家授权和字段权限验收；
卖家account ID来自OAuth taobao_user_id，不是数字店铺ID。此轮不声称已核实CRM替代合同。

## 验证记录

2026-09-10先跑合同RED（15失败、1通过），再补实现；另以2个RED覆盖TOP/有赞的合法type
业务筛选与PDD协议type的差异。最终TOP合同18例通过，连同有赞/SDK/TOP旧回归/协议兼容
的focused套件224例通过。旧测试的RF前缀伪造退款号、多余taobao_信封前缀及超1天增量
窗口已替换为官方形状，未把这些Mock响应标为真实商家验证。

同一协作工作区（包含并行DD归一化修复）Python3.12.3和3.14.6完整套件各1744 passed，
20 subtests passed。全仓Black/Ruff/mypy71源文件/全仓Pylint 10.00通过。
Bandit按CI的`-c pyproject.toml -r servers/ shared/`通过，使用既有平台MD5协议例外；
无配置扫描会报告这个既有TOP MD5签名，不为消除扫描提示更改官方协议。

wheel、sdist构建及twine check通过；wheel安装到独立Python3.12环境后，在非源码目录
完成全部24个真实MCP stdio场景和5条TOP、5条有赞安装后SDK请求。后者使用HTTPX固定响应，
没有导入MCP server模块或发出真实商家请求。元数据仍为8个平台CLI、155工具；
有赞是第9个SDK平台，无新增CLI。所有live_verified=false。

日志`/private/tmp/taobao-youzan-*.log`及`/private/tmp/mcp-taobao-youzan-*.log`；
构建物`/private/tmp/mcp-taobao-youzan-dist-20260910/`。没有启动本机容器。

## 当前真店验收状态（2026-09-11）

[TOP匿名验收记录](live-acceptance/taobao.md)已建立，真实调用未执行。先确认目标应用实际拥有本页五个方法与字段权限、卖家taobao_user_id、正式网关及已登记回调；仅有simple或沙箱资格时另取完整合同，不静默替换方法/环境。至少两页、父子单、跨日/部分退款和payment受售后影响的样本仍待提供；刷新/撤销按真实窗口分别验收。工程与发布状态见[候选记录](release-readiness.md)。
