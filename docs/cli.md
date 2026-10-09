# CLI reference

Install all eight platforms from the single root distribution:

```bash
pip install mcp-cn-commerce
# Development checkout, using the verified runtime dependency constraints:
make install
```

## Start one platform per connection

```bash
mcp-cn-commerce start oceanengine
mcp-cn-commerce start weixin_store
# Equivalent standalone console script:
mcp-cn-weixin-store
# From a source checkout:
python -m shared.cli start jd
```

A stdio connection carries one MCP server. Starting two platforms in one CLI
invocation is rejected before any child is launched. For several platforms,
configure separate client entries; each gets independent stdin/stdout and
credentials. All diagnostic logging goes to stderr.

```json
{
  "mcpServers": {
    "jd": {
      "command": "mcp-cn-commerce",
      "args": ["start", "jd"],
      "env": {
        "JD_APP_KEY": "your_app_key",
        "JD_APP_SECRET": "your_app_secret",
        "JD_ACCESS_TOKEN": "your_authorized_shop_token"
      }
    },
    "oceanengine": {
      "command": "mcp-cn-commerce",
      "args": ["start", "oceanengine"],
      "env": {"OCEANENGINE_ACCESS_TOKEN": "your_authorized_token"}
    }
  }
}
```

## Configuration and precedence

```bash
mcp-cn-commerce --config /absolute/path/config.json start
mcp-cn-commerce --config /absolute/path/config.json health --json
```

Without `--config`, the first existing file wins:

1. `./mcp-cn-commerce.json`
2. `~/.config/mcp-cn-commerce/config.json`

Files are not merged. An explicitly missing, malformed, or unsupported
configuration fails visibly. This prevents accidental use of a different
account. Supported fields are `servers`, `env`, `verbose`, and `log_level`.

```json
{
  "servers": ["jd"],
  "env": {
    "JD_APP_KEY": "your_app_key",
    "JD_APP_SECRET": "your_app_secret",
    "JD_ACCESS_TOKEN": "your_authorized_shop_token"
  },
  "verbose": false,
  "log_level": "INFO"
}
```

| Setting | Precedence |
|---|---|
| Platforms | Command arguments, then `servers` from the file; `health` otherwise checks all platforms |
| Credentials/environment | Existing process environment, then `env` file defaults; even an explicitly empty environment variable wins |
| Logging | `--verbose`, then file `verbose: true`, then file `log_level`, then `INFO` |

`start` requires exactly one effective platform. `health` can inspect several.
`env` accepts string values. Secret values are not printed in diagnostics.
Configuration files containing credentials should stay outside version control.

## Local health inspection

```bash
mcp-cn-commerce health
mcp-cn-commerce health jd weixin_store --json
```

`health` checks the actual platform module and required configuration fields.
It makes no platform request and does not validate token validity, scopes,
shop authorization, or network reachability. `ready` means local configuration
is present and the module imports; it does not mean live authorization works.
The JSON fields `protocol_status` and `authorization_status` explicitly remain
`not_checked`. Missing or invalid configuration is listed without exposing values.

| Platform argument | Required environment variables |
|---|---|
| `oceanengine` | `OCEANENGINE_ACCESS_TOKEN`; App Key/Secret are used externally when obtaining the token |
| `doudian` | `DOUDIAN_APP_KEY`, `DOUDIAN_APP_SECRET`, `DOUDIAN_SHOP_ID`, `DOUDIAN_ACCESS_TOKEN` |
| `jd` | `JD_APP_KEY`, `JD_APP_SECRET`, `JD_ACCESS_TOKEN` |
| `taobao` | `TAOBAO_APP_KEY`, `TAOBAO_APP_SECRET`, `TAOBAO_ACCESS_TOKEN` |
| `pinduoduo` | `PINDUODUO_CLIENT_ID`, `PINDUODUO_CLIENT_SECRET`, `PINDUODUO_ACCESS_TOKEN` |
| `kuaishou` | `KUAISHOU_APP_KEY`, `KUAISHOU_APP_SECRET`, `KUAISHOU_SIGN_SECRET`, `KUAISHOU_ACCESS_TOKEN` |
| `xiaohongshu` | `XHS_CLIENT_ID`, `XHS_CLIENT_SECRET`, `XHS_ACCESS_TOKEN` |
| `weixin_store` | Static: `WX_ACCESS_TOKEN`. Managed: `WX_APP_ID` and `WX_APP_SECRET`. Optional `WX_TOKEN_MODE=static` or `managed` |

With no explicit Weixin mode, an existing `WX_ACCESS_TOKEN` selects static mode;
otherwise managed mode is selected. Explicit managed mode needs the app
credentials even if a static token is present.

Servers support MCP initialization, tool discovery and local operational tools
without merchant credentials. A business tool returns a configuration error
before making a network request when required credentials are missing.

## Information commands

```bash
mcp-cn-commerce --version
mcp-cn-commerce info --json
mcp-cn-commerce list
mcp-cn-commerce --verbose health jd
```

`info` reports installed package directories. The legacy JSON key `src_found`
is retained for compatibility and now reflects the actual platform package;
there are no per-platform `src/` installations.

## Docker

```bash
docker build -t mcp-cn-commerce .
docker run --rm -i --env-file .env mcp-cn-commerce mcp-cn-commerce start jd
# Equivalent Compose connection; -T disables the terminal:
docker compose run --rm -T jd
# Tests need no merchant .env file:
docker build --target development -t mcp-cn-commerce-dev .
docker run --rm mcp-cn-commerce-dev make test
```

Do not allocate a TTY for MCP connections. The Compose file requires version 2.24 or newer and treats `.env` as optional.
Each Compose platform service runs
its own stdio process with `tty: false`. The development image contains test
and quality tools; the default runtime image installs only the root package
and its runtime dependencies.

## Installation and release gates

The locked dependency CI installs the root package with
`-c requirements-lock.txt`; a separate job tests the latest versions permitted
by the package's dependency ranges. The distribution smoke test runs from a
neutral directory after installing the wheel and sdist into clean environments.
It launches all eight standalone commands and the CLI commands resolved from
`server.json`, then exercises MCP initialization, tool listing, operational
success, tool errors, and missing-credential business errors. Docker uses the
same stdio protocol test against the built runtime image.

`server.json` specifies the executable package's `start` argument and an explicit
platform choice. Its default is `oceanengine`; each additional platform needs a
separate connection. Conditional credentials for all eight choices are described
in the manifest.

Release order is explicit: quality gates → build and version validation → PyPI
upload → GitHub release → reusable Registry publishing workflow. The Registry
job checks that the exact PyPI version is available before publishing. It does
not rely on a `release:published` event emitted by `GITHUB_TOKEN`. Update
`shared.__version__`, the manifest version and package version together before
creating a new matching `vVERSION` tag. A manual release takes an existing tag
and tests that same ref.
