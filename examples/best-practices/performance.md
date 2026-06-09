# 性能优化最佳实践

本页介绍使用 mcp-cn-commerce 时的性能优化建议。

## 目录

- [查询优化](#查询优化)
- [分页策略](#分页策略)
- [缓存策略](#缓存策略)
- [并发控制](#并发控制)
- [API 调用优化](#api-调用优化)

---

## 查询优化

### 1. 限制时间范围

**不推荐**：查询全量数据
```
请帮我查询京东所有的订单
```

**推荐**：指定时间范围
```
请帮我查询京东最近 7 天的订单
```

**原因**：查询全量数据会导致：
- 响应时间过长
- API 调用次数过多
- 内存占用过大

### 2. 使用筛选条件

**不推荐**：查询所有订单后筛选
```
请帮我查询京东所有订单，然后找出待发货的
```

**推荐**：直接使用筛选条件
```
请帮我查询京东状态为"待发货"的订单
```

**原因**：使用筛选条件可以：
- 减少返回数据量
- 降低 API 调用次数
- 提高响应速度

### 3. 选择必要的字段

**不推荐**：查询所有字段
```
请帮我查询京东订单的所有信息
```

**推荐**：只查询需要的字段
```
请帮我查询京东订单的订单号、金额和状态
```

**原因**：减少数据传输量，提高响应速度。

---

## 分页策略

### 1. 合理设置分页大小

**不推荐**：设置过大的分页大小
```
page_size: 1000
```

**推荐**：根据实际需求设置
```
page_size: 20-100
```

**建议**：
- 首次查询：page_size = 20
- 批量处理：page_size = 50-100
- 大数据量：page_size = 100

### 2. 使用游标分页

对于大数据量查询，建议使用游标分页：

```python
# 第一页
page = 1
while True:
    data = query(page=page, page_size=100)
    if not data:
        break
    process(data)
    page += 1
```

### 3. 避免深度分页

**不推荐**：查询深页数据
```
page: 1000
page_size: 20
```

**推荐**：使用时间范围或其他条件缩小范围
```
start_time: "2024-01-01"
end_time: "2024-01-31"
page: 1
page_size: 100
```

---

## 缓存策略

### 1. 缓存静态数据

适合缓存的数据：
- 商品信息（变化频率低）
- 店铺信息（变化频率低）
- 广告计划信息（变化频率中）

不适合缓存的数据：
- 订单数据（实时性要求高）
- 库存数据（实时性要求高）
- 广告报表数据（实时性要求高）

### 2. 设置合理的缓存过期时间

```python
# 商品信息：缓存 1 小时
cache_ttl = 3600

# 店铺信息：缓存 24 小时
cache_ttl = 86400

# 订单数据：不缓存
cache_ttl = 0
```

### 3. 缓存更新策略

- **主动更新**：数据变化时主动更新缓存
- **被动更新**：缓存过期时重新查询
- **定时更新**：定期更新缓存

---

## 并发控制

### 1. 限制并发数量

**不推荐**：无限制并发
```python
# 同时发起 100 个请求
tasks = [query(i) for i in range(100)]
await asyncio.gather(*tasks)
```

**推荐**：限制并发数量
```python
# 限制并发为 5
semaphore = asyncio.Semaphore(5)

async def limited_query(i):
    async with semaphore:
        return await query(i)

tasks = [limited_query(i) for i in range(100)]
await asyncio.gather(*tasks)
```

**建议**：
- 单平台并发：3-5
- 多平台并发：每个平台 2-3
- 总并发：不超过 10

### 2. 使用连接池

```python
# 使用 httpx 连接池
async with httpx.AsyncClient(
    limits=httpx.Limits(
        max_keepalive_connections=5,
        max_connections=10
    )
) as client:
    # 复用连接
    response = await client.get(url)
```

### 3. 避免请求风暴

**不推荐**：短时间内大量请求
```python
for i in range(100):
    await query(i)
```

**推荐**：添加延迟
```python
for i in range(100):
    await query(i)
    await asyncio.sleep(0.1)  # 100ms 延迟
```

---

## API 调用优化

### 1. 批量查询

**不推荐**：逐个查询
```python
for product_id in product_ids:
    product = await get_product(product_id)
```

**推荐**：批量查询（如果 API 支持）
```python
products = await get_products(product_ids)
```

### 2. 减少 API 调用次数

**不推荐**：多次调用获取关联数据
```python
orders = await get_orders()
for order in orders:
    product = await get_product(order.product_id)
```

**推荐**：一次性获取所有需要的数据
```python
orders = await get_orders()
product_ids = [order.product_id for order in orders]
products = await get_products(product_ids)
```

### 3. 使用合适的 API

**不推荐**：使用通用 API
```
查询所有订单，然后筛选
```

**推荐**：使用专用 API
```
使用订单查询 API，直接传入筛选条件
```

---

## 性能监控

### 1. 监控 API 响应时间

```python
import time

start = time.time()
result = await query()
elapsed = time.time() - start

if elapsed > 5:  # 超过 5 秒
    logger.warning(f"API response slow: {elapsed:.2f}s")
```

### 2. 监控 API 调用次数

```python
api_call_count = 0

async def query():
    global api_call_count
    api_call_count += 1
    # ...
```

### 3. 监控错误率

```python
error_count = 0
total_count = 0

async def query():
    global error_count, total_count
    total_count += 1
    try:
        # ...
    except Exception:
        error_count += 1
        raise
```

---

## 性能优化清单

### 查询优化

- [ ] 限制时间范围
- [ ] 使用筛选条件
- [ ] 选择必要的字段
- [ ] 避免查询全量数据

### 分页优化

- [ ] 合理设置分页大小
- [ ] 使用游标分页
- [ ] 避免深度分页

### 缓存优化

- [ ] 缓存静态数据
- [ ] 设置合理的过期时间
- [ ] 实现缓存更新策略

### 并发优化

- [ ] 限制并发数量
- [ ] 使用连接池
- [ ] 避免请求风暴

### API 优化

- [ ] 批量查询
- [ ] 减少 API 调用次数
- [ ] 使用合适的 API

---

## 注意事项

1. **API 限流**：注意各平台的 API 调用频率限制
2. **数据延迟**：考虑平台数据延迟，不要过于频繁查询
3. **错误处理**：实现重试机制，处理临时性错误
4. **监控告警**：监控 API 调用情况，及时发现性能问题

## 相关示例

- [安全建议](security.md) - 安全配置和权限管理
- [错误处理](error-handling.md) - 常见错误和解决方案
- [数据处理](data-processing.md) - 数据处理最佳实践
