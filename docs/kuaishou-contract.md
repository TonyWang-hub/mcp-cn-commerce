# 快手小店五个只读合同实现

规格日期 2026-09-10。当前官方正文、SDK 1.0.7698 与57个结构证据已核实，来源见
[其余平台合同](remaining-platform-contracts.md)及 `/private/tmp/remaining-platform-evidence-20260910/ks-schema-findings.md`。
本轮接续实现SDK/CLI的订单列表/详情、售后列表/详情、店铺信息；不扩展Pro授权、采集或归一化。

先用HTTPX写失败回归，再实现：五个GET正式路径、appkey/method/version=1/timestamp毫秒、JSON字符串param、
URL query编码、signSecret后缀及MD5小写（官方SDK默认）；HMAC_SHA256使用Base64并保留算法测试。
底层只读调用复用重试/限流/连接池；每次尝试重签。参数白名单禁止系统字段覆盖；售后type仅在JSON业务param内可用。
严格验证result=1和data/list/cursor，不能把HTTP200的业务错误或缺失cursor当空成功。

CLI保留旧工具名，订单页码>1必须提供真实cursor；售后页码与pcursor一起传。
时间字符串支持明确时区的ISO8601，兼容无时区日期按Asia/Shanghai解释后转毫秒；明确这是CLI配置规则。
旧订单状态参数所列状态不正确，新文档采用官方输入orderViewStatus枚举，与输出status分开；
ID改为官方正int64，旧示例KS/RF前缀字符串明确拒绝。

完整业务覆盖和资金日覆盖依然不同：店铺信息没有shopID；OAuth open_id、订单sellerOpenId、售后sellerId命名空间不能混用。
Pro授权主体映射未闭合，暂不添加provider；没有正式或测试店凭据就不声称live验证。


## 已实现的请求与响应

| SDK operation | 方法与请求必填 | 列表/详情位置 |
| --- | --- | --- |
| get_order_list | open.order.cursor.list；orderViewStatus、pageSize<=50、beginTime/endTime毫秒<=7天、cursor字符串 | data.orderList[].orderBaseInfo、data.cursor |
| get_order_detail | open.order.detail；oid正int64 | data.orderBaseInfo.oid、orderItemInfo等 |
| get_refund_list | open.seller.order.refund.pcursor.list；type8/9、currentPage正int64、pageSize<=100、beginTime/endTime毫秒<=1天、pcursor | data.refundOrderInfoList、data.pcursor、data.totalSize |
| get_refund_detail | open.seller.order.refund.detail；refundId正int64 | data.refundId/oid/status/handlingWay/refundFee/endTime |
| get_shop_info | open.shop.info.get；空业务对象 | data.shopName/shopType（没有shopID） |

每个 method 点号替换为斜杠，GET `https://openapi.kwaixiaodian.com/<path>`，完整公共参数放URL query。
订单cursor、售后pcursor首轮显式空串，之后原样传上次响应，nomore结束；页码不能生成游标。
订单无total，售后currentPage/pageSize/totalPage官方只保证第一次值有效；不能仅用totalPage替代pcursor。
当前SDK要求列表必须含非空的返回游标（含nomore）与数组；result明确1才继续，缺字段不当空成功。
本轮未实现平台保留期/活动窗口的自动缩分，调用者仍须遵守近90天及活动期间缩窗要求。

SDK仅针对快手在业务JSON里放行type，与TOP/有赞相同只是一项业务过滤器，不改变已选方法。
其他协议字段仍不允许覆盖，嵌套option只允许Boolean needExchange；Pro Commerce在引入快手授权时还需同步这项例外，当前Pro不宣称快手授权可用。

## 资金与授权的未完成项

订单totalFee官方描述是“子订单商品总价”，不是已经核实的买家实付；payTime示例是毫秒时间戳，但字段正文没有统一声明金额单位和该时间单位。
售后refundFee官方描述是商家实退金额，包含现金/消费金/宠爱红包/平台补贴、不含主播红包；不能把它直接解释成银行现金。
endTime是退款成功或失败的结束时间，须结合status=60成功且handlingWay为1退货退款/10仅退款；handlingWay=3为换货。
本轮保存完整字段原文，不进行金额/日期归一化，尤其未从示例890猜成8.90元。
实际确认金额单位、平台支付口径、卖家与授权用户ID关系，以及测试用户/商家权限仍需后续官方资料或授权联调。
旧商品/物流/评价/营销CLI的业务方法仍未完成本轮合同核验，不因底层类可导入就计入可用范围。

## 实际验证

五SDK方法、独立双授权与签名、游标/参数/错误合同首次26失败，实现后26通过；CLI实际签名调用链首次5失败，实现后合计31通过。
保持全部live_verified=false；所有HTTP均由MockTransport或AsyncMock截获，没有真实商家调用。

最终相关CLI/SDK/协议/集成focused **448 passed**；同一协作目录完整Core **2038 passed、20 subtests passed**（2026-09-10，包含另一工作项当时的JD归一化变更）。
本轮源码Black/Ruff/mypy通过，4个KS/SDK模块Pylint10.00。日志 `/private/tmp/ks-native-final-focused-20260910.log` 与 `/private/tmp/ks-native-final-20260910.log`。
独立提交仅包含本轮KS/SDK及相关测试文档，不包含其他所有者的JD归一化文件；最终发布以集成任务的冻结快照验收为准。
