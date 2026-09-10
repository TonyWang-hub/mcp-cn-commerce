# 修复与实际验收记录

日期：2026-09-10。工程验收通过；真实商家联调尚未执行，京东/拼多多/快手的当前协议仍有未闭合项。本记录不使用前一环境离线检查作为本轮通过证据。

## 分支与补丁接收

- 修复分支：`codex/repair-acceptance-20260910`。
- [草稿 PR #115](https://github.com/TonyWang-hub/mcp-cn-commerce/pull/115)，未合并、未发布。
- 最新主线基线：`3ec0ee0f6d44f21dc416f148540867e7d7e12463`，本次实际 fetch 后与交接基线一致，rebase 无新增冲突。
- 原工作目录 `/Users/tony/Documents/work/ai/cloud_work/项目/agent-harness/mcp-cn-commerce` 的分支和未跟踪 `lark_auth_qr.png` 保持原样；独立 worktree：`/private/tmp/mcp-cn-commerce-repair-20260910`。
- 交接 patch SHA-256 实测为 `a4ad9d9b0c41509aba84bbc70070b42535f8c8984cc17aeb8cb1cd42eda0890d`，与交接说明一致；`git am` 接收54个文件变更。原补丁作者保留，提交者及新增提交使用仓库级 TonyWang-hub noreply 身份。

| 提交 | 内容 |
|---|---|
| `b4fe5c8` | 接收交接修复补丁，父提交为上述主线基线 |
| `cf22c0d` | 修正依赖锁、TOP 协议、微信游标与状态、MCP 配置错误、类型和测试合同 |
| `ea946dd85786e7ae5eedb072bec9b14b1254390c` | 修复默认 HTTPX 日志凭证泄露、小红书状态与退款完整性；本轮最终代码验收对象 |

此后的文档提交仅补充官方 token 证据及本验收记录，不更改上述已验证代码。

## 实际环境与结果

本机 macOS arm64、Python 3.12.3。所有依赖安装在隔离 venv，未修改全局工具链。锁定 MCP 2.1.1、HTTPX 0.28.1、Pydantic 2.13.5/core 2.46.5；最新支持依赖环境实际解析为 MCP 2.2.0。未安装或启动本机 Docker；Docker 在 GitHub Linux runner 实际执行。

| 实际命令/场景 | 结果 | 日志或证据 |
|---|---|---|
| `python -m pip install -c requirements-lock.txt -e ".[dev]"` | 成功；首次失败发现 core 2.48.0 与 Pydantic 要求2.46.5冲突，已修复 | `/private/tmp/mcp-repair-install.log`、`/private/tmp/mcp-repair-install-fixed.log` |
| `python scripts/check_tool_metadata.py` | 8平台、155注册入口、每平台5公共工具一致 | 包含4个明确不支持的小红书入口，不等于155个已线上联调工具 |
| `python -m pytest servers/ tests/ -q --tb=short --junitxml=...` | **1586 passed，0 failed，0 skipped；另20 subtests passed** | `/private/tmp/mcp-repair-final.log`、`/private/tmp/mcp-repair-final.xml` |
| `python -m black --check .` | 通过 | `/private/tmp/mcp-final-black.log` |
| `python -m ruff check .` | 通过 | `/private/tmp/mcp-final-ruff.log` |
| `python -m mypy servers/ shared/ tests/ --config-file=pyproject.toml` | 52个源文件无问题（使用仓库原有配置） | `/private/tmp/mcp-final-mypy.log` |
| `python -m pylint --rcfile=pyproject.toml --disable=import-error servers/ shared/` | 10.00/10，退出0 | `/private/tmp/mcp-final-pylint.log` |
| `python -m bandit -c pyproject.toml -r servers/ shared/` | 0发现，未新增 nosec 或关闭规则 | `/private/tmp/mcp-final-bandit.log` |
| `python -m build`、`python -m twine check dist/*` | wheel与sdist构建、元数据检查均通过 | `/private/tmp/mcp-final-build.log`、`/private/tmp/mcp-final-twine.log` |
| 干净 venv：锁定依赖安装 wheel + 仓库外 smoke | 24场景通过，MCP 2.1.1 | `/private/tmp/mcp-final-wheel-locked.log` |
| 干净 venv：最新支持依赖安装 wheel + 仓库外 smoke | 24场景通过，MCP 2.2.0 | `/private/tmp/mcp-final-wheel-latest.log` |
| 干净 venv：锁定依赖安装 sdist + 仓库外 smoke | 24场景通过，MCP 2.1.1 | `/private/tmp/mcp-final-sdist-locked.log` |
| `python examples/daily-report/generate.py` | 与提交内 example-data.json 完全相同；合成示例4899分、2单 | `/private/tmp/mcp-daily-report.json` |
| `git diff --check` | 通过 | 本地执行 |

三个安装环境均执行真实依赖解析安装，未用 `--no-deps` 代替安装验收。每个环境从 `/private/tmp` 运行 `scripts/smoke_install.py` 绝对路径，确认模块来自 site-packages。每平台验证 Registry CLI、独立命令、无凭证模式；包括 initialize、tools/list、成功导出、错误工具调用、错误后继续请求、正常退出，共72组实际 stdio 场景。服务端加载真实 MCP SDK，未访问商家 API。

初次完整测试实际为1570通过/7失败/1跳过。失败包括过期的配置/日志测试合同及淘宝错误传播；初次安装冒烟又发现 SDK 2 隐藏普通配置异常，已使用 SDK ToolError 提供安全的缺配置提示。openpyxl 已加入 dev 并实际安装，最终 Excel 导出测试不再跳过。独立复审复现的日志与退款问题均先建立失败回归、再修复，复审已在新进程核验真实 SDK 默认 stderr 脱敏。

## 远程验收

最终代码提交 `ea946dd` 的 [Test run 34463196026](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34463196026) **10个 job 全部 success**：

- Python 3.11、3.12、3.13完整测试矩阵。
- 锁定依赖 wheel/sdist 安装、最新支持依赖 wheel 安装及真实 SDK stdio。
- Docker runtime/development target 实际构建；development 镜像 `make test`；runtime 镜像 `smoke_install.py --docker mcp-cn-commerce:smoke`。
- 官方 `mcp-publisher v1.8.1 validate` 实际 Registry manifest 校验。
- lint、typecheck、code-quality。

[Docker job](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/34463196026) 可在该 run 内查步骤完整输出。远程日志下载到 `/private/tmp/mcp-ci-code.log`，job状态 `/private/tmp/mcp-ci-code.json`，三版本 JUnit artifact 在 `/private/tmp/mcp-ci-reports/`。本机 `/private/tmp` 日志可能被系统清理；远程 run 和 artifact 为可共享证据。

## 官方合同与剩余外部条件

官方来源、版本/更新时间及本次读取结果详见 [official-access-status.md](official-access-status.md)。淘宝官方固定签名向量、微信订单游标/秒单位、小红书真实状态枚举均有新增合成回归。不能把 HTTPX MockTransport、MCP 握手或官网入口当作商家 API 已成功。

| 平台 | 需准备的获批账号/环境变量 | 仍需具体核验 |
|---|---|---|
| 巨量 | 广告应用及对应广告主/千川权限；`OCEANENGINE_ACCESS_TOKEN` | 只读广告主信息及报表；授权账户范围、报表口径 |
| 抖店 | 获批自用或工具型应用及店铺授权；`DOUDIAN_APP_KEY`、`DOUDIAN_APP_SECRET`、`DOUDIAN_ACCESS_TOKEN`、`DOUDIAN_SHOP_ID` | 订单/退款两页与详情、实际金额和付款/退款完成时间、token所属店铺 |
| 淘宝 | TOP卖家订单权限及卖家授权；`TAOBAO_APP_KEY`、`TAOBAO_APP_SECRET`、`TAOBAO_ACCESS_TOKEN`（映射session） | 卖家订单列表/详情、按创建时间和修改时间补页；元单位与后台核对、实际session生命周期 |
| 微信小店 | 本店开发者AppID/Secret及IP白名单；`WX_APP_ID`、`WX_APP_SECRET`、`WX_TOKEN_MODE=managed`；或有效`WX_ACCESS_TOKEN`、static模式 | 订单next_key/has_more两页、order_id_list逐单详情；服务商需权限集131及对应店铺authorizer_access_token，当前包不管理服务商刷新 |
| 小红书 | 获批自研/ISV商家应用及关联店铺；`XHS_CLIENT_ID`、`XHS_CLIENT_SECRET`、`XHS_ACCESS_TOKEN` | 9个已映射业务方法逐项只读调用；售后列表无实际退款完成时间/金额，须取得对应证据再发布完整日报。4个Unsupported入口保持不支持 |
| 京东 | JOS零售订单应用与商家授权；`JD_APP_KEY`、`JD_APP_SECRET`、`JD_ACCESS_TOKEN` | **协议未闭合**：旧官方MD5/360buy_param_json与当前HMAC-MD5/裸JSON冲突，需当前官方SDK、网关版本、签名向量及订单权限后修复，不可称已生产可用 |
| 拼多多 | 商家经营/ERP应用和店铺授权；`PINDUODUO_CLIENT_ID`、`PINDUODUO_CLIENT_SECRET`、`PINDUODUO_ACCESS_TOKEN` | **协议未闭合**：本次仅拿到JS壳，当前网关/商家方法、timestamp单位、时间窗、分页和签名向量待官方正文确认；多多进宝授权不等于商家订单权限 |
| 快手 | 商家自用或第三方电商应用及授权；`KUAISHOU_APP_KEY`、`KUAISHOU_APP_SECRET`、`KUAISHOU_SIGN_SECRET`、`KUAISHOU_ACCESS_TOKEN` | **协议未闭合**：当前网关/参数名/签名算法及订单schema待官方SDK或控制台文档；保留独立签名密钥不代表算法已获证实 |

当前进程检查未发现以上任何商家环境变量，独立 worktree 无 `.env`，未搜寻其他项目或凭证存储。凭证应在本地环境或 MCP 客户端中配置，不通过聊天传递。

只读联调步骤：选定获批应用和单一店铺 → 配置对应环境变量 → `mcp-cn-commerce start <platform>` → 查询一个受支持的小时间窗口和至少两页 → 保存脱敏响应结构、实际时间/金额单位、游标终止条件 → 逐单详情与后台核对。日报必须另证付款日与真实退款完成日覆盖；只按创建/更新时间查询不能直接声明 coverage=true。京东/拼多多/快手先完成上述官方合同问题，再执行平台业务请求。
