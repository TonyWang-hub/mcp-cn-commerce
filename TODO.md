# 待办事项

## PyPI 发布待办

### 已完成 ✅

- [x] 主包 `mcp-cn-commerce` 已发布
- [x] `mcp-cn-oceanengine` 已发布
- [x] `mcp-cn-doudian` 已发布
- [x] `mcp-cn-jd` 已发布
- [x] 更新 README 添加 PyPI 安装说明

### 待上传 ⏳

**因 PyPI 限流（429 Too Many Requests），以下包需要等待 15-30 分钟后上传：**

- [ ] `mcp-cn-taobao`
- [ ] `mcp-cn-pinduoduo`
- [ ] `mcp-cn-kuaishou`
- [ ] `mcp-cn-xiaohongshu`
- [ ] `mcp-cn-weixin-store`

**上传命令：**

```bash
cd /Users/wangzhuo/work/mcp-cn-commerce

# 请使用你的 PyPI API Token 替换 <YOUR_TOKEN>
for platform in taobao pinduoduo kuaishou xiaohongshu weixin-store; do
  echo "=== Uploading $platform ==="
  cd /Users/wangzhuo/work/mcp-cn-commerce/servers/$platform
  twine upload dist/* -u __token__ -p <YOUR_TOKEN>
  sleep 10
done
```

---

## 后续推广待办

### 短期（1-2 周）

- [ ] 提交到 Anthropic 官方 Registry（GitHub PR）
- [ ] 在小红书/知乎/B站发布使用教程
- [ ] 在 V2EX/掘金发布项目介绍

### 中期（1-2 月）

- [ ] 联系 Cherry Studio 官方收录
- [ ] 联系 Kimi Work 官方收录
- [ ] 准备阿里云百炼 MCP 市场上架材料

---

## PyPI 链接

- 主包: https://pypi.org/project/mcp-cn-commerce/0.1.0/
- 巨量引擎: https://pypi.org/project/mcp-cn-oceanengine/0.1.0/
- 抖店: https://pypi.org/project/mcp-cn-doudian/0.1.0/
- 京东: https://pypi.org/project/mcp-cn-jd/0.1.0/
