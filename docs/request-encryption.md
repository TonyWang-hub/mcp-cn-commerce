# Request Encryption & Audit

This document describes the request encryption and audit logging features
added to the `mcp-cn-commerce` shared base.

## Request Encryption

### Supported Algorithms

| Algorithm | Key | Notes |
|---|---|---|
| `none` | - | No encryption (default) |
| `aes_256_cbc` | 64 hex chars (32 bytes) | AES-256 in CBC mode with PKCS7 padding; requires `pyaes` |
| `xor_cipher` | any hex string | XOR with repeating key; **testing only** |

### Configuration

```python
from shared.cn_commerce_base import EncryptionConfig, EncryptionMethod

config = EncryptionConfig(
    method=EncryptionMethod.AES_256_CBC,
    encryption_key="0123456789abcdef" * 4,  # 32 bytes hex
    include_encrypted_header=True,           # sets X-Encrypted header
    header_name="X-Encrypted",               # customisable header name
)
```

Pass `encryption_config` to any `CommerceMCPBase` subclass:

```python
client = MyPlatformClient(
    app_key="...",
    app_secret="...",
    encryption_config=config,
)
```

### How It Works

1. **Encrypt (request)** -- When `method == "POST"` and data is present,
   the JSON body is serialised to bytes, then encrypted. If compression is
   also enabled, encryption is applied **before** compression. The
   `X-Encrypted` header signals to the server that the body is encrypted.

2. **Decrypt (response)** -- If the response carries the `X-Encrypted`
   header, the body is decrypted before JSON parsing.

### Standalone Usage

```python
from shared.cn_commerce_base import RequestEncryptor, EncryptionConfig, EncryptionMethod

enc = RequestEncryptor(EncryptionConfig(
    method=EncryptionMethod.AES_256_CBC,
    encryption_key="0123456789abcdef" * 4,
))

plaintext = b'{"order_id": "12345"}'
ciphertext, headers = enc.encrypt(plaintext)
decrypted = enc.decrypt(ciphertext)
assert decrypted == plaintext
```

### XOR Cipher (Testing)

```python
enc = RequestEncryptor(EncryptionConfig(
    method=EncryptionMethod.XOR_CIPHER,
    encryption_key="deadbeef",
))
encrypted, _ = enc.encrypt(b"hello world")
assert enc.decrypt(encrypted) == b"hello world"
```

### AES-256-CBC Details

- **Mode**: CBC (Cipher Block Chaining)
- **Padding**: PKCS7
- **IV**: 16 bytes, randomly generated per encryption, prepended to ciphertext
- **Key**: 32 bytes (256 bits), passed as 64-char hex string
- **Dependency**: `pyaes` (`pip install pyaes`)

Ciphertext layout: `[IV (16 bytes)][encrypted blocks...]`

### Statistics

```python
stats = client.get_encryption_stats()
# {
#     "method": "aes_256_cbc",
#     "total_encrypted": 42,
#     "total_decrypted": 38,
#     "total_bytes_encrypted": 15360,
#     "total_bytes_decrypted": 12288,
# }
```

---

## Request Audit

### Overview

Every request through `CommerceMCPBase._request()` is automatically logged
to an in-memory audit log. Each entry records:

- Request ID, method, path, platform
- HTTP status code, latency
- Whether the body was encrypted
- Error message (if failed)

### Querying

```python
# Get all errors
errors = client.query_audit(errors_only=True, limit=50)

# Filter by platform and method
entries = client.query_audit(platform="TAOBAO", method="POST", limit=20)

# Filter by path substring
entries = client.query_audit(path="/api/order", limit=100)
```

### Statistics

```python
stats = client.get_audit_stats()
# {
#     "total_entries": 150,
#     "max_entries": 50000,
#     "error_count": 3,
#     "encrypted_count": 42,
#     "platforms": {"TAOBAO": 80, "DOUDIAN": 70},
#     "methods": {"GET": 100, "POST": 50},
# }
```

### Export

```python
# JSON
json_str = client.export_audit_json(limit=100)

# CSV
csv_str = client.export_audit_csv(limit=100)

# File
client.get_audit_log().export_to_file("audit.json", format="json")
client.get_audit_log().export_to_file("audit.csv", format="csv")
```

### Direct AuditLog Access

```python
from shared.cn_commerce_base import AuditLog, AuditEntry

audit = AuditLog(max_entries=10000)
audit.log(AuditEntry(
    method="GET",
    path="/api/products",
    platform="TAOBAO",
    status_code=200,
    latency_ms=45.2,
))
```

### Configuration

The audit log is configured via `audit_max_entries` in `CommerceMCPBase.__init__`:

```python
client = MyPlatformClient(
    app_key="...",
    app_secret="...",
    audit_max_entries=100000,  # default: 50000
)
```

Old entries are automatically evicted when the limit is reached (FIFO).

---

## Security Notes

- Encryption keys are masked in configuration output (`to_dict()`).
- The audit log does **not** store request/response bodies -- only metadata.
- AES-256-CBC uses a fresh random IV for every encryption, preventing
  pattern analysis across identical payloads.
- XOR cipher is provided for testing convenience only and must not be
  used in production.
