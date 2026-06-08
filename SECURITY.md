# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in mcp-cn-commerce, please **do NOT** open a public issue.

Instead, please report it via:

- **GitHub Security Advisory**: [Create a private advisory](https://github.com/TonyWang-hub/mcp-cn-commerce/security/advisories/new)
- **Email**: Please reach out to the maintainer directly

You can expect:

- Acknowledgment of your report within 48 hours
- Regular updates on the progress of a fix
- Credit in the security advisory (unless you prefer to remain anonymous)

## Security Design Principles

This project handles API credentials for Chinese e-commerce platforms. Our security guarantees are:

1. **Credentials never leave your machine** — all API calls are made locally from your MCP client
2. **Read-only by default** — all tools only read data; no write, delete, or modify operations
3. **Open source** — anyone can audit every line of code
4. **No telemetry** — no usage data is collected or transmitted
5. **No third-party servers** — the code communicates directly with platform APIs only

## Best Practices for Users

- Store credentials in environment variables, never hardcode them
- Use `.env` files only in secure, private directories
- Rotate API tokens regularly
- Review the code before running it in production
