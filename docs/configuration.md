# 配置文件

mcp-cn-commerce 支持通过 YAML 或 JSON 配置文件管理各平台的 API 凭证和参数，同时支持环境变量覆盖。

## 目录

- [快速开始](#快速开始)
- [配置文件格式](#配置文件格式)
- [环境变量覆盖](#环境变量覆盖)
- [配置验证](#配置验证)
- [API 参考](#api-参考)

---

## 快速开始

### JSON 配置文件

```json
{
  "oceanengine": {
    "app_key": "your_app_key",
    "app_secret": "your_app_secret",
    "access_token": "your_token"
  },
  "taobao": {
    "app_key": "your_app_key",
    "app_secret": "your_app_secret"
  }
}
```

### YAML 配置文件

```yaml
oceanengine:
  app_key: your_app_key
  app_secret: your_app_secret
  access_token: your_token

taobao:
  app_key: your_app_key
  app_secret: your_app_secret
```

### 加载配置

```python
from cn_commerce_base import ConfigLoader

# 从 JSON 文件加载
loader = ConfigLoader("config.json")

# 从 YAML 文件加载
loader = ConfigLoader("config.yaml")

# 带环境变量前缀
loader = ConfigLoader("config.json", env_prefix="COMMERCE_")

# 读取配置值
app_key = loader.get("oceanengine")["app_key"]

# 使用点号访问嵌套值
db_host = loader.get_nested("database.host", default="localhost")
```

---

## 配置文件格式

### 支持的格式

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| JSON | `.json` | Python 标准库 `json`，无需额外依赖 |
| YAML | `.yaml` / `.yml` | 需要安装 PyYAML：`pip install pyyaml` |

### 嵌套配置

配置文件支持任意深度的嵌套结构：

```json
{
  "database": {
    "host": "localhost",
    "port": 5432,
    "credentials": {
      "user": "admin",
      "password": "secret"
    }
  }
}
```

通过 `get_nested()` 方法访问嵌套值：

```python
loader.get_nested("database.host")           # "localhost"
loader.get_nested("database.port")           # 5432
loader.get_nested("database.credentials.user")  # "admin"
loader.get_nested("missing.key", default="N/A") # "N/A"
```

---

## 环境变量覆盖

环境变量优先级高于配置文件中的值。

### 规则

1. 环境变量名 = `{PREFIX}{KEY}`，全部大写
2. 嵌套键用下划线分隔：`database.host` -> `{PREFIX}DATABASE_HOST`

### 示例

假设配置文件 `config.json`：

```json
{
  "database": {
    "host": "file-host",
    "port": 5432
  }
}
```

通过环境变量覆盖 `database.host`：

```bash
export MYAPP_DATABASE_HOST="production-db.example.com"
```

```python
loader = ConfigLoader("config.json", env_prefix="MYAPP_")
loader.get_nested("database.host")  # "production-db.example.com"
loader.get_nested("database.port")  # 5432 (来自文件)
```

### 无文件模式

可以不提供配置文件，仅通过环境变量配置：

```python
loader = ConfigLoader(env_prefix="COMMERCE_")
loader.get("app_key")  # 读取 COMMERCE_APP_KEY 环境变量
```

---

## 配置验证

### 验证必填字段

```python
from cn_commerce_base import ConfigLoader

loader = ConfigLoader("config.json")

missing = ConfigLoader.validate_required(
    loader.config,
    required_keys=["oceanengine.app_key", "oceanengine.app_secret"]
)

if missing:
    print(f"缺少必填配置: {missing}")
```

### 合并配置

`deep_merge()` 方法可以将多层配置合并，后者覆盖前者：

```python
defaults = {"timeout": 30, "retry": {"max": 3, "delay": 1.0}}
overrides = {"retry": {"max": 5}}

merged = ConfigLoader.deep_merge(defaults, overrides)
# {"timeout": 30, "retry": {"max": 5, "delay": 1.0}}
```

---

## API 参考

### `ConfigLoader(config_path=None, env_prefix="")`

配置加载器主类。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `config_path` | `str \| Path \| None` | 配置文件路径，`None` 表示仅用环境变量 |
| `env_prefix` | `str` | 环境变量前缀（如 `"MYAPP_"`） |

### 方法

| 方法 | 说明 |
|------|------|
| `get(key, default=None)` | 获取顶层配置值，自动检查环境变量 |
| `get_nested(dotted_key, default=None)` | 用点号获取嵌套配置值 |
| `apply_env_overrides(config=None)` | 批量应用环境变量到配置字典 |
| `load_file(path)` | 静态方法，自动识别格式加载文件 |
| `load_json(path)` | 静态方法，加载 JSON 文件 |
| `load_yaml(path)` | 静态方法，加载 YAML 文件 |
| `deep_merge(base, override)` | 静态方法，深度合并两个配置字典 |
| `validate_required(config, required_keys)` | 静态方法，验证必填字段 |

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `config` | `dict` | 已加载的配置字典（只读副本） |
| `env_prefix` | `str` | 环境变量前缀 |
| `config_path` | `Path \| None` | 配置文件路径 |

### 异常

| 异常 | 触发条件 |
|------|----------|
| `FileNotFoundError` | 指定的配置文件不存在 |
| `ValueError` | 不支持的文件扩展名 |
| `ImportError` | 加载 YAML 文件但未安装 PyYAML |
