# Database Snapshots

This directory contains database snapshots for offline access and backup purposes.

## Usage

### Creating Snapshots

To create a snapshot of the current database:

```bash
python scripts/dump_snapshot.py
```

This will create a timestamped JSON file in this directory.

### Loading Snapshots

To load a snapshot:

```bash
python scripts/load_snapshot.py path/to/snapshot.json
```

Use the `--clear` flag to clear existing data before loading:

```bash
python scripts/load_snapshot.py path/to/snapshot.json --clear
```

## Snapshot Format

Snapshots are stored in JSON format with the following structure:

```json
{
  "nodes": [...],
  "relations": [...],
  "metadata": {
    "node_count": 123,
    "relation_count": 456,
    "exported_at": "2024-01-01T12:00:00"
  }
}
```

## Best Practices

1. Create snapshots before major changes
2. Use descriptive names for important snapshots
3. Keep snapshots in version control for reproducibility
4. Test loading snapshots in a clean environment
