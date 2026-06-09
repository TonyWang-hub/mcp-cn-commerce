# Data Export

Export e-commerce data to CSV, JSON, or Excel formats with custom field selection, pagination, and nested dict flattening.

## Overview

The `DataExporter` class provides a unified way to export API response data to files or strings. It supports:

- **Three formats**: CSV, JSON, Excel (.xlsx)
- **Custom field selection**: Export only the fields you need
- **Pagination**: Export data in pages for large datasets
- **Nested dict flattening**: Automatically flatten nested structures with dot notation

## Core Types

### `ExportFormat`

Supported export formats:

| Format | Value   | File Extension | Notes |
|--------|---------|----------------|-------|
| CSV    | `"csv"` | `.csv`         | UTF-8 encoding by default |
| JSON   | `"json"`| `.json`        | Pretty-printed with indent 2 |
| Excel  | `"excel"`| `.excel`      | Requires `openpyxl` |

### `ExportConfig`

Configuration for data export:

```python
from shared.cn_commerce_base import ExportConfig, ExportFormat

config = ExportConfig(
    format=ExportFormat.CSV,      # Export format
    fields=["id", "name"],        # Fields to include (None = all)
    filename="orders",            # Output filename (without extension)
    output_dir="./exports",       # Output directory
    page=1,                       # Page number (0 = all data)
    page_size=100,                # Items per page
    flatten_nested=True,          # Flatten nested dicts
    encoding="utf-8",             # Character encoding
)
```

## Usage

### Basic Export

```python
from shared.cn_commerce_base import DataExporter, ExportConfig, ExportFormat

# Sample data from API
data = [
    {"id": 1, "name": "Product A", "price": 99.9},
    {"id": 2, "name": "Product B", "price": 149.9},
]

# Export to CSV
result = DataExporter.export(data, ExportConfig(
    format=ExportFormat.CSV,
    output_dir="./exports",
    filename="products",
))
print(f"Exported {result['record_count']} records to {result['file_path']}")
```

### Custom Field Selection

Export only specific fields:

```python
result = DataExporter.export(data, ExportConfig(
    format=ExportFormat.JSON,
    fields=["id", "name"],  # Only export id and name
    output_dir="./exports",
    filename="product_names",
))
```

### Paginated Export

Export data in pages for large datasets:

```python
# Export page 2 with 50 items per page
result = DataExporter.export(data, ExportConfig(
    format=ExportFormat.CSV,
    page=2,
    page_size=50,
    output_dir="./exports",
    filename="orders_page2",
))

print(f"Page {result['pagination']['page']}/{result['pagination']['total_pages']}")
print(f"Has next: {result['pagination']['has_next']}")
```

### Export Nested Data

Flatten nested dictionaries automatically:

```python
data = [
    {
        "id": 1,
        "name": "Order 1",
        "address": {"city": "Beijing", "district": "Haidian"},
        "items": [{"sku": "A", "qty": 2}],
    }
]

result = DataExporter.export(data, ExportConfig(
    format=ExportFormat.JSON,
    flatten_nested=True,
    output_dir="./exports",
    filename="orders_flat",
))
# Output will have: id, name, address.city, address.district, items
```

### Export to String (In-Memory)

Export without writing to a file:

```python
# JSON string
json_str = DataExporter.export_to_string(data, format=ExportFormat.JSON)

# CSV string with specific fields
csv_str = DataExporter.export_to_string(
    data,
    format=ExportFormat.CSV,
    fields=["id", "name"],
)
```

### Excel Export

Export to Excel format (requires `openpyxl`):

```python
result = DataExporter.export(data, ExportConfig(
    format=ExportFormat.EXCEL,
    output_dir="./exports",
    filename="report",
))
```

Install openpyxl if not available:

```bash
pip install openpyxl
```

## API Reference

### `DataExporter.export(data, config)`

Export data to a file.

**Parameters:**
- `data` (list[dict]): List of data records to export.
- `config` (ExportConfig, optional): Export configuration. Uses CSV defaults if not provided.

**Returns:**
```python
{
    "file_path": str,        # Absolute path to the exported file
    "format": str,           # Export format ("csv", "json", "excel")
    "record_count": int,     # Number of records exported
    "fields": list[str],     # Fields included in the export
    "pagination": {          # Pagination information
        "total": int,        # Total records in dataset
        "page": int,         # Current page (0 = all data)
        "page_size": int,    # Items per page
        "total_pages": int,  # Total number of pages
        "has_next": bool,    # Whether there is a next page
        "has_prev": bool,    # Whether there is a previous page
    }
}
```

### `DataExporter.export_to_string(data, format, fields, flatten_nested)`

Export data to an in-memory string.

**Parameters:**
- `data` (list[dict]): List of data records.
- `format` (ExportFormat): CSV or JSON (Excel not supported for strings).
- `fields` (list[str], optional): Fields to include.
- `flatten_nested` (bool): Whether to flatten nested dicts (default: True).

**Returns:** Exported data as a string.

**Raises:** `ValueError` if Excel format is requested.

## Integration with Batch Operations

Combine with batch operations for full data export workflows:

```python
from shared.cn_commerce_base import (
    CommerceMCPBase,
    BatchRequestItem,
    DataExporter,
    ExportConfig,
    ExportFormat,
)

async def export_all_orders(client: CommerceMCPBase, order_ids: list[str]):
    # Fetch orders in batch
    requests = [
        BatchRequestItem("GET", "/api/orders", params={"id": oid}, request_id=oid)
        for oid in order_ids
    ]
    summary = await client._batch_request(requests, max_concurrency=5)

    # Collect successful results
    orders = [r.data for r in summary.results if r.success and r.data]

    # Export to CSV
    result = DataExporter.export(orders, ExportConfig(
        format=ExportFormat.CSV,
        fields=["order_id", "status", "total_amount"],
        output_dir="./exports",
        filename="orders",
    ))

    return result
```

## Best Practices

1. **Use field selection** - Export only the fields you need to reduce file size and processing time.
2. **Paginate large datasets** - For 10,000+ records, use pagination to avoid memory issues.
3. **Flatten nested data** - Use `flatten_nested=True` for spreadsheet-compatible exports.
4. **Choose the right format** - CSV for spreadsheet import, JSON for programmatic use, Excel for reports.
5. **Handle empty data** - The exporter handles empty datasets gracefully.
