# 官方接入现状与协议核验

核查日期：2026-09-10。范围：本项目的 8 个平台适配器；公开官方网页、官方 SDK、官网公开文档接口。未登录商家或开发者控制台，未使用真实店铺凭证。

## 结论

需要区分三件事：平台开放 API、平台官方 MCP、当前应用实际取得的数据权限。**现有官方 API 不等于已经存在可直接替代本项目的官方 MCP，也不等于用户的账号自动获得全部店铺数据。**

本次已从官方正文确认巨量 Marketing API、抖店商家接入、小红书商家订单 API；快手官网明确提供商家自用和第三方应用及订单能力。京东开放平台入口可访问，但本次未取得协议正文；淘宝、拼多多、微信小店的当前细则未能从官方正文完成核实。不能据此宣称这些渠道没有官方 API，也不能宣称八个平台已经全部完成当前协议联调。

本次未核实到覆盖上述八个平台商家私有订单的官方 MCP 集合。已核实的百炼 MCP 接入、京东 JoyAgent、火山 MCP 市场、腾讯 CloudBase MCP 各有明确业务范围，不能直接当作对应商城的商家订单授权入口。

## 证据等级

- **A：官方正文或官方 SDK 已实际读取**，结论仅覆盖读取内容，不代表真实凭证联调成功。
- **B：官方入口或公开前端文案已读取**，可以确认产品/通道存在，不能确认全部资格、签名和接口兼容性。
- **C：本轮正文未取得**，保留官方核验入口和下一步事项，不将历史知识或搜索不到当作现状证明。

## 八个平台

