# 拼多多授权与只读业务合同核验

核验日期：2026-09-10。授权与公共运输有官方正文证据；业务字段正文受限。
本文和 HTTPX 测试均不代表商家账号或生产 API 验收通过。

## 本轮规格与计划

1. 用当前官网公开的授权、调用、SDK、订单及售后接入正文核对旧实现。
2. 先写失败测试，再修复请求时间戳、拒绝协议字段覆盖，以及 SDK/CLI 的不完整合同边界。
3. Pro 新增独立 `PinduoduoProvider`：继承现有显式应用配置和 HTTP 注入协议，支持 merchant code exchange/refresh，拒绝 self-use；核验 owner、期限、scope 与错误信封。
4. HTTPX 边界测试通过后跑完整回归和代码质量检查。没有店铺授权不发生产业务请求。

## 官方来源及重现

官网入口 [API 文档](https://open.yangkeduo.com/application/document/api) 的当前
`main.f41932a3.js` / `14.fa5a0d37.js` / `documentApi.978c0130.chunk.js`
给出了 `https://open-api.yangkeduo.com` 与文档请求路径，均为公开网页使用的资源。
本地完整缓存：`/private/tmp/pinduoduo-contract-evidence-20260910`，包含原始 JSON、正文提取文本和前端资源。

| 正文 | 官方页面 | 公开查询参数 |
| --- | --- | --- |
| 授权说明 | [授权说明](https://open.pinduoduo.com/application/document/browse?idStr=BD3A776A4D41D5F5) | `POST /doc/article/getArticle {"idStr":"BD3A776A4D41D5F5"}` |
| API 调用指南 | [调用指南](https://open.pinduoduo.com/application/document/browse?idStr=8EC06C399636041E) | `idStr=8EC06C399636041E` |
| SDK 使用指南 | [SDK](https://open.pinduoduo.com/application/document/browse?idStr=7E28519022C8E799) | `idStr=7E28519022C8E799` |
| 订单接入 | [接入方案](https://open.pinduoduo.com/application/document/browse?idStr=ACD8CDA5CA04B827) | `idStr=ACD8CDA5CA04B827` |
| 售后接入 | [售后说明](https://open.pinduoduo.com/application/document/browse?idStr=D6BA70A443D1C94F) | `idStr=D6BA70A443D1C94F` |

以上正文与 `POST /pop/doc/info/list/byCat {"id":1|2|18|20}` 均返回 HTTP 200、`success:true`。
相同域名 `POST /pop/doc/info/get {"id":"<API名>"}` 查询订单列表、订单详情、售后列表、售后详情、token create、token refresh 时均返回
HTTP 403、`{"success":false,"errorCode":4000000,"errorMsg":"System Error","result":null}`。
该错误不证明 API 不存在，也不证明某个账号具体缺少哪种权限。当前前端存在 `apiDocLoginRequired` 开关；需开发者登录后的正文或官方应用生成 SDK 源码才能继续核验。
官方 SDK 指南明确目前只提供 Java SDK，下载须注册、创建应用、在应用开发者工具中生成，且只能调用应用拥有的权限包。

## 授权与运输（已有正文）

- Merchant Web 授权页为 `https://fuwu.pinduoduo.com/service-market/auth`，参数为 `response_type=code`、`client_id`、URL 编码的 `redirect_uri`、回传 `state`；不是多多进宝推手授权。
- 仅店铺主账号可授权，店铺已完成开店且未申请退店。code 有效 10 分钟；重复授权使旧 code/access_token/refresh_token 立即失效。
- `pdd.pop.auth.token.create` 使用 code；`pdd.pop.auth.token.refresh` 使用 refresh_token。统一 POST 到 `https://gw-api.pinduoduo.com/api/router`，没有测试网关声明；官方 tester 仅正式环境。
- 公共 `timestamp` 是 Unix **秒**字符串。所有公共及业务参数按 ASCII 键顺序无缝拼接，前后加 client_secret，MD5 十六进制大写作为 sign。请求支持 JSON；已有 CORE form 运输按官方 URL 编码要求保留。
- 授权响应分别在 `pop_auth_token_create_response`、`pop_auth_token_refresh_response`。`owner_id` 绑定授权主体，不能用 owner_name 替代；`scope` 为 API 名字符串数组。
- `expires_in`、`refresh_token_expires_in` 是剩余秒数；`expires_at`、`refresh_token_expires_at` 为 Unix 秒。实现取绝对期限和相对期限的较早者，刷新不得延长原授权期限。
- 权限细分期限使用 `r1/r2/w1/w2_expires_at`，Unix 秒；官方示例 `w1_expires_in` 误用绝对值，因此不以该字段推算期限。无法核实的响应不按默认成功处理。
- 错误信封为 `error_response`（官网 API 页展示 `error_code/error_msg/sub_code/sub_msg/request_id`）。没有细分错误码正文时不猜 token 失效/重试分类，保留固定安全失败原因。

## 业务操作（部分证据，暂不可用）

| SDK operation | 官方名称 | 已证实范围 |
| --- | --- | --- |
| get_order_list | pdd.order.list.get | 按成交时间；单次最多 24 小时；初始化近 90 天；SDK 示例 StartConfirmAt/EndConfirmAt/OrderStatus/RefundStatus/Page/PageSize |
| get_increment_orders | pdd.order.number.list.increment.get | 按更新时间；最多 30 分钟；近三个月创建的订单；官方建议从后向前翻页 |
| get_order_detail | pdd.order.information.get | 按订单号；近三个月创建的订单 |
| get_refund_list | pdd.refund.list.increment.get | 按更新时间；最多 30 分钟；原代码的 pdd.refund.list.get 无目录证据 |
| get_refund_detail | pdd.refund.information.get | 接入指南说明需要售后单号和订单号，旧工具只有 refund_id 不足以确认 |
| get_shop_info | pdd.mall.info.get | 店铺目录确认名称，但未获得请求/响应字段 |

全部上述 SDK operation 为 `contract_status="partial"`、`supported=False`、`live_verified=False`。
CLI 保留工具名及输入形状以维持发现/握手兼容，但在发请求前通过 MCP `ToolError` 明确报合同未核实，删除已知错误的旧日期字段和退款列表路径组装。
通用客户端运输供已有其他工具使用，不把它的 HTTP mock 成功升级成业务支持。

尚缺：各字段类型/必填、订单与售后状态枚举、起始页码和 page_size 上限、总数/has_more 精确字段、响应 list/detail 路径、订单实付与补贴/商家收入的金额单位、售后申请金额和实际完成退款的差别及到账时间。
官方增量目录关于系统时间前 3 分钟的措辞与分页稳定性，须结合完整 API 文档再落实；本轮不据此猜实现。

## 实际验收记录

先得到授权 27 个失败用例、CORE 22 个失败用例，再实现。新增最终授权用例 32 个、CORE 23 个；保留旧工具的错误/分页/响应场景，改为验证未核实业务的显式拒绝与零运输调用。

- CORE Python 3.12、3.14 完整回归分别 **1763 passed + 20 subtests**。
- Pro 授权 provider、registry、授权服务与 token manager focused：**192 passed**。
- CORE Ruff、Black、mypy（72 source files）、Pylint（10.00/10）、Bandit 按仓库配置通过；Pro 本轮文件 Ruff、Black、mypy（2 个授权 source files）通过。
- 真实子进程 MCP stdio 三个场景通过：初始化/18 工具发现/公共工具成功和失败、缺凭证、业务不可用原因透传。没有发出商家业务请求。
- 日志：`/private/tmp/pdd-core-py{312,314}-final-20260910.log`、`/private/tmp/pdd-pro-auth-focused-20260910.log`、`/private/tmp/pdd-mcp-smoke-final-20260910.log`。
- Pro 全量曾运行，得到 618 passed/16 failed；16 个失败均属同时开发中的 warehouse 新接口（page_key/get_job_progress/IncompleteWindowError），已通知其 owner。此结果不算 Pro 全量通过，统一全量验收由集成任务在并行工作完成后执行。

外部待办：创建/审核应用、对应订单/售后/店铺权限包、允许授权名单、真实店铺主账号授权，以及取得受限 API 正文或生成的 Java SDK；然后才能跑真实首次查询、全分页和金额对账。本轮没有安装/启动 Docker，也没有声明新的打包或 Docker 验收通过。
