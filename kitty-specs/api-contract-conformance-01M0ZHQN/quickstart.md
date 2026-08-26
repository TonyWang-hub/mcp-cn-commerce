# Quickstart：在这个仓库上干活前必读

本文件记录本 mission 期间踩到并已确认的环境与方法论事实。每一条都是实际卡过人的。

## 1. 用哪个解释器 —— 这条卡过全部 5 个实施 agent

**必须用仓内 `.venv/bin/python`。**

```bash
.venv/bin/python -m pytest tests/ servers/ -q
.venv/bin/python -m ruff check . && .venv/bin/python -m black --check .
```

`/opt/homebrew/bin/python3.12` **跑不了这个仓库** —— 它加载 user-site 的旧版 `mcp`（无
`mcp.server.mcpserver`，该模块是 mcp v2 才有的），于是所有 `servers/*` 在 collect 阶段就
ImportError。这与任何代码改动无关，在改动前的 baseline 上同样失败。

`.venv` 由本 mission 期间创建（mcp 2.1.1 + httpx + pytest/black/ruff），已 gitignore。

## 2. 不要在测试里 `importlib.reload` 服务器模块

`reload` 在**同一个 globals 字典**里把模块级 client 换成新对象。各平台测试文件在 import 时
捕获的工具函数是在**调用时**才查那个全局名 —— 于是拿到新对象，而 patch 打在旧对象上，测试
会真的出网（表现为 `40013 invalid appid` 这类平台报错）。

本 mission 期间这一个模式造成全量跑 **70 条失败 / 隔离跑全绿**，且定位过程中一度归因错了文件。
六处 `reload` 全都只是为了拿到**类**、随后用显式参数自建实例，模块全局重建从未被用到，已全部
删除。删完 1750 passed，且全量耗时 52s → 19s。

**需要读模块里的类时**：`import servers.<p>.server as m; m.SomeClass(...)`，不要 reload。

## 3. 活体探测不能作为 endpoint 存在性证据

三处实证：

- 巨量：**已下线的路由仍返回 `40105 access_token无效` 而不是 404**
- 淘宝：`getApiParamList` 对 2018 年就公告下线的 `taobao.items.list.get` **仍返回参数**
- 京东：官方目录对「已下线」与「从未存在」返回**同一个** `API不存在`

唯一可靠判据是「**官方文档清单** + **官方公告语料**」双重比对。各平台的公开文档接口见
mission spec §2.3.1（八个平台全部记录在案，均无需登录）。

拼多多给出了最干净的区分判据：它历史上所有下线都点名到具体接口且公告永久可查，所以
「在全部公告语料中 0 命中 **且** 不在现行清单中」= **从未存在**，而非「下线了」。

## 4. 官方 SDK 里有类 ≠ 接口还活着

- 巨量官方 Java SDK 最新版（1.1.93，2026-08-12）**仍在发布** `ReportAdGetV2Api` 等
  已于 2024-05-06 下线接口的类
- 快手官方 SDK 里有 71 个 `@Deprecated` 类，但多数标的是**旧 SDK 包装类**而非死接口
  （退款列表旧类废弃、新类仍在官方目录中，接口是活的）

判据必须是「全部候选类废弃 **且** 官方目录中缺失」。

## 5. 官方算例要分两步断言

先断言「转录的参数集能逐字节重建官方那个拼接串」，再断言「实现产出期望哈希」。少了第一步，
一个**碰巧哈希对上**的参数集也能通过 —— 那等于把错误实现盖章为正确。

`tests/contract/vectors.py` 里拼多多与京东的算例已本地精确复现；淘宝那条**期望值已知但入参
串未取到**，故记为 `PENDING`、payload 留空，并有专门的守卫测试防止后来者给它编一个输入。

## 6. 多 agent 并发改同一工作树会误裹提交

本 mission 期间 `git commit`（无 pathspec）撞上别人的暂存区，把另一个 WP 的四个文件裹进了
一个无关的 style commit。内容无误但提交信息误导。

**并发时提交必须带 pathspec**：`git commit -m "..." -- <逐个点名文件>`，绝不用
`git add -A` / `git add .`。更稳的做法是给并发 agent 用独立 worktree。

## 7. 代理会挡掉部分平台文档站

本机设了 `ALL_PROXY` / `HTTPS_PROXY` / `HTTP_PROXY`（`127.0.0.1:3213`）。`open.kwaixiaodian.com`
和抖店文档接口经代理会超时/502，需：

```bash
env -u ALL_PROXY -u HTTPS_PROXY -u HTTP_PROXY curl --noproxy '*' <url>
```

注意 `ALL_PROXY` 也要 unset —— 只清 HTTP(S)_PROXY 不够。
