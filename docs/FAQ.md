# Frequently Asked Questions

## General

### What is mcp-cn-commerce?

An independent suite of MCP servers and an explicit-credential Python SDK for authorized Chinese merchant business data. Core also includes money/time normalization and deterministic reporting over records supplied by the caller. It is not affiliated with the platforms.

### What makes this different from other MCP servers?

The focus is authorized merchant operations data, read-only adapters and explicit data-completeness handling. Current per-operation support is listed in the [SDK catalogue](sdk-integration.md#catalogue-and-evidence-status); platform registration alone is not evidence that every API works.

### Is Core free, and can it calculate multi-shop reports?

Yes. Core remains under the unchanged [MIT license](../LICENSE). The explicit SDK, normalizers and `build_daily_report` multi-shop calculation are already public and remain available without Pro. The caller supplies normalized records, timezone and truthful completeness information. It must obtain the required pages itself; a report is not proof of complete merchant accounts.

### What does Pro add?

Pro reuses Core and adds authorization lifecycle governance, encrypted application/grant storage, tenant/shop access control, persistent collection and restart recovery, report history, scheduling and audit. It does not make the public aggregation algorithm exclusive. Pro is separately authorized; standard seed-user beta testing remains free. See [Core/Pro boundaries](core-pro-boundary.md) and the [inquiry guide](pro-inquiry-playbook.md).

### Does Core install private Pro code?

No. Core does not require Pro or the separate commercial HTTP Client. CI checks source imports/dependencies before installation and checks wheel/sdist payloads before installation and public upload. See [the boundary checker](../scripts/check_public_boundary.py). This is a static packaging guard, not a proof against arbitrary renamed/copied implementation.

## Platforms & Compatibility

### Which platforms are supported?

There are eight MCP platform entry points and 155 registered tools, including historical or explicitly unsupported operations. Youzan is an additional SDK-only adapter. Use the [current catalogue](sdk-integration.md#catalogue-and-evidence-status), not old phase labels. PDD merchant SDK reads remain disabled; JD after-sale queries are not complete refunds; XHS collection time contracts and advertising report coverage still have gaps. All platform live acceptance remains unverified.

### Do I need a business license?

Eligibility depends on the actual developer identity, application category, requested API permissions and authorized shop. Do not infer that all personal stores or all enterprise stores can or cannot use an API. Check the actual platform console and current permission review. The [official access record](official-access-status.md) links the platform entry points and distinguishes documentary evidence from merchant acceptance.

### How do I get 淘宝 (Taobao) API credentials?

1. Sign in to the [Taobao Open Platform](https://open.taobao.com/) with the actual applicant identity and inspect available application types and required materials.
2. Create an approved application and obtain its AppKey. Request the specific order/refund permissions and fields needed by the [implemented TOP contracts](taobao-contract.md).
3. Complete seller authorization using the applicable official flow. Registration alone does not guarantee API permissions or a sandbox/test token.
4. Configure credentials on the controlled deployment: the Core MCP process uses `TAOBAO_APP_KEY`, `TAOBAO_APP_SECRET`, `TAOBAO_ACCESS_TOKEN`; SDK hosts pass an explicit credential snapshot. The host manages expiry and renewal.

### Can a 个人店 / 个人 C 店 (individual store) use it?

Earlier wording that personal stores generally could not obtain order permissions was too categorical and lacked evidence for the specific application. Store type alone is insufficient; use the console's actual application and permission decision. To investigate a blocker, share the application category, API name, environment and a redacted error code/screenshot. Do not post secrets, tokens, authorization codes or buyer details.

### Which AI clients work?

Use an MCP-compatible client with stdio support for the Core process. Platform business permissions are separate from the MCP client connection. See [Quick Start](../README_en.md#quick-start).

### Can I use this on Windows / macOS / Linux?

Core requires Python 3.11+. Installation and transport evidence is tied to specific environments and commits; see [release readiness](release-readiness.md). Do not treat source portability as all-system or merchant acceptance.

## Security

### Where do my API credentials go?

Core MCP processes read configured credentials locally; the SDK accepts an explicit snapshot. Platform requests send the required authorization to the configured official gateway. Query results go to the caller/MCP client, whose own hosting and data policy also matter. Do not send AppSecret, code or access/refresh tokens through public issues or ordinary email.

### Can AI agents modify my store data?

The supported business operations are read-only. Diagnostic, export and report tools may create local outputs, but do not place orders, issue refunds or alter platform business records. Historical tool registration does not imply every named API contract has been verified.

### How do I report a security issue?

Follow [SECURITY.md](../SECURITY.md); report vulnerabilities privately.

## Development & Troubleshooting

### How do I add a new platform?

Read [CONTRIBUTING.md](../CONTRIBUTING.md), implement the platform client and applicable MCP tools, and verify official request/response contracts. Add tests and catalogue/documentation updates; keep unsupported operations explicit. Preserve the public namespace and dependency checks.

### Will there be CLI support?

CLI entry points already exist: `mcp-cn-commerce --help` lists platform selection, and platform-specific commands are declared in [pyproject.toml](../pyproject.toml).

### Can I use this as a library instead of MCP?

Yes. Use the [explicit SDK](sdk-integration.md) to avoid environment-backed server globals. The host is responsible for authorization, refresh, access control, pagination and persistence.

### "Sign does not match", "App key not exist" or "Invalid access token"

Check the specific platform contract, application/environment, permissions, timestamp units and token expiry. Lifetime and refresh behavior differ by platform and application mode; there is no universal 24-hour lifetime. Provide redacted error metadata, not credentials, when requesting help.

### Tests fail locally but pass in CI

Use the documented Python environment and dependency constraints, and record the failing test and exact source commit. Engineering tests use synthetic transports and local MCP/HTTP connections; they are not evidence of merchant live success. Never replace a controlled fixture with real credentials to make an offline test pass.
