# 工作流模板接入指南

模板由确定的数据处理代码供数，模型负责说明和建议。业务求和、日期归属、去重与完整性不能交给提示词猜测。

## 1. 安装并启动一个平台

```bash
python -m pip install mcp-cn-commerce
```

每个 stdio MCP 连接启动一个平台，例如 mcp-cn-commerce start doudian 或 mcp-cn-doudian。多平台请在客户端配置多个连接；docker compose up 不是一个聚合 MCP 连接。

凭证通过 shell 环境、MCP 客户端 env 或 CLI 配置传入。项目不会自动加载 .env；仅创建该文件不会改变 Python 进程的环境。变量名以 [.env.example](../.env.example) 为准，拼多多使用 PINDUODUO_*，微信使用 WX_*。

客户端配置示例（配置文件位置由客户端决定）：

```json
{
  "mcpServers": {
    "doudian": {
      "command": "mcp-cn-doudian",
      "env": {
        "DOUDIAN_APP_KEY": "your-app-key",
        "DOUDIAN_APP_SECRET": "your-app-secret",
        "DOUDIAN_ACCESS_TOKEN": "your-authorized-token"
      }
    }
  }
}
```

## 2. 准备数据与完整性声明

调用所选平台的订单、退款工具，按该平台官方时间/分页契约提取列表。平台返回通常还有包装字段，不能把整个 API envelope 当作统一订单。

对今天和昨天分别完成全部分页，记录每个来源是否成功。coverage[date].orders/refunds=true 是调用者对已完成查询的声明，系统不会根据“列表看起来很长”推断取完。平台失败、缺权限、漏页或数据截止时间不足时应传 false 或不设置。

每家店输入：

```json
{
  "platform": "doudian",
  "shop_id": "demo-shop",
  "shop_name": "示例店铺",
  "input_format": "normalized",
  "orders": [],
  "refunds": [],
  "coverage": {
    "2026-09-10": {"orders": false, "refunds": false},
    "2026-09-09": {"orders": false, "refunds": false}
  },
  "errors": []
}
```

空列表加 false 表示没有足够数据，不能作为销售为零的证据。只有已经完成查询且确实为空，才能声明完整。

input_format="raw" 可输入当前 normalizer 支持的原平台记录；该转换不证明平台响应 schema 已通过真实账号验证。字段单位不确定时必须按官方说明设置该店铺的 amount_units，否则金额保持 null。具体格式见 [data-contracts.md](data-contracts.md)。

## 3. 调用确定性日报工具

每个平台注册同一个公共工具：

```text
build_daily_report(
  shops_json="上述店铺对象构成的 JSON 数组",
  report_date="2026-09-10",
  timezone="Asia/Shanghai"
)
```

也可以直接使用 Python API：

```python
from shared.aggregation import build_daily_report

report = build_daily_report("2026-09-10", shops, timezone="Asia/Shanghai")
```

该操作只处理提供的数据，不自动请求商家 API。跨店去重按平台/店铺隔离；每店订单按订单号去重。冲突记录和未知字段产生质量错误。

输出包含 shops[].summary/yesterday/top_products、total_summary、complete、metric_definitions 和各店错误。完整性不足的正式指标为 null，已获取的部分数据单独放 observed_summary。金额以整数分计，平均值使用 Decimal；无数据时的比率是 null。

口径必须与后台核对：订单量按付款日，GMV 为实际支付金额的合计；当日退款包含可能来自以前订单的退款。具体退款率定义写在返回数据里，不能换成另一种口径后仍直接比较。

## 4. 生成文字日报

将 build_daily_report 的完整返回填入 [daily-report/prompt.md](../templates/daily-report/prompt.md)。模型必须遵守：

- 不把 null 转成零，不把 observed_summary 冒充完整店铺数据。
- 明确日期、时区、统计口径、覆盖范围和错误。
- 用已计算的 total_summary，不重新猜测跨店汇总。
- 商品级支付 GMV、新老客和库存没有证据时保留未知。

原有 example-data.json 只是展示用汇总样例，不是实时平台响应。没有凭证时可以体验模板，但不能称为真实经营数据。
