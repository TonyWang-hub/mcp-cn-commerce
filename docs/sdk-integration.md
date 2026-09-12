# Explicit platform client SDK

## Specification and implementation plan

This SDK gives a host application one client per authorization snapshot. The host
owns OAuth, token refresh, tenant authorization, persistence, and business data
normalization. The SDK never selects a shop from process environment variables or
changes an MCP server's global client.

Public entry point:

```python
create_platform_client(platform, credentials, *, http_client=None, rate_limiter=None)
```

It returns a `PlatformClient` with `call(operation, params)`, `close()`, and an
immutable operation catalogue. Operation names follow the existing tools
(`get_order_list`, `get_order_detail`, `get_refund_list`, `get_refund_detail`,
`get_shop_info` where implemented). Parameters are the existing low-level
platform adapter's business parameters, not universally normalized fields.
Unknown operations and attempts to override routing or credential fields fail
before network access. The public response is the adapter's dictionary envelope.

Each factory call copies and validates explicit credentials. A supplied HTTP
client is borrowed: closing this wrapper cannot close it, and a closed external
client must fail rather than silently create another transport. Without an
injected HTTP client the wrapper owns its connection pool. The configurable rate
limiter can be injected, including a shared limiter for an application's quota.
Refreshing credentials requires creating a new SDK client; it cannot mutate an
existing authorization snapshot.

Implementation sequence:

1. RED: concurrent requests for two shops prove separate signed wire credentials;
   resource injection/ownership, unknown methods and credential override rejection.
2. Add explicit construction and read-only routing using existing adapters.
3. Cover every published mapping with actual HTTPX MockTransport requests; preserve
   existing CLI tests and record contract status independently of transport tests.
4. Run focused and full checks, document actual results and remaining live gates.

No local or simulated transport test proves merchant platform acceptance. Contract
status is recorded per operation, and every operation initially has
`live_verified=False`. Unsupported or unverified platform contracts are not
promoted to live support by the SDK.

## Use from a service

This SDK, the normalizers and `shared.aggregation.build_daily_report` are public
Core capabilities under the repository's unchanged MIT license. A host can use
multiple explicit authorization snapshots and supply normalized records from
multiple shops to the deterministic report builder without Pro. The host remains
responsible for obtaining all required pages and declaring data completeness.
Private Pro adds authorization governance, tenant/shop access control, encrypted
persistence, restartable collection, report history, scheduling and audit; it
does not own the already-public aggregation algorithm exclusively. Core never
imports or depends on Pro or the separate commercial HTTP Client. See the
[distribution boundary and CI checks](core-pro-boundary.md).

```python
import httpx
from shared.platform_clients import create_platform_client
from shared.cn_commerce_base import ConfigurableRateLimiter

async def read_orders(authorization_snapshot):
    limiter = ConfigurableRateLimiter()  # reuse per app if its quota is shared
    async with httpx.AsyncClient(timeout=30) as transport:
        async with create_platform_client(
            "taobao",
            authorization_snapshot,
            http_client=transport,
            rate_limiter=limiter,
        ) as client:
            return await client.call("get_order_list", {
                "fields": "tid,status,payment,created,pay_time",
                "start_created": "2026-09-09 00:00:00",
                "end_created": "2026-09-09 23:59:59",
                "page_no": 1,
                "page_size": 100,
            })
```

This is one page, not a complete daily report. The host must validate its user's
access to the selected merchant and shop, obtain an up-to-date snapshot, collect
all pages, normalize business data and apply response privacy rules. SDK errors
propagate as exceptions; they are not converted into apparently successful empty
lists. No transport credential, method name or URL can be supplied through
business parameters.

The optional rate limiter follows `await acquire(platform, endpoint)`. The
platform argument is the adapter's identifier (`DOUDIAN`, `TAOBAO`, `JD`,
`PINDUODUO`, `KUAISHOU`, `XHS`, `WEIXIN_STORE`, `OCEANENGINE`). It is invoked per
attempt, including retries. The default is an independent configurable limiter.

