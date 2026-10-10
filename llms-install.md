# LLM installation guide

> Follow this guide to install and configure `mcp-cn-commerce` for an MCP client.

## What this is

`mcp-cn-commerce` is a read-only MCP server suite for authorized Chinese e-commerce merchant data. Each platform has a separate stdio command. A registered or discoverable tool name does not by itself prove that its operation is currently supported; check the [SDK operation table](docs/sdk-integration.md#catalogue-and-evidence-status).

## Requirements

- Python 3.11 or newer.
- An isolated project virtual environment. Do not install this package into the system Python.
- Platform credentials supplied and approved by the merchant. The agent must not invent credentials or ask for secrets in chat.

## Step 0 — Check Python

```bash
python3 --version
```

If the version is below 3.11, check for `python3.11`, `python3.12` or `python3.13` and use one of those explicitly. Do not continue until a supported interpreter is available.

The commands below use Python 3.12. If you selected another supported interpreter, replace `python3.12` with that interpreter's command.

## Step 1 — Choose a version and install it

As of 2026-10-10, PyPI and the public stable release remain `0.1.5`. The fixed Core `0.1.6` source snapshot used for this engineering acceptance and local artifact preparation is `7e10d2f80a0bafa333c10282edbc7af6f0b2cbb9`; it has merged into public `main`, and its [11 CI checks passed](https://github.com/TonyWang-hub/mcp-cn-commerce/actions/runs/38038270963). A wheel and sdist were prepared and checked locally from this exact source, but have not been published. The `0.1.6` release draft still points to the historical `c32e004` candidate. Merchant live acceptance has not been performed. See the [engineering and local release preparation record](docs/release-readiness.md#2026-10-10-core-main-与本地发布准备). Later status-document commits have separate SHAs and CI records; this entry does not claim that `main` still points to `7e10d2f`.

Choose one of these installs. Keep each in its own directory and virtual environment.

### Public stable PyPI version `0.1.5`

```bash
mkdir -p mcp-cn-commerce-0.1.5
cd mcp-cn-commerce-0.1.5
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install "mcp-cn-commerce==0.1.5"
.venv/bin/mcp-cn-commerce --version
```

### Pinned engineering acceptance and preparation source snapshot `0.1.6`

```bash
git clone https://github.com/TonyWang-hub/mcp-cn-commerce.git
cd mcp-cn-commerce
git checkout --detach 7e10d2f80a0bafa333c10282edbc7af6f0b2cbb9
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements-lock.txt .
.venv/bin/mcp-cn-commerce --version
```

This source snapshot has engineering CI evidence tied to this exact commit. Local wheel/sdist preparation is not publication. It is not a stable PyPI release; later source revisions need their own evidence, and merchant API acceptance remains unverified. Do not use an unqualified `pip install mcp-cn-commerce`: it selects the public stable release, currently `0.1.5`.

The package provides these platform commands:

| Platform | Command | Required environment variables |
|---|---|---|
| 巨量引擎 / 千川 Ocean Engine | `mcp-cn-oceanengine` | `OCEANENGINE_ACCESS_TOKEN` |
| 抖店 Douyin Shop | `mcp-cn-doudian` | `DOUDIAN_APP_KEY`, `DOUDIAN_APP_SECRET`, `DOUDIAN_SHOP_ID`, `DOUDIAN_ACCESS_TOKEN` |
| 京东 JD.com | `mcp-cn-jd` | `JD_APP_KEY`, `JD_APP_SECRET`, `JD_ACCESS_TOKEN` |
| 淘宝 Taobao | `mcp-cn-taobao` | See [platform setup](docs/platforms.md) |
| 拼多多 Pinduoduo | `mcp-cn-pinduoduo` | See [platform setup](docs/platforms.md) |
| 快手 Kuaishou | `mcp-cn-kuaishou` | See [platform setup](docs/platforms.md) |
| 小红书 Xiaohongshu | `mcp-cn-xiaohongshu` | See [platform setup](docs/platforms.md) |
| 微信小店 WeChat Store | `mcp-cn-weixin-store` | See [platform setup](docs/platforms.md) |

## Step 2 — Choose platforms and operations

Ask which platform and data operation the user needs. Configure only those servers. Check each requested operation in the [SDK operation table](docs/sdk-integration.md#catalogue-and-evidence-status); do not infer support from the platform name or MCP tool discovery alone. Follow any explicit unsupported status exposed by the server and do not retry it through a legacy alias.

## Step 3 — Configure credentials locally

The agent must not invent credentials. Ask the user to enter approved values locally in the shell or the MCP client's environment settings. Do not ask them to paste AppSecret, access tokens, authorization codes, buyer information or payment records into chat, an issue or a public configuration file. The required app type and API permission depend on the merchant scenario; see [official access status](docs/official-access-status.md). A token does not imply access to every operation.

Discovery and offline report generation can be checked without merchant credentials. A live operation sends a request to the platform and should only run after the user has selected the platform, operation and authorized account.

## Step 4 — Configure the MCP client

Use the absolute path to the command inside the chosen virtual environment. Activating a shell environment does not update a desktop client's `PATH`. Example for Ocean Engine and Douyin Shop; replace the placeholder paths and enter credentials only in the local client configuration:

```json
{
  "mcpServers": {
    "oceanengine": {
      "command": "/absolute/path/to/mcp-cn-commerce-0.1.5/.venv/bin/mcp-cn-oceanengine",
      "env": {
        "OCEANENGINE_APP_KEY": "<configured locally>",
        "OCEANENGINE_APP_SECRET": "<configured locally>",
        "OCEANENGINE_ACCESS_TOKEN": "<configured locally>"
      }
    },
    "doudian": {
      "command": "/absolute/path/to/mcp-cn-commerce-0.1.5/.venv/bin/mcp-cn-doudian",
      "env": {
        "DOUDIAN_APP_KEY": "<configured locally>",
        "DOUDIAN_APP_SECRET": "<configured locally>",
        "DOUDIAN_SHOP_ID": "<configured locally>",
        "DOUDIAN_ACCESS_TOKEN": "<configured locally>"
      }
    }
  }
}
```

If you installed the pinned source candidate, point `command` to the executable under that checkout's `.venv/bin/` instead. On Windows, use the corresponding `.venv\\Scripts\\` executable path.

## Step 5 — Verify discovery

Restart or reload the MCP client and list the selected server's tools. Compare requested operations with the SDK operation table and any explicit server capability metadata. Discovery is not proof that the platform grants access or that a merchant request has succeeded. Do not make a real API call as an installation check unless the user has approved the account and operation.

## Notes

- The process runs locally. Required authentication is sent to the relevant official platform API, and results return to the configured MCP client.
- Follow the platform's token expiry and revocation behavior. Do not assume tokens are permanent or share one refresh rule across platforms. Set `WX_TOKEN_MODE` explicitly when configuring managed WeChat token renewal.
- Full per-platform authentication details are in [docs/platforms.md](docs/platforms.md).
