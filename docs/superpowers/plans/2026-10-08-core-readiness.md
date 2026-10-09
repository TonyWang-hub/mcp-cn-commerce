# Core readiness implementation plan

**Goal:** Complete the three approved items: consistent MCP/SDK capability boundaries, a resolvable grouped runtime dependency upgrade, and accurate installation/status/report examples.

**Architecture:** Keep existing MCP tool names and input signatures for discovery compatibility. Share the SDK operation catalogue with MCP capability checks, reject explicitly unsupported operations before making platform HTTP requests, and clearly identify historical unverified tools. The new OceanEngine report guard also rejects before client creation; existing unsupported error contracts remain compatible. Keep documented SDK operations available and preserve the separation between documented contracts and merchant live verification.

**Scope:** Public Core repository only. Pro is a read-only reference for its current engineering candidate; this task does not implement new platform contracts or perform merchant API calls.

## 1. Capability boundaries

- [x] Reproduce the SDK/MCP discrepancy with meaningful regression tests proving upstream calls cannot occur for unsupported operations.
- [x] Add a shared capability description/check mechanism and apply it consistently across all eight platform MCP entry points.
- [x] Preserve documented read-operation behaviour, names, signatures, tool counts and safe operational common tools.
- [x] Clearly label historical unverified operations and verify tool discovery exposes the evidence boundary.
- [x] Run the affected contract/metadata/installation tests and review the diff.

## 2. Runtime dependencies

- [x] Verify the actual metadata constraints of MCP/mcp-types, httpx2/httpcore2 and Pydantic/pydantic_core.
- [x] Upgrade related versions together, regenerate a runtime-only lock and configure Dependabot groups.
- [x] Resolve and install in an isolated Python environment; run pip check without ignoring dependencies.
- [x] Verify the installed MCP SDK and clean wheel/sdist installation with real stdio handshakes.

## 3. Documentation and examples

- [x] Fix the missing explicit promotion amount in the documented daily-report input and execute the example.
- [x] Replace obsolete TODO and global installation guidance with current candidate/stable installation instructions.
- [x] Update public status summaries using the verified Core/Pro/Client versions while preserving exact historical acceptance records.
- [x] Explain the new MCP capability boundary and keep merchant live verification false.

## Final acceptance

- [x] Independent code review of each implementation area; fix material findings.
- [x] Full Core regression suite and existing formatting/type/security checks in the isolated environment.
- [x] Wheel/sdist metadata, public-distribution boundary and locked/latest-supported installation smoke checks.
- [x] Record actual commands and results without attributing historical CI or merchant acceptance to this change.

Acceptance: 2291 tests + 20 subtests, all quality gates, 155 compatible registrations, three clean installations and 72 stdio scenarios passed locally. See [the dated acceptance record](../../release-readiness.md#2026-10-08-本轮本地变更验收) for versions and scope.
