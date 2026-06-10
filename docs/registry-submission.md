# Registry / 市场提交操作指南

> 目标：让 mcp-cn-commerce 出现在所有主流 MCP 发现入口。
> 前置条件：**v0.1.3 已发布到 PyPI**（依赖声明修复必须先上线，否则用户从 Registry 装回来还是坏的）。

## 0. 先发 v0.1.2（前置）

```bash
git add pyproject.toml shared/__init__.py CHANGELOG.md server.json README.md docs/registry-submission.md
git commit -m "fix: declare runtime dependencies (mcp, httpx); add MCP registry manifest"
git tag v0.1.2
git push origin main v0.1.2
```

打 tag 后 CI 自动：跑全量质量门 → GitHub Release → 上传 PyPI（需仓库 secret `PYPI_TOKEN` 有效）。
发布后验证：`pip install mcp-cn-commerce==0.1.2 && mcp-cn-commerce --help`（干净 venv）。

---

## 1. MCP 官方 Registry（registry.modelcontextprotocol.io）

清单文件 `server.json` 已就绪（仓库根目录）。所有权验证有两道：

1. **命名空间** `io.github.tonywang-hub` —— 通过 GitHub 登录验证；
2. **PyPI 包归属** —— Registry 会检查 PyPI 上该包 README 中是否含
   `mcp-name: io.github.tonywang-hub/mcp-cn-commerce`（已加在 README 底部，
   **必须随 0.1.2 一起发布到 PyPI 才能通过校验**）。

操作（需要交互式 GitHub 授权，本人执行）：

```bash
brew install mcp-publisher          # 或从 GitHub releases 下载二进制
cd <repo>
mcp-publisher validate              # 校验 server.json 是否符合当前 schema
mcp-publisher login github          # 浏览器 OAuth
mcp-publisher publish
```

> 注意：schema 版本可能更新，以 `mcp-publisher validate` 的输出为准修正 server.json。
> 以后每发一个版本，更新 server.json 的两处 version 并重新 `publish`。

## 2. awesome-mcp-servers（punkpeye/awesome-mcp-servers）

Fork 后在 **Finance / E-commerce 相关分类**追加一行，提 PR：

```markdown
- [TonyWang-hub/mcp-cn-commerce](https://github.com/TonyWang-hub/mcp-cn-commerce) 🐍 ☁️ 🏠 - Read-only merchant business data from 8 Chinese e-commerce platforms (Douyin Shop, JD.com, Taobao, Pinduoduo, Kuaishou, Xiaohongshu, WeChat Store, Ocean Engine ads): orders, products, after-sales, ad reports.
```

中文版列表（如 yzfly/Awesome-MCP-ZH 等）同步提交：

```markdown
- [mcp-cn-commerce](https://github.com/TonyWang-hub/mcp-cn-commerce) - 中国电商商家经营数据 MCP 套件：抖店/京东/淘宝/拼多多/快手/小红书/微信小店/巨量引擎，订单、商品、售后、广告报表，全部只读。
```

## 3. ModelScope 魔搭 MCP 广场（modelscope.cn/mcp）

- 登录魔搭 → MCP 广场 → 「创建 MCP 服务」，填 GitHub 仓库地址，
  服务配置直接用 README 中的 mcpServers JSON 片段。
- 类目选「开发者工具 / 商业服务」；描述用下方统一文案。

## 4. 阿里云百炼 MCP 市场

- 入口：百炼控制台 → MCP 管理 → 申请上架（或通过魔搭收录联动）。
- 需要材料：服务描述、工具清单（README 工具汇总表）、安装方式（PyPI）、
  凭证说明（环境变量表）。主体资质：当前个人可先提交收录，商业化分成需企业主体（见知识库待办）。

## 5. 客户端生态收录

| 渠道 | 动作 |
|---|---|
| Cherry Studio | GitHub 提 issue/PR 到其内置 MCP 列表仓库 + 邮件联系收录 |
| Kimi Work | 官网开发者渠道提交 MCP 服务收录申请 |
| Cline / Continue | 其 marketplace 仓库提 PR |

## 统一推广文案（复制即用）

**中文一句话**：让 AI 当你的电商运营分析师——抖店/京东/淘宝/拼多多等 8 大平台经营数据（订单、售后、广告报表），一句话查，全部只读、本地运行、不经过任何第三方服务器。

**English one-liner**: The first open-source MCP server suite for Chinese e-commerce *merchant operations data* — read-only access to orders, products, after-sales and ad reports across 8 platforms (Douyin Shop, JD.com, Taobao, Pinduoduo, Kuaishou, Xiaohongshu, WeChat Store, Ocean Engine), running locally with your own credentials.

## 提交状态跟踪

| 渠道 | 状态 | 日期 | 备注 |
|---|---|---|---|
| PyPI v0.1.3 | ✅ | 2026-06-10 | 0.1.1/0.1.2 为坏包，建议 yank |
| MCP 官方 Registry | ⬜ | | 需 mcp-publisher login |
| awesome-mcp-servers | ⬜ | | PR |
| Awesome-MCP-ZH | ⬜ | | PR |
| ModelScope MCP 广场 | ⬜ | | 表单 |
| 阿里云百炼 | ⬜ | | 表单/审核 |
| Cherry Studio | ⬜ | | issue + 邮件 |
| Kimi Work | ⬜ | | 表单 |
