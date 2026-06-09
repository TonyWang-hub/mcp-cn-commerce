# 安全最佳实践

本页介绍使用 mcp-cn-commerce 时的安全建议。

## 目录

- [API 密钥管理](#api-密钥管理)
- [权限控制](#权限控制)
- [数据安全](#数据安全)
- [网络安全](#网络安全)
- [审计日志](#审计日志)

---

## API 密钥管理

### 1. 使用环境变量

**不推荐**：硬编码密钥
```python
app_key = "your_app_key"
app_secret = "your_app_secret"
```

**推荐**：使用环境变量
```python
import os

app_key = os.environ.get("APP_KEY")
app_secret = os.environ.get("APP_SECRET")
```

### 2. 使用 .env 文件

创建 `.env` 文件：
```bash
# 巨量引擎
OCEANENGINE_APP_KEY=your_app_key
OCEANENGINE_APP_SECRET=your_app_secret
OCEANENGINE_ACCESS_TOKEN=your_access_token

# 抖店
DOUDIAN_APP_KEY=your_app_key
DOUDIAN_APP_SECRET=your_app_secret
DOUDIAN_SHOP_ID=your_shop_id
DOUDIAN_ACCESS_TOKEN=your_access_token

# 京东
JD_APP_KEY=your_app_key
JD_APP_SECRET=your_app_secret
JD_ACCESS_TOKEN=your_access_token
```

**注意**：将 `.env` 文件添加到 `.gitignore`，不要提交到代码仓库。

### 3. 密钥轮换

**建议**：
- 定期轮换 API 密钥（建议每 3-6 个月）
- 轮换时更新所有使用该密钥的服务
- 保留旧密钥一段时间，确保平稳过渡

### 4. 密钥存储

**不推荐**：
- 将密钥存储在代码中
- 将密钥存储在配置文件中（未加密）
- 将密钥提交到代码仓库

**推荐**：
- 使用环境变量
- 使用密钥管理服务（如 AWS Secrets Manager、HashiCorp Vault）
- 使用加密的配置文件

---

## 权限控制

### 1. 最小权限原则

**建议**：
- 只授予必要的 API 权限
- 不要使用管理员权限的 API 密钥
- 为不同的应用使用不同的 API 密钥

### 2. 权限检查

```python
# 检查 API 密钥权限
def check_permissions(api_key):
    # 检查是否有查询订单的权限
    if not can_query_orders(api_key):
        raise PermissionError("No permission to query orders")
    
    # 检查是否有查询商品的权限
    if not can_query_products(api_key):
        raise PermissionError("No permission to query products")
```

### 3. 访问控制

```python
# 限制访问来源
ALLOWED_IPS = ["192.168.1.0/24", "10.0.0.0/8"]

def check_access(ip):
    if ip not in ALLOWED_IPS:
        raise AccessDeniedError(f"IP {ip} not allowed")
```

---

## 数据安全

### 1. 数据脱敏

**敏感数据**：
- 手机号码
- 身份证号
- 银行卡号
- 地址信息

**脱敏示例**：
```python
def mask_phone(phone):
    """手机号脱敏：138****1234"""
    if len(phone) == 11:
        return phone[:3] + "****" + phone[7:]
    return phone

def mask_id_card(id_card):
    """身份证脱敏：110***********1234"""
    if len(id_card) == 18:
        return id_card[:3] + "*" * 11 + id_card[14:]
    return id_card
```

### 2. 数据加密

**传输加密**：
- 使用 HTTPS 协议
- 验证 SSL 证书

**存储加密**：
- 敏感数据加密存储
- 使用强加密算法（如 AES-256）

### 3. 数据备份

**建议**：
- 定期备份重要数据
- 备份数据加密存储
- 定期测试备份恢复

---

## 网络安全

### 1. 使用 HTTPS

**不推荐**：使用 HTTP
```python
url = "http://api.example.com/data"
```

**推荐**：使用 HTTPS
```python
url = "https://api.example.com/data"
```

### 2. 验证 SSL 证书

```python
import httpx

# 验证 SSL 证书
async with httpx.AsyncClient(verify=True) as client:
    response = await client.get(url)
```

### 3. 限制网络访问

```python
# 限制访问来源
ALLOWED_HOSTS = ["api.example.com", "open.oceanengine.com"]

def check_host(url):
    host = urlparse(url).netloc
    if host not in ALLOWED_HOSTS:
        raise SecurityError(f"Host {host} not allowed")
```

---

## 审计日志

### 1. 记录 API 调用

```python
import logging

logger = logging.getLogger(__name__)

async def query(api_name, params):
    logger.info(f"API call: {api_name}, params: {mask_sensitive(params)}")
    try:
        result = await api_call(api_name, params)
        logger.info(f"API success: {api_name}")
        return result
    except Exception as e:
        logger.error(f"API error: {api_name}, error: {e}")
        raise
```

### 2. 记录敏感操作

```python
def log_sensitive_operation(user, operation, details):
    logger.warning(f"Sensitive operation: user={user}, operation={operation}, details={details}")
```

### 3. 日志存储

**建议**：
- 日志加密存储
- 日志定期归档
- 日志保留至少 90 天

---

## 安全检查清单

### API 密钥安全

- [ ] 使用环境变量存储密钥
- [ ] 不要将密钥提交到代码仓库
- [ ] 定期轮换密钥
- [ ] 使用密钥管理服务

### 权限控制

- [ ] 遵循最小权限原则
- [ ] 为不同应用使用不同密钥
- [ ] 定期审查权限

### 数据安全

- [ ] 敏感数据脱敏
- [ ] 传输使用 HTTPS
- [ ] 存储数据加密
- [ ] 定期备份数据

### 网络安全

- [ ] 验证 SSL 证书
- [ ] 限制访问来源
- [ ] 使用防火墙

### 审计日志

- [ ] 记录 API 调用
- [ ] 记录敏感操作
- [ ] 日志加密存储
- [ ] 定期审查日志

---

## 常见安全问题

### 1. 密钥泄露

**问题**：API 密钥被泄露到公开仓库

**解决方案**：
- 立即轮换密钥
- 检查密钥使用记录
- 加强密钥管理

### 2. 未授权访问

**问题**：未授权的用户访问 API

**解决方案**：
- 加强权限控制
- 使用访问控制列表
- 监控异常访问

### 3. 数据泄露

**问题**：敏感数据被泄露

**解决方案**：
- 加强数据脱敏
- 加密敏感数据
- 限制数据访问

---

## 注意事项

1. **安全意识**：提高安全意识，定期进行安全培训
2. **及时更新**：及时更新依赖库，修复安全漏洞
3. **应急响应**：建立安全应急响应机制
4. **合规要求**：遵守相关法律法规和平台政策

## 相关示例

- [性能优化](performance.md) - 性能优化建议
- [错误处理](error-handling.md) - 常见错误和解决方案
- [数据处理](data-processing.md) - 数据处理最佳实践
