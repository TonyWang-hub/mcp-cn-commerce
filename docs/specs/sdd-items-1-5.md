# SDD 规格：仓库整改 Items 1–5

> 状态：草案（待执行）· 分支 `refactor/sdd-items-1-5`
> 决策来源：架构/安全/测试/工程化四维分析 + 用户拍板（第3项=接入产品；第5项=shared 独立成包）

## 背景与核心问题

8 个电商平台 MCP server 共暴露约 115 个只读工具，但 server 层只用到 `_request`/`_sign`；
`shared/cn_commerce_base.py`（6839 行 / 48 类 / 252 方法）中约 5000 行高级能力**从未被任何 server 接入**。
本规格把这些能力**接入产品**（而非删除），同时修复签名/校验安全问题、规范打包发布。

---

## Item 1 — 发布流程前置门槛（P0，零风险）

**现状**：`.github/workflows/publish.yml` 的 `release` job 不依赖任何测试，tag 一推即发版。
**改动**：`release` job 增加 `needs: [test, lint, typecheck, code-quality]`（job 名取自 `test.yml`）。
**验收**：测试任一失败时 release job 不执行。

---

## Item 2 — 签名类型归一化 + 输入校验接入（P0/安全）

**现状**：
- `cn_commerce_base.py:2924` 与各 server 的 `_sign` 用 `f"{k}{to_sign[k]}"` 直接 `str()` 任意值 → dict/list 入参产生不稳定签名。
- `validate_api_param` 等校验函数（`:166-225`）仅在测试中调用，生产工具 0 调用。

**改动**：
1. 抽取一个 `_canonicalize_sign_value(v)` 工具函数：`bool→"true"/"false"`，`None→""`，`dict/list→json.dumps(sort_keys, separators=(",",":"))`，其余 `str(v)`。`base._sign` 及 7 个 server 的 `_sign` 覆盖统一调用它。
2. 在 `_request` 入口（或新增 `_validate_params`）对字符串型入参调用 `validate_api_param`，可由 `validate_input: bool = True` 配置关闭。
**验收**：新增测试覆盖 dict/list/bool/None 签名稳定性；注入样例（`' OR 1=1`、`../`、`<script>`）被 `_request` 拒绝。

---

## Item 3 — 高级能力接入产品（P1，主体工作）

**设计原则**：按"接入形式"分三层，全部通过 `CommerceMCPBase`（含新 mixin）实现一次，8 个 server 自动继承，**不逐个改 server**。行为变更类一律 **config 开关**控制，默认保持当前行为安全。

### 3A. 请求中间件接入热路径（`_request` 内）
让已实现的 helper 真正在每次请求时运行，由 `MiddlewareConfig` 控制（默认：metrics/tracing 开，dedup/priority 关）：
- `MetricsCollector` — 记录每次请求 latency/成功/失败（部分已有，补全）
- `RequestTracer` — 每请求一个 span
- `RequestDeduplicator` — 去重并发相同请求（默认关，开关 `dedup_enabled`）
- `PriorityScheduler` — `_request(..., priority=...)`，经 scheduler 调度（默认 NORMAL）
- `AlertManager` — 每次 metrics 更新后 `evaluate_alerts`，触发回调
**验收**：集成测试断言一次 `_request` 后 metrics 计数+1、tracer 有 span；dedup 开启时并发相同请求只打一次 HTTP。

### 3B. 跨平台 MCP 工具（base 提供 `register_common_tools(mcp)`，各 server `main()` 调用一行）
所有 server 统一获得：
- `get_metrics` — 返回 MetricsCollector 快照
- `health_check` — 复用现有 `health_check()`
- `export_data(format, data)` — DataExporter 导出 CSV/JSON
- `get_alerts` — AlertManager 当前告警状态
**验收**：任取 2 个 server，列出工具含上述 4 个；调用 `get_metrics` 返回结构正确。

### 3C. Opt-in 基础设施能力（可达 + 集成测试，不强制启用）
- `LoadBalancer` + `FailoverManager` — 当 `endpoints: list[str]` 配置 >1 时 `_request` 经 LB 选端点、失败走 failover
- `WebhookManager` + 签名校验 — 暴露 `verify_webhook(headers, body)` 方法/工具
- `CacheWarmer` — `warmup_cache()` 可调
- `RequestRecorder`/`RequestReplayer` — 由 `MCP_DEBUG_RECORD` 环境变量启用录制
**验收**：每个能力一条集成测试证明"启用后路径走通"。**不主张**针对各平台的业务正确性（属后续工作，文档注明）。

### 3D. 文档对齐
`docs/` 中 webhooks/request-priority/request-replay/load-balancing 等从"虚文档"更新为"已接入，附启用方式与最小示例"。examples/ 增加至少 1 个可运行 `.py`。

---

## Item 4 — Doudian 归一 + shared 真包化（P1，结构）

1. **Doudian 继承 base**：`DouDianClient` 改为继承 `CommerceMCPBase`，删除重复的签名/请求/错误处理（约 300 行），保留抖店特有的签名规则（覆盖 `_sign`/`_canonicalize` 或 BASE_URL）。
2. **shared 成为合法包**：新增 `shared/__init__.py` 导出公共 API + `__version__`；移除 8 个 server 里的 `sys.path.insert` hack，改为标准包导入。
**验收**：8 个 server import 不再操作 `sys.path`；Doudian 测试全绿；`python -c "import shared"` 可行。

---

## Item 5 — 发布模型：shared 独立成包 + 依赖锁定 + 版本单一来源（P1，工程化）

1. **shared 独立包** `mcp-cn-commerce-shared`：新增 `shared/pyproject.toml`（hatchling，包含 cn_commerce_base/cli/dashboard/i18n）。8 个 server 的 `dependencies` 增加 `mcp-cn-commerce-shared>=0.1,<0.2`。
2. **构建后端统一**：jd/doudian 由 setuptools 改 hatchling，与其余 6 个一致。
3. **版本单一来源**：各包 `version` 改为 hatchling `dynamic = ["version"]` 读 `__init__.__version__`；`shared/cli.py:20` 的硬编码版本改为读 `shared.__version__`。
4. **依赖收口**：所有 `mcp>=1.0`→`mcp>=1.0,<2`、`httpx>=0.27`→`httpx>=0.27,<1`；`requires-python` 统一 `>=3.11`；删除未用的 `pyaes` crypto extra。
5. **lock 文件**：生成 `requirements-lock.txt`（pip freeze 形式）纳入版本控制。
6. **publish.yml**：构建并发布 shared + 8 server 全部 dist（仍上传 GitHub Release）。
**验收**：`python -m build` 在 shared 与各 server 目录成功；版本号仅需改 `__init__` 一处。

---

## 执行顺序与依赖

```
Phase 0 (并行, 低风险):  Item 1, Item 2
Phase 1 (结构):          Item 4 (shared 包化 + 去 sys.path + Doudian 归一)
Phase 2 (主体):          Item 3 (base 中间件 + 工具 mixin + opt-in + 文档)
Phase 3 (工程化):        Item 5 (独立包/版本/锁定/构建统一/publish)
Phase 4 (验证):          black + ruff + mypy + pytest 全绿, 修复回归
```

每个 Phase 结束跑 `make test`/`make quality`，红就修到绿再进下一阶段。
</content>
</invoke>