| 平台 | 官方接入现状与业务边界 | 身份、授权和 token | 官方 MCP / Agent 的核验结论 | 证据与行动 |
| --- | --- | --- | --- | --- |
| 巨量引擎 | 已确认 Marketing API 和官方 Go SDK；核心是广告投放、账户及报表，不能等同于抖店全量交易订单 | SDK 明确要求注册开发者、应用拥有对应权限组；支持授权码换 access token / refresh token；请求头使用 `Access-Token` | 商家经营范围的官方 MCP 未核实；火山云服务 MCP 不直接证明巨量广告 MCP | **A**：[官方 SDK](https://github.com/oceanengine/ad_open_sdk_go)。按广告账户授权核验，复用客户端并接入正确请求头 |
| 抖店 | 已确认自用型、工具型应用及商家数据对接；官方 API 调用指南、SDK 和签名工具均有公开文档 | 当前自用指南要求商家后台系统类目资质、系统材料、软著、关联店铺；主体相同或证明强关联。多店铺 token 由应用与店铺共同确定；工具型应用另走资质审核 | 公开文档搜索 `MCP` 返回 0 条；只表示本次未核实，不证明不存在。普通抖音内容开放能力不能替代抖店授权 | **A**：[自用指南](https://op.jinritemai.com/docs/guide-docs/140/583)、[工具型应用](https://op.jinritemai.com/docs/guide-docs/8/19)、[API 调用指南](https://op.jinritemai.com/docs/guide-docs/148/814)。选择自用或 ISV 路线，逐店授权 |
| 京东 | 京东零售开放平台、宙斯开发者中心入口可访问；本轮正文为 JavaScript 页面，未完成零售订单协议核验 | 自用/服务商申请范围、OAuth、应用权限包及店铺授权规则须在对应控制台核对；不能拿京东联盟商品推广权限代替商家订单权限 | 已确认官方 JoyAgent 是通用多智能体产品，可挂载外部 MCP；这不是京东商家订单 MCP 的证明 | **B**：[零售开放平台](https://open.jd.com/)、[宙斯](https://jos.jd.com/)；**A**：[JoyAgent](https://github.com/jd-opensource/joyagent-jdgenie)。核验零售应用的当前网关、签名和订单权限 |
| 淘宝 | 本项目面向淘宝开放平台；本次官方网站和 API 文档正文抓取失败，当前具体接口及申请范围未完成核实 | 须核对 TOP 应用类型、卖家授权 session/token、所需订单权限及数据保护要求。淘宝客选品/推广不等于卖家私有订单 | 已确认百炼可以调用外部 MCP；未取得可证明淘宝卖家私有订单范围的官方 MCP 文档，百炼通用说明不能作为该证明 | **C**：[淘宝开放平台](https://open.taobao.com/)；**A**：[百炼 MCP 说明](https://help.aliyun.com/zh/model-studio/mcp)。先取当前卖家 API 文档与已获批权限表 |
| 拼多多 | 本项目面向拼多多开放平台；本轮官方正文抓取失败 | 商家订单与多多进宝推广应分别核对；应用资质、商家授权和 token 规则需以当前控制台为准 | 商家私有订单的官方 MCP 未核实 | **C**：[拼多多开放平台](https://open.pinduoduo.com/)。确认申请的是商家经营接口，而非仅推广/联盟接口 |
| 快手 | 官网公开文案明确提供商品、订单等电商能力；区分商家自用型应用和第三方开发者在服务市场销售的应用 | 官网流程为注册认证、创建应用、开发测试、上线；详细授权/token/签名规则需要进一步取得开发者文档与应用权限 | 快手电商商家经营的官方 MCP 未核实；不能用快手内容接口代替小店订单 | **B**：[快手电商开放平台](https://open.kwaixiaodian.com/)、[开发者指引](https://open.kwaixiaodian.com/zone/new/docs/dev?pageSign=4852036ba63c13df7f5fd2ddc38169581614263613785)。独立核验签名、订单方法和分页 |
| 小红书 | 已确认订单、售后、商品、库存、物流、财务 API，以及公网统一网关、签名、自研与 ISV 授权正文；订单列表为 `order.getOrderList` | 自研应用只能授权同主体或关联主体的最多 10 个正常经营企业店铺，店铺主账号操作授权；服务商使用 OAuth code 换店铺 token，支持刷新和撤销。具体应用类目权限仍须核对已获批范围 | 商家私有订单的官方 MCP 未核实；笔记抓取、发布或内容营销工具不能作为订单权限证明 | **A**：[订单文档](https://open.xiaohongshu.com/document/api?apiNavigationId=183&id=25&gatewayId=103&gatewayVersionId=1661&apiId=27241&apiParentNavigationId=15)、[自研授权](https://open.xiaohongshu.com/document/developer/file/36)、[服务商授权](https://open.xiaohongshu.com/document/developer/file/38)。按当前方法名、签名和 schema 迁移 |
| 微信小店 | 本项目面向微信小店；本轮官方订单和 token 文档正文抓取失败，当前授权模式的全部边界未完成核实 | 必须区分本店开发者调用与第三方服务商代店铺授权；公众号/小程序/其他店铺的 token 不能未经核实混用 | 腾讯官方 CloudBase MCP 面向云开发数据库、函数、部署等；不能当作微信小店订单 MCP | **C**：[微信小店文档](https://developers.weixin.qq.com/doc/store/shop/)；**A**：[CloudBase AI Toolkit](https://github.com/TencentCloudBase/CloudBase-AI-Toolkit)。分别验收已有 token 与自动获取模式 |

## 直接影响修复的官方协议证据

### 巨量引擎

官方 SDK 使用 `Access-Token` 请求头，示例 API 网关为 `https://api.oceanengine.com`；SDK 文档明确建议复用客户端。不能沿用通用电商 MD5 参数认证来代替。来源：[官方 Go SDK](https://github.com/oceanengine/ad_open_sdk_go)。

### 抖店

当前自用指南公开显示：一个应用可以授权多个关联店铺；获取 token 必须带目标 `shop_id`，遗漏时可能返回最早授权店铺的 token。指南给出的默认 token 有效期为 7 天，支持创建/刷新，不应每次业务请求前重新获取。自用应用不能在服务市场发布服务；对外服务客户应按工具型/相应服务商类目办理。来源：[自用型应用入驻指南](https://op.jinritemai.com/docs/guide-docs/140/583)。

官方签名 FAQ 指向当前 API 调用指南、平台签名工具，并建议使用官方 SDK。旧公告已明确支持 HMAC-SHA256，但应以当前调用指南的参数封装、序列化和签名范围为准，不能仅把 MD5 算法名替换掉。来源：[签名错误 FAQ](https://op.jinritemai.com/doc/external/open/queryDocArticleDetail?articleId=3062)、[API 调用指南](https://op.jinritemai.com/docs/guide-docs/148/814)、[签名工具](https://op.jinritemai.com/docs/guide-docs/gen-sign)。

### 小红书

订单列表公开 schema 的请求字段为 `startTime`、`endTime`、`timeType`、`pageNo`、`pageSize` 等。其中 `timeType` 必填；创建时间窗口最多 24 小时，更新时间窗口最多 30 分钟且要求从末页向首页读取；页码与页大小均有限制。结果有 `orderList`、`total`、`maxPageNo`，结果中的订单时间字段使用毫秒。旧 REST 路径、snake_case 字段和一般正向分页不能直接当作此接口的合同。来源：[官方订单 schema](https://open.xiaohongshu.com/api/doc/infoNew?gatewayId=103&gatewayVersionId=1661&apiId=27241)。

官方系统参数指南确认公网请求统一发往 `https://ark.xiaohongshu.com/ark/open_api/v3/common_controller`，使用 POST JSON；公共参数与业务参数同在 body。`version` 为 `2.0`，`timestamp` 为秒；商家业务调用必须有 `accessToken`。来源：[官方系统参数指南](https://open.xiaohongshu.com/document/developer/file/40)、[公共参数 schema](https://open.xiaohongshu.com/api/doc/common/paramNew?gatewayId=103&gatewayVersionId=1661)。

签名来源为 `method + "?" + 已排序的 appId/timestamp/version 查询串 + appSecret` 的小写 MD5；授权 token 与业务字段不参与签名。不是把全部参数按旧版通用规则签名。来源：[官方签名算法](https://open.xiaohongshu.com/document/developer/file/39)。

服务商授权指南规定授权 code 有效 10 分钟，access token 默认 7 天、refresh token 14 天；刷新窗口和旧 token 重叠期也有说明。此处应使用服务端返回的过期时间管理缓存，refresh token 过期时要求商家重新授权。指南的授权请求表含一个毫秒格式旧示例，与系统参数指南及当前公共 schema 的秒单位冲突；实现采用后两者明确的秒单位。来源：[官方软件服务商授权流程](https://open.xiaohongshu.com/document/developer/file/38)。

## 官方 MCP 相关产品：已确认什么

| 官方来源 | 实际提供的能力 | 不能据此推出的结论 |
| --- | --- | --- |
| [阿里云百炼 MCP](https://help.aliyun.com/zh/model-studio/mcp)、[官方 MCP 服务说明](https://help.aliyun.com/zh/model-studio/official-and-third-party-mcp) | 大模型/工作流集成与外部调用 MCP；示例包含网页解析和高德等服务 | 所有淘宝商家订单已开放给任意 AI 客户端 |
| [京东 JoyAgent-JDGenie](https://github.com/jd-opensource/joyagent-jdgenie) | 通用多智能体产品，可自行添加 MCP Server | 京东零售订单授权被自动包含 |
| [火山引擎 MCP Server 仓库](https://github.com/volcengine/mcp-server) | 同时收录火山官方云服务与第三方生态工具 | 市场里的所有工具均为平台官方，或自动拥有抖店/巨量权限 |
| [腾讯 CloudBase AI Toolkit](https://github.com/TencentCloudBase/CloudBase-AI-Toolkit) | 云开发数据库、函数、认证、存储及部署工具 | 可读取微信小店商家私有订单 |

## 核查记录与时间

以下均于 2026-09-10 实际访问。页面未公开更新时间时不推测发布日期。

| 来源 | 本次读取结果 | 页面/数据自身时间 |
| --- | --- | --- |
| 巨量官方 Go SDK README | 完整正文，含访问条件、OAuth、请求头和示例 | 本轮未提取提交时间 |
| 抖店自用指南 `articleId=583` | 官方公开文档接口返回完整正文；当前页面路径为 `/docs/guide-docs/140/583` | 2026-09-01 07:56:07 UTC（官方 `updateTime=1788249367`） |
| 抖店工具型指南 `articleId=19` | 完整正文，明确工具型应用需类目资质审核 | 2022-06-13（官方 `updateTime=1655114036`）；旧文档，细则还应与应用控制台核对 |
| 抖店旧自用链接 `articleId=18` | 官方返回“文档不存在”，因此没有用它证明当前流程 | 不适用 |
| 抖店文档检索 `keyword=MCP` | 官方公开检索接口返回 `total=0` | 查询时结果，不构成不存在证明 |
| 小红书一级/二级 API 目录 | `api/doc/listNew`、`api/doc/second/listNew?apiNavigationId=15` 成功；官网使用的 API 排除列表当次为空 | 查询时结果 |
| 小红书订单 schema | `apiId=27241` 正文成功 | API `updateTime=2026-08-18T07:38:09.000Z`；订单详情模型包含 `2026-09-04` 更新 |
| 小红书公共参数 schema | 正文成功 | `updateTime=2025-12-08T13:35:51.000Z` |
| 小红书开发者文档 `36/38/39/40` | 官网公开搜索定位，按前端实际调用的 `POST api/developer/doc/getDocDetailNew` 读取全文；对应自研授权、服务商授权、签名、系统参数 | 官方 `updateTime` 均为 2026-01-08；签名/系统参数为 `1767842109000` 毫秒 |
| 快手官网 | HTML 和其公开前端文案成功读取，已确认自用/第三方及订单能力 | 首页脚本标记 `web_version=20250217120102`；不代表接口最后更新时间 |
| 京东开放平台、宙斯 | 入口成功，正文仅 JavaScript 提示 | 未公开可读更新时间 |
| 淘宝、拼多多、微信小店上述官方文档 | 网络超时或抓取失败；**不能把网络失败描述为必须登录** | 未核实 |
| 百炼英文 MCP 文档 | 完整正文 | [英文页](https://www.alibabacloud.com/help/en/model-studio/mcp)显示 2026-09-02 更新 |

## 对项目的建议

1. 每个平台维护“官方来源版本 → 适配方法 → 权限需求 → 已验证范围”的表。没有官方合同对应的方法应明确报不支持，不能以虚构 URL 或模拟成功维持工具数量。
2. 区分自有店铺和对外 ISV 两种产品路线。先做已经能合法取得授权的店铺；配置文件可以帮助接入，不能代替平台资质审核。
3. 将多店铺 token 保管、刷新与撤销、店铺路由和隔离放在确定性代码层；MCP 仅开放必要的只读工具。
4. 日报由代码完成时间窗口切分、完整分页、去重、金额/退款口径和可核对汇总。广告账户数据与交易订单分别标明来源及口径。
5. 验收分开记录协议样例测试、安装后 MCP 调用测试、真实只读店铺联调。只有前两类通过，不能写成“八平台全部线上可用”。

本项目可持续的价值在于跨平台、跨店铺的可靠授权管理和一致数据处理。即使某个平台提供官方 MCP，这些跨平台工作仍需逐项核验并实现；是否替换单个平台适配器，应比较具体方法、数据权限、授权生命周期和稳定性。
