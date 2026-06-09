# 工作流模板接入指南

## 快速开始

### 1. 安装 mcp-cn-commerce

```bash
pip install mcp-cn-commerce
```

### 2. 配置 API 凭证

在项目根目录创建 `.env` 文件：

```env
# 抖店
DOUDIAN_APP_KEY=your_app_key
DOUDIAN_APP_SECRET=your_app_secret
DOUDIAN_ACCESS_TOKEN=your_access_token
DOUDIAN_SHOP_ID=your_shop_id

# 京东
JD_APP_KEY=your_app_key
JD_APP_SECRET=your_app_secret
JD_ACCESS_TOKEN=your_access_token

# 拼多多
PDD_CLIENT_ID=your_client_id
PDD_CLIENT_SECRET=your_client_secret
PDD_ACCESS_TOKEN=your_access_token

# 快手
KUAISHOU_APP_KEY=your_app_key
KUAISHOU_APP_SECRET=your_app_secret
KUAISHOU_SIGN_SECRET=your_sign_secret
KUAISHOU_ACCESS_TOKEN=your_access_token

# 小红书
XHS_CLIENT_ID=your_client_id
XHS_CLIENT_SECRET=your_client_secret
XHS_ACCESS_TOKEN=your_access_token

# 微信小店
WX_APP_ID=your_app_id
WX_APP_SECRET=your_app_secret

# 巨量引擎
OCEANENGINE_ACCESS_TOKEN=your_access_token
OCEANENGINE_ADVERTISER_ID=your_advertiser_id

# 淘宝
TAOBAO_APP_KEY=your_app_key
TAOBAO_APP_SECRET=your_app_secret
TAOBAO_ACCESS_TOKEN=your_access_token
```

### 3. 启动 MCP Server

```bash
# 启动单个平台
mcp-cn-doudian

# 或用 Docker 启动全部
docker-compose up
```

### 4. 在 AI Agent 中使用

#### Claude Code / Cowork

在 `.claude/settings.json` 中添加 MCP 配置：

```json
{
  "mcpServers": {
    "doudian": {
      "command": "mcp-cn-doudian",
      "env": {
        "DOUDIAN_APP_KEY": "...",
        "DOUDIAN_APP_SECRET": "..."
      }
    }
  }
}
```

#### Kimi Work / 通义

参考各平台的 MCP 接入文档。

### 5. 使用模板

将模板的 `prompt.md` 中的 `{{EXAMPLE_DATA}}` 替换为 MCP Server 返回的真实数据：

```
# 在 AI Agent 中执行：
1. 调用 get_order_list 获取订单数据
2. 调用 get_refund_list 获取退款数据
3. 将数据填入模板 prompt
4. 生成日报
```

## 数据格式

所有模板使用统一的数据格式（由 `shared/normalizer.py` 提供）：

| 字段 | 类型 | 说明 |
|------|------|------|
| 金额 | int | 单位：分（1元=100分） |
| 时间 | string | ISO 8601 格式 |
| 状态 | string | 统一枚举值 |

详见 [normalizer.py](../shared/normalizer.py) 文档。

## 常见问题

### Q: 没有 API 凭证怎么办？

使用 `example-data.json` 中的示例数据体验模板效果。等有真实凭证后再接入。

### Q: 模板支持哪些 AI Agent？

支持所有支持 MCP 协议的 Agent：Claude Code、Cowork、Kimi Work、通义、Cursor 等。

### Q: 如何自定义模板？

直接修改 `prompt.md` 中的角色定义、任务说明和输出格式。