| Factory platform | Explicit credentials | Parameter and response contract |
|---|---|---|
| `doudian` | `app_key`, `app_secret`, `access_token`, `shop_id` | Native business JSON; response is the `data` dictionary unwrapped by the existing adapter |
| `taobao` | `app_key`, `app_secret`, `access_token` | TOP business fields, including caller-selected `fields`; response retains the TOP method envelope |
| `youzan` | `access_token`; optional `app_key`, `app_secret` | Native business JSON; returns the `success`/`code`/`data` envelope. SDK only; no environment-backed MCP CLI |
| `jd` | `app_key`, `app_secret`, `access_token` | Flat native fields inside a signed JOS form; explicit source_id/optional_fields for orders; [JD contract](jd-contract.md) |
| `pinduoduo` | `app_key`, `app_secret`, `access_token` | App fields hold PDD client ID/secret; business reads currently unsupported pending official schema access |
| `kuaishou` | `app_key`, `app_secret`, `access_token`, `sign_secret` | Native camelCase fields inside signed JSON param; current GET cursor/pcursor protocol; [Kuaishou contract](kuaishou-contract.md) |
| `xiaohongshu` | `app_key`, `app_secret`, `access_token` | App fields hold appId/appSecret; existing local alias fields such as `start_time`, `end_time`, `order_id`, `refund_id` are translated by the adapter |
| `weixin_store` | `access_token`; optional `app_key`, `app_secret` | Native JSON body (shop info uses GET); order list uses seconds-based `create_time_range`/`update_time_range`, `page_size`, `next_key`; fixed static token mode |
| `oceanengine` | `access_token`; optional `app_key`, `app_secret` | Native Marketing API fields; arrays/dicts in query values are serialized by the adapter |

Unknown credential keys are rejected. Client secrets are strings copied at
construction, never loaded from environment or updated in place. To renew a
token, the host creates a new client and retires the previous client after its
in-flight requests finish. External clients must be created with the host's
intended timeout/TLS/proxy settings; the wrapper never replaces a closed borrowed
transport or closes it through reconnect/close paths.

## Catalogue and evidence status

Current catalogue checked against Core `6b6a7f9fbe336273e331ec70aa3322f37ae51580` on
2026-09-11. This table describes explicit SDK operations, not every historical MCP
tool. Registration, documented contract, callable SDK mapping and merchant live
acceptance are separate states. See [release readiness](release-readiness.md).

`operation_catalog(platform)` requires no credentials, creates no transport, and
returns the same read-only mapping of frozen `Operation` records as
`client.operations`. Services can inspect capabilities before obtaining or
refreshing authorization:

- `endpoint`: existing low-level adapter route (XHS entries are local aliases).
- `supported`: whether the SDK has an existing adapter mapping. It is not an
  assertion of merchant permission or live availability.
- `contract_status`: `documented` means the specific official contract was read;
  `transport_only` means authentication/transport was checked but this business
  mapping still needs verification; `unverified` retains an unresolved contract.
  `partial` marks an identified contract gap; consult `supported` and `reason` before calling.
- `live_verified`: currently **false for every operation**.
- `reason`: explains an explicitly unsupported mapping.

