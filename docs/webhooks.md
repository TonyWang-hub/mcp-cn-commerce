# Webhooks

Real-time event notifications for e-commerce platform updates.

## Overview

Webhooks allow your application to receive real-time notifications when events occur on connected e-commerce platforms. Instead of polling for changes, webhooks push data to your endpoint as events happen.

## Event Types

| Event Type | Description |
|------------|-------------|
| `order_update` | Order status changes (created, paid, shipped, completed, cancelled) |
| `inventory_change` | Stock level updates (low stock, out of stock, restocked) |
| `product_update` | Product information changes (price, description, images) |
| `refund_request` | Refund initiated or processed |
| `payment_received` | Payment confirmed for an order |
| `shipping_update` | Shipping status changes (shipped, in transit, delivered) |
| `review_submitted` | New customer review submitted |
| `coupon_used` | Coupon or promotion code used |
| `custom` | User-defined custom event type |

## Quick Start

### 1. Initialize the Webhook Manager

```python
from cn_commerce_base import WebhookManager, WebhookEvent, WebhookEventType

manager = WebhookManager()
```

### 2. Subscribe to Events

```python
# Subscribe to order and inventory events
subscription = manager.subscribe(
    url="https://your-app.com/webhooks/callback",
    event_types=[WebhookEventType.ORDER_UPDATE, WebhookEventType.INVENTORY_CHANGE],
    secret="your-shared-secret",  # Optional: auto-generated if not provided
    platform="TAOBAO",
)

print(f"Subscription ID: {subscription.subscription_id}")
```

### 3. Create and Trigger Events

```python
import asyncio

async def trigger_order_update():
    event = WebhookEvent(
        event_type=WebhookEventType.ORDER_UPDATE,
        platform="TAOBAO",
        payload={
            "order_id": "123456789",
            "status": "shipped",
            "tracking_number": "SF1234567890",
        },
        source="order_123456789",
    )

    results = await manager.trigger(event)
    for result in results:
        print(f"Delivered to {result.subscription_id}: success={result.success}")

asyncio.run(trigger_order_update())
```

### 4. Verify Incoming Webhooks

When receiving webhook callbacks, verify the signature to ensure authenticity:

```python
from fastapi import FastAPI, Request, HTTPException
from cn_commerce_base import WebhookSignatureVerifier

app = FastAPI()

@app.post("/webhooks/callback")
async def handle_webhook(request: Request):
    # Get the signature from headers
    signature = request.headers.get("X-Webhook-Signature", "")

    # Get the raw body
    body = await request.body()

    # Verify signature
    verifier = WebhookSignatureVerifier(secret="your-shared-secret")
    if not verifier.verify(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Process the event
    payload = await request.json()
    event = payload.get("event", {})
    print(f"Received {event.get('event_type')} event")

    return {"status": "ok"}
```

## Custom Delivery Callbacks

For advanced use cases, register custom delivery callbacks:

```python
import httpx
from cn_commerce_base import WebhookDeliveryResult

async def custom_delivery(subscription, event, payload_bytes, signature):
    """Custom HTTP delivery with platform-specific headers."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                subscription.url,
                content=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": signature,
                    "X-Webhook-Event": event.event_type,
                    "X-Webhook-ID": event.event_id,
                },
                timeout=30.0,
            )
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=200 <= response.status_code < 300,
                status_code=response.status_code,
            )
        except Exception as e:
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=False,
                error=str(e),
            )

manager.add_delivery_callback(custom_delivery)
```

## Managing Subscriptions

### List Subscriptions

```python
# List all active subscriptions
all_subs = manager.list_subscriptions()

# Filter by event type
order_subs = manager.list_subscriptions(event_type="order_update")

# Filter by platform
taobao_subs = manager.list_subscriptions(platform="TAOBAO")

# Include inactive subscriptions
all_subs = manager.list_subscriptions(active_only=False)
```

### Update a Subscription

```python
manager.update_subscription(
    subscription_id="sub-123",
    url="https://new-endpoint.com/webhook",
    is_active=True,
)
```

