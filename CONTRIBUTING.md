# Contributing to mcp-cn-commerce

Thanks for your interest in contributing! 🚀

`mcp-cn-commerce` provides **Model Context Protocol (MCP) servers** for Chinese e-commerce platforms, enabling AI agents to read merchant business data (orders, refunds, ad reports, etc.).

## Ways to Contribute

| Type | Examples |
|------|----------|
| **New Platform** | Add an MCP server for Taobao, Pinduoduo, Xiaohongshu, Kuaishou, WeChat Store |
| **New Tools** | Add more API endpoints for existing platforms (logistics, inventory, promotions) |
| **Bug Fixes** | Fix issues with API calls, signing, pagination, error handling |
| **Documentation** | Improve README, add usage examples, translate docs |
| **Tests** | Add more test coverage, integration tests |

## Development Setup

```bash
# Clone
git clone https://github.com/TonyWang-hub/mcp-cn-commerce.git
cd mcp-cn-commerce

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Option 1: Use Makefile (recommended)
make install    # Install all dependencies
make test       # Run tests

# Option 2: Manual setup
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

## Adding a New Platform Server

1. Create `servers/<platform>/` with this structure:
   ```
   servers/<platform>/
   ├── __init__.py
   ├── server.py
   └── tests/
       └── test_<platform>.py
   ```

2. Extend `CommerceMCPBase` from `shared/cn_commerce_base.py`
3. Set `BASE_URL` and `sign_method`
4. Define tools that call `self._request()` or a platform-specific wrapper

See existing servers (oceanengine, doudian, jd) for reference.

## Commit Conventions

- `feat:` — new platform or tool
- `fix:` — bug fix
- `docs:` — documentation
- `test:` — tests
- `refactor:` — code restructure

## Pull Request Checklist

- [ ] Code follows existing patterns (extends `CommerceMCPBase`)
- [ ] Tests pass (`pytest servers/ -v`)
- [ ] Python 3.11+ compatible
- [ ] Platform added to `docs/platforms.md`
- [ ] README updated with new platform
- [ ] No credentials committed

## Questions?

Open a [Discussion](https://github.com/TonyWang-hub/mcp-cn-commerce/discussions) or start an [Issue](https://github.com/TonyWang-hub/mcp-cn-commerce/issues).
