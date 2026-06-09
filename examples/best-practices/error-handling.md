# 错误处理最佳实践

本页介绍使用 mcp-cn-commerce 时的常见错误和解决方案。

## 目录

- [常见错误类型](#常见错误类型)
- [错误处理策略](#错误处理策略)
- [重试机制](#重试机制)
- [错误日志](#错误日志)
- [错误恢复](#错误恢复)

---

## 常见错误类型

### 1. 认证错误

**错误信息**：
```
Authentication failed: Invalid access token
```

**可能原因**：
- Access token 过期
- Access token 无效
- Access token 权限不足

**解决方案**：
```python
# 检查 access token 是否有效
if is_token_expired(access_token):
    # 刷新 token
    new_token = refresh_access_token(refresh_token)
    update_access_token(new_token)
```

### 2. 权限错误

**错误信息**：
```
Permission denied: No permission to access this resource
```

**可能原因**：
- API 密钥权限不足
- 未申请相关 API 权限
- 权限未生效

**解决方案**：
- 检查 API 密钥权限
- 申请必要的 API 权限
- 联系平台技术支持

### 3. 参数错误

**错误信息**：
```
Invalid parameter: start_time format error
```

**可能原因**：
- 参数格式错误
- 参数值超出范围
- 必填参数缺失

**解决方案**：
```python
# 验证参数
def validate_params(params):
    # 检查时间格式
    if 'start_time' in params:
        try:
            datetime.strptime(params['start_time'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            raise ValueError("start_time format error, expected: YYYY-MM-DD HH:MM:SS")
    
    # 检查数值范围
    if 'page_size' in params:
        if params['page_size'] > 100:
            params['page_size'] = 100  # 限制最大值
```

### 4. 频率限制

**错误信息**：
```
Rate limit exceeded: Too many requests
```

**可能原因**：
- API 调用频率超过限制
- 短时间内大量请求

**解决方案**：
```python
import asyncio

async def query_with_retry(params, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await query(params)
        except RateLimitError:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # 指数退避
            else:
                raise
```

### 5. 网络错误

**错误信息**：
```
Network error: Connection timeout
```

**可能原因**：
- 网络连接问题
- 服务器响应超时
- DNS 解析失败

**解决方案**：
```python
import httpx

async def query_with_timeout(url, params, timeout=30):
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.get(url, params=params)
            return response.json()
        except httpx.TimeoutException:
            logger.error("Request timeout")
            raise
        except httpx.NetworkError as e:
            logger.error(f"Network error: {e}")
            raise
```

---

## 错误处理策略

### 1. 错误分类

```python
class ErrorCode:
    # 认证错误
    AUTH_FAILED = "AUTH_FAILED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    
    # 权限错误
    PERMISSION_DENIED = "PERMISSION_DENIED"
    
    # 参数错误
    INVALID_PARAM = "INVALID_PARAM"
    MISSING_PARAM = "MISSING_PARAM"
    
    # 频率限制
    RATE_LIMIT = "RATE_LIMIT"
    
    # 网络错误
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    
    # 服务器错误
    SERVER_ERROR = "SERVER_ERROR"
```

### 2. 错误处理流程

```python
async def handle_error(error):
    """统一错误处理"""
    if isinstance(error, AuthenticationError):
        # 认证错误：尝试刷新 token
        await refresh_token()
        return await retry_query()
    
    elif isinstance(error, PermissionError):
        # 权限错误：记录日志，通知管理员
        logger.error(f"Permission denied: {error}")
        notify_admin(error)
        return None
    
    elif isinstance(error, RateLimitError):
        # 频率限制：等待后重试
        await asyncio.sleep(60)
        return await retry_query()
    
    elif isinstance(error, NetworkError):
        # 网络错误：重试
        return await retry_query(max_retries=3)
    
    else:
        # 其他错误：记录日志
        logger.error(f"Unknown error: {error}")
        raise
```

### 3. 错误响应格式

```python
{
    "success": False,
    "error": {
        "code": "AUTH_FAILED",
        "message": "Authentication failed",
        "details": "Invalid access token",
        "timestamp": "2024-01-01T12:00:00Z"
    }
}
```

---

## 重试机制

### 1. 指数退避重试

```python
import asyncio
import random

async def retry_with_backoff(func, max_retries=3, base_delay=1):
    """指数退避重试"""
    for attempt in range(max_retries):
        try:
            return await func()
        except RetryableError as e:
            if attempt < max_retries - 1:
                # 指数退避 + 随机抖动
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            else:
                raise
```

### 2. 条件重试

```python
async def retry_if_recoverable(func, max_retries=3):
    """仅对可恢复错误重试"""
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if is_recoverable(e) and attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                raise

def is_recoverable(error):
    """判断错误是否可恢复"""
    recoverable_errors = [
        NetworkError,
        TimeoutError,
        RateLimitError,
        ServerError,
    ]
    return any(isinstance(error, err) for err in recoverable_errors)
```

### 3. 重试配置

```python
RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay": 1,
    "max_delay": 60,
    "retryable_errors": [
        NetworkError,
        TimeoutError,
        RateLimitError,
        ServerError,
    ]
}
```

---

## 错误日志

### 1. 结构化日志

```python
import logging
import json

logger = logging.getLogger(__name__)

def log_error(error, context=None):
    """记录结构化错误日志"""
    log_data = {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "timestamp": datetime.utcnow().isoformat(),
        "context": context or {}
    }
    logger.error(json.dumps(log_data, ensure_ascii=False))
```

### 2. 错误上下文

```python
async def query_with_context(params):
    """带上下文的查询"""
    context = {
        "api_name": "get_order_list",
        "params": mask_sensitive(params),
        "request_id": generate_request_id()
    }
    
    try:
        return await query(params)
    except Exception as e:
        log_error(e, context)
        raise
```

### 3. 日志级别

```python
# DEBUG: 调试信息
logger.debug(f"Query params: {params}")

# INFO: 正常操作
logger.info(f"Query success: {api_name}")

# WARNING: 警告信息
logger.warning(f"Slow query: {elapsed:.2f}s")

# ERROR: 错误信息
logger.error(f"Query failed: {error}")

# CRITICAL: 严重错误
logger.critical(f"Service unavailable: {error}")
```

---

## 错误恢复

### 1. 降级策略

```python
async def query_with_fallback(params):
    """带降级的查询"""
    try:
        # 优先使用主 API
        return await query_primary(params)
    except Exception as e:
        logger.warning(f"Primary API failed: {e}, trying fallback")
        try:
            # 降级到备用 API
            return await query_fallback(params)
        except Exception as e2:
            logger.error(f"Fallback API failed: {e2}")
            # 返回默认值或缓存数据
            return get_cached_data(params)
```

### 2. 熔断机制

```python
class CircuitBreaker:
    """熔断器"""
    
    def __init__(self, failure_threshold=5, reset_timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    async def call(self, func):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitBreakerOpenError("Circuit breaker is open")
        
        try:
            result = await func()
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
            
            raise
```

### 3. 恢复策略

```python
async def recover_from_error(error):
    """从错误中恢复"""
    if isinstance(error, TokenExpiredError):
        # 刷新 token
        await refresh_token()
        return True
    
    elif isinstance(error, RateLimitError):
        # 等待后重试
        await asyncio.sleep(60)
        return True
    
    elif isinstance(error, NetworkError):
        # 检查网络连接
        if await check_network():
            return True
        return False
    
    else:
        # 无法恢复
        return False
```

---

## 错误处理清单

### 错误分类

- [ ] 认证错误处理
- [ ] 权限错误处理
- [ ] 参数错误处理
- [ ] 频率限制处理
- [ ] 网络错误处理
- [ ] 服务器错误处理

### 重试机制

- [ ] 实现指数退避重试
- [ ] 设置最大重试次数
- [ ] 区分可重试和不可重试错误

### 错误日志

- [ ] 记录结构化错误日志
- [ ] 包含错误上下文
- [ ] 设置合适的日志级别

### 错误恢复

- [ ] 实现降级策略
- [ ] 实现熔断机制
- [ ] 实现恢复策略

---

## 注意事项

1. **错误分类**：区分可恢复和不可恢复错误
2. **重试策略**：不要无限重试，设置合理的重试次数
3. **日志记录**：记录足够的错误信息，便于排查问题
4. **用户友好**：提供友好的错误提示，不要暴露技术细节

## 相关示例

- [性能优化](performance.md) - 性能优化建议
- [安全建议](security.md) - 安全配置和权限管理
- [数据处理](data-processing.md) - 数据处理最佳实践
