# 微信小店自研采集合同与实施记录

**目标：** 将当前官方订单、售后接口接入受控采集，保留真实分页证据；尚未使用商家凭据进行 live 验收。
**架构：** Pro 的自研 provider 负责稳定 token 与店铺原始 ID 绑定，SDK 固定使用该授权快照。Source 逐页拉取 ID 并补全详情；Warehouse 原子保存数据、加密游标和页证明。已有 counted 分页继续验证官方 total。
**技术：** Python、HTTPX、SQLite、现有加密 CredentialStore、pytest。

## 官方证据（2026-09-10）

原文保存在 `/private/tmp/remaining-platform-evidence-20260910/wx-*.html` 与同名 `.txt`。

- [开发者指南](https://developers.weixin.qq.com/doc/store/shop/dev_before/guide.html)：自研使用小店后台“服务市场→经营工具→自研”的 AppID/AppSecret；ISV 使用 authorizer_access_token。
- [稳定 token](https://developers.weixin.qq.com/doc/store/shop/API/apimgnt/common/api_getstableaccesstoken.html)：POST JSON client_credential/appid/secret/force_refresh=false；expires_in 秒，无 refresh_token。不得用 component_access_token 访问商家订单。
- [店铺](https://developers.weixin.qq.com/doc/store/shop/API/storemanage/api_mmecapi_basicinfo.html)：GET `/channels/ec/basics/info/get`；`info.username` 是店铺原始 ID，不是 AppID，不假设数字或 gh_ 前缀。详情没有统一店铺字段，Source 每页先核同一授权快照的店铺身份。
- [订单列表](https://developers.weixin.qq.com/doc/store/shop/API/channels-shop-order/api_getorderlist.html)：POST，create_time_range 或 update_time_range 的 start_time/end_time 为秒、跨度最多7天，page_size<=100；order_id_list、has_more、next_key；没有 total。
- [订单详情](https://developers.weixin.qq.com/doc/store/shop/API/channels-shop-order/api_getorder.html)：POST order_id 字符串，响应 order；order_id、create_time/update_time 秒。`order_detail.price_info.order_price` 用户实付分；original_order_price 原始订单价分（含运费），product_price 仅商品总价，freight 分，merchant_receieve_price 为商家实收分。`order_detail.pay_info.pay_time` 秒；payment_method=1 微信支付，2 先用后付的确认时间、3 抽奖零元与4积分兑换的下单时间不证明付款。`order_present_info.is_b2c_free_present=true` 没有实际支付。普通支付之外付款金额/日期保持未知，不凭待发货状态推断付款。商品 product_infos[].product_id/sku_id/count/sale_price，sale_price 分。
- [售后列表](https://developers.weixin.qq.com/doc/store/shop/API/channels-shop-aftersale/aftersale/api_getaftersalelist.html)：POST begin/end_create_time 或 begin/end_update_time 成对，最多24小时；时间为秒，next_key 第二页起传。无 page/page_size/total；after_sale_order_id_list、has_more、next_key。
- [售后详情](https://developers.weixin.qq.com/doc/store/shop/API/channels-shop-aftersale/aftersale/api_getaftersaleorder.html)：响应 after_sale_order；ID、order_id、create_time/update_time；complete_time 明确售后完结秒级时间。仅 REFUND+MERCHANT_REFUND_SUCCESS 或 RETURN+MERCHANT_RETURN_SUCCESS 表示对应退款完成，金额 refund_info.amount 分。处理中/失败/换货均不计完成退款；complete_time 缺失不能回退 update_time。平台优惠退回、赔付、保险字段不额外相加。
- [官方测试服务](https://developers.weixin.qq.com/doc/oplatform/partner/service_market/provider_guideline/enter_guideline/sph_enter_guideline)：ISV 上架可设测试服务，配置测试人员后在服务市场小程序调试；仍需先开微信小店购买，套餐需7天免费版本。不是匿名沙箱/公众号测试号。

金额仅表示官方字段的实付或已完成退款，不代表银行结算。列表没有版本与 total；详情只能核 ID 与窗口，不能声称列表/详情共享版本或平台快照。订单、退款完整支付事件覆盖仍需回补/对账。历史查询保留期、窗口端点开闭、下一页 token 长度上限没有明确公开保证；本地采用重叠更新窗口和明确预算。

## 实施步骤

- [x] Core `tests/test_weixin_normalizer_contract.py` 验证普通支付、非支付方式、赠礼、退款成功/失败/换货、金额分单位、秒时间、缺失字段；`shared/normalizer.py` 增加微信原生分支。旧输入形状只保留原有显式兼容，原生数据不回退猜测金额/日期。
- [x] Pro `tests/test_weixin_store_collection.py` 验证按平台/操作/路径投影店铺 ID，未知 username 仍被移除；原生订单/退款字段保留；跨店/缺失 ID/错误信封/错误时间/缺详情拒绝。实现 `pro/sources/weixin_store.py` 与 `pro/privacy.py`，Commerce 传入 platform 上下文；凭证脱敏若改变原生 ID 列表成员，整页拒绝，不能将损坏列表当作空页或较短页面。
- [x] `SourcePage` 增加 cursor 模式、next_cursor 与 terminal 标志；total=None。`CollectionRunner` 按模式提交，counted 保持现有 total 校验。Warehouse 游标模式验证单调页次、固定大小、非重复 token/ID、明确终页，原子写入加密下一页 token 与 observed_count。页证明对外分别显示 pagination_mode、official_total、terminal_evidence；观察唯一数量继续 unique_record_count。
- [x] 新 `tests/test_weixin_source_runtime.py` 跑真实 Commerce→SDK→HTTPX MockTransport→加密 Warehouse，验证两类采集、重启续传、不完整页、循环游标、跨页重复、同版本冲突、counted 回归与公共运行时输出。不改 ScheduleWorker 或其测试。
- [x] 已有 venv 中 Core 相关测试 120 项、Pro 相关测试 265 项通过；本轮 Python 文件 Black/Ruff、生产文件 mypy/Pylint 通过。新增 12 项列表脱敏回归先复现失败，再验证修复；覆盖订单/售后、单个与混合 ID、访问凭证与应用密钥子串、终页与非终页。
- [ ] 全量回归、CI 与发布验收由总任务汇总。实际凭据/IP 白名单、官方权限及真人订单握手仍为外部 live gate。
