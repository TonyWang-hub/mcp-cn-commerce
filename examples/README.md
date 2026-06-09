# mcp-cn-commerce 使用示例

本目录包含 mcp-cn-commerce 的各种使用示例，帮助您快速上手。

## 目录结构

```
examples/
├── README.md              # 本文件
├── basic/                 # 基础使用示例
│   ├── query-orders.md    # 订单查询示例
│   ├── query-products.md  # 商品查询示例
│   └── query-ads.md       # 广告数据查询示例
├── advanced/              # 高级使用示例
│   ├── multi-platform.md  # 多平台数据对比
│   ├── data-analysis.md   # 数据分析场景
│   └── automation.md      # 自动化监控
└── best-practices/        # 最佳实践
    ├── performance.md     # 性能优化
    ├── security.md        # 安全建议
    └── error-handling.md  # 错误处理
```

## 快速开始

### 1. 配置环境变量

```bash
# 巨量引擎 (Ocean Engine)
export OCEANENGINE_APP_KEY="your_app_key"
export OCEANENGINE_APP_SECRET="your_app_secret"
export OCEANENGINE_ACCESS_TOKEN="your_access_token"

# 抖店 (Douyin Shop)
export DOUDIAN_APP_KEY="your_app_key"
export DOUDIAN_APP_SECRET="your_app_secret"
export DOUDIAN_SHOP_ID="your_shop_id"
export DOUDIAN_ACCESS_TOKEN="your_access_token"

# 京东 (JD.com)
export JD_APP_KEY="your_app_key"
export JD_APP_SECRET="your_app_secret"
export JD_ACCESS_TOKEN="your_access_token"
```

### 2. 添加到 MCP 客户端

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "mcp-cn-oceanengine"
    },
    "doudian": {
      "command": "mcp-cn-doudian"
    },
    "jd": {
      "command": "mcp-cn-jd"
    }
  }
}
```

### 3. 开始使用

在您的 AI 客户端中，可以直接用自然语言提问：

- "查询京东最近 7 天的订单"
- "查看巨量引擎的广告投放数据"
- "分析抖店的商品库存情况"

## 示例分类

### 基础示例

适合初学者，涵盖最常见的使用场景：

- [订单查询](basic/query-orders.md) - 查询各平台订单数据
- [商品查询](basic/query-products.md) - 查询商品信息和库存
- [广告数据](basic/query-ads.md) - 查询广告投放效果

### 高级示例

适合有经验的用户，展示复杂的数据分析场景：

- [多平台对比](advanced/multi-platform.md) - 跨平台数据对比分析
- [数据分析](advanced/data-analysis.md) - 深度数据分析场景
- [自动化监控](advanced/automation.md) - 设置自动化监控告警

### 最佳实践

生产环境推荐的做法：

- [性能优化](best-practices/performance.md) - 查询优化和性能建议
- [安全建议](best-practices/security.md) - 安全配置和权限管理
- [错误处理](best-practices/error-handling.md) - 常见错误和解决方案

## 相关资源

- [项目文档](../docs/) - 完整文档
- [平台对比](../docs/platforms.md) - 各平台 API 能力对比
- [贡献指南](../CONTRIBUTING.md) - 如何参与项目贡献