| Platform | Callable operations | Evidence and omissions |
|---|---|---|
| 抖店 | Orders list/detail, refunds list/detail | Four business contracts documented on 2026-09-10; general shop info explicitly unsupported. Native fields and live gates: [Doudian contract](doudian-contract.md) |
| 淘宝 | Orders list/detail/increment, refunds list/detail, shop info | Five order/refund contracts documented; shop info transport-only. [TOP contract](taobao-contract.md) records required fields, windows and application permission limits |
| 有赞 | Orders list/detail, refunds list/detail, shop info | Five documented SDK-only contracts; [Youzan contract](youzan-contract.md) records current API versions and pagination/amount differences |
| 京东 | Orders list/detail, shop info, `get_aftersale_list`, `get_aftersale_refund_detail` | Five documented JOS contracts. The two after-sale reads do not provide all completed refunds; generic `get_refund_list/get_refund_detail` remain unsupported and Pro refund collection remains unavailable. [JD contract](jd-contract.md), [funds evidence and gaps](platform-gap-evidence-20260911.md) |
| 拼多多 | None | Partial/unsupported: current official business schema was not accessible; see [PDD contract](pinduoduo-contract.md) |
| 快手 | Orders list/detail, refunds list/detail, shop info | Five documented SDK/CLI contracts; shop info has no shop ID, so Pro OAuth binding remains pending |
| 小红书 | Orders list/detail, refunds list/detail | Four documented native queries; shop info unsupported. Order-query `startTime/endTime` and refund-detail `refundTime` units remain unresolved, so Pro Source is blocked. [XHS contract](xiaohongshu-contract.md), [precise field gaps](platform-gap-evidence-20260911.md) |
| 微信小店 | Orders list/detail, refunds list/detail, shop info | Five documented contracts; refund cursor and shop GET corrected; real shop authorization still unverified |
| 巨量引擎 | Advertiser info, account balance | Two documented ad-gateway reads; reports unsupported pending current dataset migration. Merchant orders/refunds/shop-info explicitly unsupported |

See [remaining platform contracts](remaining-platform-contracts.md) for the 2026-09-10 SDK migrations and test-account evidence.
See [official access status](official-access-status.md) for original official URLs,
retrieval dates and precise remaining live credential requirements. Adding this
SDK does not close those gates. Response schema normalization and tenant-level
PII masking remain host responsibilities.

## Compatibility and validation

Platform transport classes now live in `servers/<platform>/client.py`. Existing
`server.py` imports re-export their previous class names, exceptions and CLI
entry points. SDK construction imports only the client modules, so CLI globals
and environment-backed startup cannot participate in credential selection.

The implementation began with 8 failing SDK tests, followed by the two-platform
GREEN checks and 114 unchanged 抖店/TOP tests. The remaining platform routing and
unsupported metadata tests then failed before their implementations were added.
Wire tests use real HTTPX `MockTransport`, not live merchant endpoints. The initial extraction snapshot covered
39 then-callable mappings (historical count, before subsequent contract restrictions), two simultaneous authorizations on each of 8 platforms,
input-snapshot isolation, protocol-field override rejection, independent/shared
transport ownership, explicit credential validation, immutable metadata, and a
fresh-process check for environment/global-server side effects.

Initial SDK extraction checks on 2026-09-10 (before the Doudian contract correction;
see its [validation record](doudian-contract.md) for subsequent results):

- Python 3.12.3: 74 SDK tests passed; complete suite 1660 passed plus 20 subtests.
- Python 3.14.6: complete suite 1660 passed plus 20 subtests.
- Black and Ruff passed; mypy reported no issues; Pylint 10.00/10; Bandit reported
  no issues. Tool metadata retained 8 platforms and 155 MCP tools.
- Wheel and sdist built successfully in an isolated build environment; both
  passed `twine check`.
- A new Python 3.12 virtual environment installed the wheel using the runtime
  lock. From a neutral directory, all 24 real MCP stdio scenarios passed
  (registry CLI, standalone entry point, missing-credentials behavior for each
  platform). Separate installed-wheel checks exercised all 8 explicit SDK
  adapters through HTTPX without importing MCP server modules.
- AST comparison confirmed all extracted non-constructor platform methods
  exactly match the baseline; constructor changes only forward resource injection.

These initial checks did not call merchant APIs or start a local container runtime.
Subsequent exact-SHA CI and package checks are recorded in [release readiness](release-readiness.md),
including the newer Python matrix and remote container results. They do not
retroactively turn the historical extraction snapshot into merchant live evidence.
