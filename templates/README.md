# 电商工作流模板

开箱即用的 AI 工作流模板，配合 [mcp-cn-commerce](https://github.com/TonyWang-hub/mcp-cn-commerce) MCP Server 使用。

## 模板列表

| 模板 | 用途 | 适用角色 | 数据源 |
|------|------|----------|--------|
| [daily-report](daily-report/) | 每日经营日报 | 运营/老板 | 全平台订单 |
| [bad-review-alert](bad-review-alert/) | 差评预警 | 客服/品控 | 全平台评价 |
| [cs-classify](cs-classify/) | 客服退款分类 | 客服主管 | 全平台退款 |
| [product-select](product-select/) | 选品分析 | 选品经理 | 全平台商品 |
| [kol-match](kol-match/) | 达人匹配 | 投放优化师 | 巨量星图 |

## 使用方式

### 方式一：直接使用示例数据

1. 打开模板的 `prompt.md`
2. 将 `{{EXAMPLE_DATA}}` 替换为 `example-data.json` 的内容
3. 发送给 AI Agent（Claude / Kimi / 通义）

### 方式二：接入真实数据

1. 安装 mcp-cn-commerce：`pip install mcp-cn-commerce`
2. 配置平台 API 凭证（见 [接入文档](../docs/template-guide.md)）
3. 用 MCP Server 返回的真实数据替换 `example-data.json`

## 模板结构

每个模板包含：
- `prompt.md` — Agent 角色定义 + 任务说明 + 输出格式
- `example-data.json` — 逼真的中文示例数据（格式对齐 mcp-cn-commerce）
- `output-template.md` — 输出报告模板（可选）

## 定价

| 包 | 包含模板 | 价格 |
|----|----------|------|
| 电商日报包 | daily-report | ¥99 |
| 客服售后包 | bad-review-alert + cs-classify | ¥99 |
| 选品竞品包 | product-select | ¥99 |
| 达人投放包 | kol-match | ¥149 |
| 全平台全套 | 以上全部 | ¥299 |

## License

MIT
