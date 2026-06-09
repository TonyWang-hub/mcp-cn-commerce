# Load Balancing and Failover

mcp-cn-commerce provides built-in load balancing and failover capabilities for distributing API requests across multiple endpoints and handling endpoint failures gracefully.

## Status: opt-in

`LoadBalancer` and `FailoverManager` are **opt-in** building blocks in
`shared.cn_commerce_base`. The base client makes its requests against a single
`BASE_URL`; it does *not* route through a load balancer automatically, and these
classes are not exposed as MCP tools. Wire them in yourself -- the
[Integration with CommerceMCPBase](#integration-with-commercemcpbase) section
below shows a subclass that does exactly that.

## Overview

The load balancing system consists of two main components:

1. **LoadBalancer** - Distributes requests across endpoint pools using configurable strategies
2. **FailoverManager** - Detects failures, manages circuit breakers, and handles endpoint recovery

## Load Balancing Strategies

### Round Robin

Distributes requests sequentially across all healthy endpoints. Each endpoint receives requests in turn, regardless of weight or current load.

```python
from cn_commerce_base import LoadBalancer, LoadBalancingStrategy

lb = LoadBalancer(LoadBalancingStrategy.ROUND_ROBIN)
lb.add_endpoint("https://api1.example.com")
lb.add_endpoint("https://api2.example.com")
lb.add_endpoint("https://api3.example.com")

# Requests cycle through: api1 -> api2 -> api3 -> api1 -> ...
endpoint = lb.get_endpoint()
```

### Weighted

Distributes requests based on endpoint weights. Endpoints with higher weights receive proportionally more traffic.

```python
lb = LoadBalancer(LoadBalancingStrategy.WEIGHTED)
lb.add_endpoint("https://api1.example.com", weight=3)  # Receives ~75% of traffic
lb.add_endpoint("https://api2.example.com", weight=1)  # Receives ~25% of traffic
```

### Least Connections

Routes requests to the endpoint with the fewest active connections. This strategy adapts to varying request durations.

```python
lb = LoadBalancer(LoadBalancingStrategy.LEAST_CONNECTIONS)
lb.add_endpoint("https://api1.example.com")
lb.add_endpoint("https://api2.example.com")

# Track connections manually
endpoint = lb.get_endpoint()
lb.increment_connections(endpoint.url)
try:
    # Make request...
    pass
finally:
    lb.decrement_connections(endpoint.url)
```

## Endpoint Management

### Adding and Removing Endpoints

```python
# Add endpoints
lb.add_endpoint("https://api1.example.com", weight=2)
lb.add_endpoint("https://api2.example.com", weight=1)

# Remove endpoint
lb.remove_endpoint("https://api2.example.com")

# Check pool status
print(f"Total endpoints: {lb.endpoint_count}")
print(f"Healthy endpoints: {lb.healthy_count}")
```

### Health Status

Endpoints are automatically tracked for health status:

```python
# Mark endpoint healthy (resets failure count)
lb.mark_healthy("https://api1.example.com")

# Mark endpoint unhealthy
lb.mark_unhealthy("https://api1.example.com")

# Record request outcomes
lb.record_success("https://api1.example.com", latency_ms=45.2)
lb.record_failure("https://api2.example.com")
```

## Failover Configuration

The `FailoverConfig` dataclass controls failover behavior:

```python
from cn_commerce_base import FailoverConfig

config = FailoverConfig(
    max_failures=3,                    # Mark unhealthy after 3 consecutive failures
    recovery_check_interval=30.0,      # Check recovery every 30 seconds
    recovery_timeout=5.0,              # Timeout for recovery probes
    enable_auto_recovery=True,         # Enable automatic recovery
    circuit_breaker_threshold=0.5,     # Trip breaker at 50% failure rate
    circuit_breaker_reset_seconds=60.0 # Reset breaker after 60 seconds
)
```

### Failure Detection

The FailoverManager tracks consecutive failures and marks endpoints unhealthy:

```python
from cn_commerce_base import LoadBalancer, FailoverManager, FailoverConfig

lb = LoadBalancer()
lb.add_endpoint("https://api1.example.com")
lb.add_endpoint("https://api2.example.com")

fm = FailoverManager(load_balancer=lb, config=FailoverConfig(max_failures=3))

# Report failures
fm.report_failure("https://api1.example.com", error="Connection refused")
fm.report_failure("https://api1.example.com", error="Connection refused")
fm.report_failure("https://api1.example.com", error="Connection refused")
# Endpoint now marked unhealthy after 3 failures

# Report success resets failure count
fm.report_success("https://api1.example.com", latency_ms=50.0)
```

### Circuit Breaker Pattern

The circuit breaker prevents cascading failures by temporarily blocking requests to failing endpoints:

```python
# Check if circuit is open
if fm.is_circuit_open("https://api1.example.com"):
    print("Circuit is open, skipping endpoint")

# Get healthy endpoint (automatically skips open circuits)
endpoint = fm.get_healthy_endpoint()
if endpoint:
    # Make request to endpoint.url
    pass
```

Circuit breaker states:
- **Closed**: Normal operation, requests pass through
- **Open**: Requests blocked, endpoint considered failed
- **Half-Open**: After reset timeout, allows probe requests

### Automatic Recovery

The recovery monitor periodically probes unhealthy endpoints:

```python
# Start background recovery monitor
await fm.start_recovery_monitor()

# Stop recovery monitor
fm.stop_recovery_monitor()

# Manual recovery check
recovered = await fm.check_recovery("https://api1.example.com")
if recovered:
    print("Endpoint recovered!")
```

## Integration with CommerceMCPBase

To use load balancing with your platform client:

```python
from cn_commerce_base import (
    CommerceMCPBase,
    LoadBalancer,
    LoadBalancingStrategy,
    FailoverManager,
    FailoverConfig,
)

class MyPlatformClient(CommerceMCPBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set up load balancing
        self.load_balancer = LoadBalancer(LoadBalancingStrategy.WEIGHTED)
        self.load_balancer.add_endpoint("https://api1.platform.com", weight=2)
        self.load_balancer.add_endpoint("https://api2.platform.com", weight=1)

        # Set up failover
        self.failover_manager = FailoverManager(
            load_balancer=self.load_balancer,
            config=FailoverConfig(max_failures=3)
        )

    async def _request_with_lb(self, method, path, **kwargs):
        """Make request with load balancing and failover."""
        endpoint = self.failover_manager.get_healthy_endpoint()
        if not endpoint:
            raise RuntimeError("No healthy endpoints available")

        try:
            # Temporarily override BASE_URL
            original_url = self.BASE_URL
            self.BASE_URL = endpoint.url
            result = await self._request(method, path, **kwargs)
            self.failover_manager.report_success(endpoint.url)
            self.BASE_URL = original_url
            return result
        except Exception as e:
            self.failover_manager.report_failure(endpoint.url, str(e))
            self.BASE_URL = original_url
            raise
```

## Statistics and Monitoring

### Load Balancer Stats

```python
stats = lb.get_stats()
print(f"Strategy: {stats['strategy']}")
print(f"Healthy endpoints: {stats['healthy_endpoints']}/{stats['total_endpoints']}")

for url, ep_stats in stats['endpoints'].items():
    print(f"  {url}: {ep_stats['total_requests']} requests, "
          f"{ep_stats['total_failures']} failures, "
          f"avg latency {ep_stats['avg_latency_ms']:.1f}ms")
```

### Failover Stats

```python
stats = fm.get_stats()
print(f"Total failure events: {stats['total_failure_events']}")
print(f"Circuit breakers: {len(stats['circuit_breakers'])}")

for url, cb in stats['circuit_breakers'].items():
    if cb['is_open']:
        print(f"  OPEN: {url}")
```

## Best Practices

1. **Choose the right strategy**:
   - Use `ROUND_ROBIN` for homogeneous endpoints
   - Use `WEIGHTED` for heterogeneous endpoints with different capacities
   - Use `LEAST_CONNECTIONS` for varying request durations

2. **Configure appropriate thresholds**:
   - Set `max_failures` based on your error tolerance
   - Tune `circuit_breaker_threshold` based on traffic patterns
   - Set `recovery_check_interval` to balance detection speed and probe overhead

3. **Monitor endpoint health**:
   - Use `get_stats()` to track endpoint performance
   - Set up alerts for circuit breaker state changes
   - Review failure history for patterns

4. **Handle no-healthy-endpoints gracefully**:
   - Always check for `None` from `get_endpoint()`
   - Implement fallback logic (retry after delay, use cached data, etc.)

## API Reference

### LoadBalancer

| Method | Description |
|--------|-------------|
| `add_endpoint(url, weight)` | Add endpoint to pool |
| `remove_endpoint(url)` | Remove endpoint from pool |
| `get_endpoint()` | Select next endpoint |
| `mark_healthy(url)` | Mark endpoint healthy |
| `mark_unhealthy(url)` | Mark endpoint unhealthy |
| `record_success(url, latency_ms)` | Record successful request |
| `record_failure(url)` | Record failed request |
| `increment_connections(url)` | Increment active connections |
| `decrement_connections(url)` | Decrement active connections |
| `get_stats()` | Get load balancer statistics |

### FailoverManager

| Method | Description |
|--------|-------------|
| `report_success(url, latency_ms)` | Report successful request |
| `report_failure(url, error)` | Report failed request |
| `is_circuit_open(url)` | Check circuit breaker status |
| `get_healthy_endpoint()` | Get healthy endpoint |
| `check_recovery(url)` | Probe endpoint for recovery |
| `start_recovery_monitor()` | Start background recovery |
| `stop_recovery_monitor()` | Stop background recovery |
| `get_stats()` | Get failover statistics |
| `reset()` | Reset all failover state |
