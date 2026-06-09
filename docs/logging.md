# Logging Configuration

mcp-cn-commerce provides a flexible logging system with file rotation, sensitive data masking, and structured output.

## Quick Start

```python
from cn_commerce_base import setup_logging, LogRotationConfig

# Basic setup with console output
setup_logging()

# With size-based file rotation (10 MB per file, keep 5 backups)
setup_logging(LogRotationConfig(log_dir="logs", max_bytes=10*1024*1024, backup_count=5))

# With time-based rotation (rotate daily, keep 30 days)
setup_logging(LogRotationConfig(
    log_dir="logs",
    enable_size_rotation=False,
    enable_timed_rotation=True,
    when="midnight",
    timed_backup_count=30,
))

# Both rotations active simultaneously
setup_logging(LogRotationConfig(
    log_dir="logs",
    enable_size_rotation=True,
    max_bytes=5*1024*1024,
    backup_count=3,
    enable_timed_rotation=True,
    when="midnight",
    timed_backup_count=30,
))
```

## LogRotationConfig Parameters

| Parameter             | Type  | Default                  | Description                                   |
| --------------------- | ----- | ------------------------ | --------------------------------------------- |
| `log_dir`             | str   | `"logs"`                 | Directory for log files                       |
| `log_file`            | str   | `"mcp-cn-commerce.log"`  | Base log file name                            |
| `max_bytes`           | int   | `10485760` (10 MB)       | Max file size before rotation                 |
| `backup_count`        | int   | `5`                      | Backup files to keep (size rotation)          |
| `when`                | str   | `"midnight"`             | Timed rotation interval (`midnight`, `h`, `d`)|
| `interval`            | int   | `1`                      | Multiplier for timed rotation interval        |
| `timed_backup_count`  | int   | `30`                     | Backup files to keep (timed rotation)         |
| `enable_size_rotation`| bool  | `True`                   | Enable size-based rotation                    |
| `enable_timed_rotation| bool  | `False`                  | Enable time-based rotation                    |

## Sensitive Data Masking

All log output is automatically filtered by `SensitiveDataFilter`, which masks:

- JWT tokens (`eyJ...`)
- Bearer tokens
- Fields matching `app_key`, `app_secret`, `access_token`, `client_secret`, `refresh_token`, `api_key`, `password`, `token`, `sign`

To disable masking:

```python
setup_logging(sensitive_filter=False)
```

## Auto-Reconnect Logging

The auto-reconnect mechanism logs at these levels:

| Level   | When                                                        |
| ------- | ----------------------------------------------------------- |
| DEBUG   | Client successfully connected                               |
| WARNING | Reconnect attempt failed, will retry                        |
| ERROR   | All reconnect attempts exhausted                            |

## Environment Variables

You can control logging via environment variables:

| Variable              | Description                       | Default  |
| --------------------- | --------------------------------- | -------- |
| `MCP_LOG_LEVEL`       | Logging level (DEBUG/INFO/WARN)   | `INFO`   |
| `MCP_LOG_DIR`         | Log file directory                | `logs`   |
| `MCP_LOG_MAX_BYTES`   | Max log file size in bytes        | `10485760`|
| `MCP_LOG_BACKUP_COUNT`| Number of backup files            | `5`      |

Example:

```bash
export MCP_LOG_LEVEL=DEBUG
export MCP_LOG_DIR=/var/log/mcp-cn-commerce
```

## Integration with MCP Servers

Each platform server inherits logging from the base class. To configure logging at server startup:

```python
import os
from cn_commerce_base import setup_logging, LogRotationConfig

config = LogRotationConfig(
    log_dir=os.environ.get("MCP_LOG_DIR", "logs"),
    max_bytes=int(os.environ.get("MCP_LOG_MAX_BYTES", 10*1024*1024)),
    backup_count=int(os.environ.get("MCP_LOG_BACKUP_COUNT", 5)),
)
setup_logging(config, level=getattr(logging, os.environ.get("MCP_LOG_LEVEL", "INFO")))
```