### Unsubscribe

```python
manager.unsubscribe("sub-123")
```

## Delivery Statistics

Monitor webhook delivery performance:

```python
stats = manager.get_delivery_stats()
print(f"""
Total deliveries: {stats['total_deliveries']}
Success rate: {stats['success_rate'] * 100:.1f}%
Average latency: {stats['avg_latency_ms']:.2f}ms
Active subscriptions: {stats['active_subscriptions']}
""")
```

## Error Handling

### Automatic Retry

Failed deliveries are automatically retried with exponential backoff:

- **Default retries**: 3 attempts
- **Backoff**: Exponential (2^n seconds, max 30s)
- **Auto-disable**: After 10 consecutive failures

### Delivery Errors

```python
from cn_commerce_base import WebhookDeliveryError

try:
    results = await manager.trigger(event)
    for result in results:
        if not result.success:
            print(f"Delivery failed: {result.error}")
except WebhookDeliveryError as e:
    print(f"Webhook error: {e.message}")
```

## Security Best Practices

1. **Always verify signatures** - Use `WebhookSignatureVerifier` to validate incoming webhooks
2. **Use HTTPS** - Always use HTTPS endpoints for webhook URLs
3. **Rotate secrets** - Periodically update webhook secrets
4. **Validate payloads** - Validate event structure before processing
5. **Idempotent processing** - Design handlers to be idempotent (events may be delivered multiple times)

## Platform-Specific Examples

### Taobao/Alibaba

```python
subscription = manager.subscribe(
    url="https://your-app.com/webhooks/taobao",
    event_types=[WebhookEventType.ORDER_UPDATE],
    platform="TAOBAO",
    metadata={"shop_id": "12345"},
)
```

### JD.com

```python
subscription = manager.subscribe(
    url="https://your-app.com/webhooks/jd",
    event_types=[WebhookEventType.INVENTORY_CHANGE, WebhookEventType.PRODUCT_UPDATE],
    platform="JD",
)
```

### Pinduoduo

```python
subscription = manager.subscribe(
    url="https://your-app.com/webhooks/pdd",
    event_types=[WebhookEventType.ORDER_UPDATE, WebhookEventType.REFUND_REQUEST],
    platform="PINDUODUO",
)
```

## API Reference

### WebhookManager

| Method | Description |
|--------|-------------|
| `subscribe(url, event_types, ...)` | Register a new webhook subscription |
| `unsubscribe(subscription_id)` | Remove a subscription |
| `get_subscription(subscription_id)` | Get subscription by ID |
| `list_subscriptions(...)` | List subscriptions with filters |
| `update_subscription(...)` | Update subscription settings |
| `trigger(event)` | Send event to matching subscriptions |
| `verify_signature(...)` | Verify webhook payload signature |
| `get_delivery_stats()` | Get delivery statistics |
| `clear_history()` | Clear event and delivery history |
| `add_delivery_callback(callback)` | Register custom delivery handler |

### WebhookEvent

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | `str` | Unique event identifier (auto-generated) |
| `event_type` | `str` | Event type (see Event Types) |
| `platform` | `str` | Source platform |
| `payload` | `dict` | Event data |
| `timestamp` | `str` | ISO 8601 timestamp |
| `source` | `str` | Source identifier |
| `version` | `str` | API version (default: "1.0") |

### WebhookSubscription

| Field | Type | Description |
|-------|------|-------------|
| `subscription_id` | `str` | Unique subscription ID |
| `url` | `str` | Callback URL |
| `event_types` | `list[str]` | Subscribed event types |
| `secret` | `str` | Shared secret for signing |
| `platform` | `str` | Platform identifier |
| `is_active` | `bool` | Whether subscription is active |
| `created_at` | `str` | Creation timestamp |
| `last_triggered_at` | `str` | Last delivery timestamp |
| `failure_count` | `int` | Consecutive failure count |
| `metadata` | `dict` | Additional metadata |
