# Persistent File Storage - Implementation Guide

## Overview

The cloud storage simulation now uses **REAL persistent file storage on disk** instead of in-memory dictionaries. Files are stored as actual files on your hard drive and persist across program restarts.

## What Changed

### Before (In-Memory Storage)
- Files stored in Python dictionaries: `self.local_files = {}`
- Files disappeared when program stopped
- No actual disk space consumed
- No persistence between sessions

### After (Persistent Disk Storage)
- Files stored as actual files: `storage_data/{node_id}/{file_id}.dat`
- Metadata stored as JSON: `storage_data/{node_id}/metadata.json`
- Network registry persisted: `storage_data/network_registry.json`
- Files survive program restarts
- Real disk space is consumed

## Directory Structure

```
storage_data/
├── network_registry.json          # Network controller's file registry
├── network_registry.json.backup   # Backup of registry
├── node1/
│   ├── metadata.json              # File metadata for node1
│   ├── metadata.json.backup       # Backup of metadata
│   ├── abc123def456.dat           # Actual file data
│   ├── 789ghi012jkl.dat           # Another file
│   └── ...
├── node2/
│   ├── metadata.json
│   ├── xyz789abc123.dat
│   └── ...
└── ...
```

## Key Features

### 1. Automatic Persistence
- Files are automatically saved to disk when created
- Metadata is saved after every file operation
- Network registry is saved after important state changes
- Backups are created before overwriting metadata

### 2. Startup Recovery
- Nodes automatically load existing files on startup
- File index and metadata are rebuilt from disk
- Storage usage is recalculated from actual file sizes
- Network controller loads file registry from disk

### 3. Data Integrity
- Files are flushed and synced to disk (fsync)
- Checksums are verified on transfer
- Metadata backups prevent data loss
- Actual disk space is checked before writing

### 4. Real Disk Usage
- Storage capacity checks against actual disk space
- File sizes are measured from real files
- Storage utilization reflects actual disk usage

## Testing Persistence

### Method 1: Automated Test Script

Run the comprehensive test:
```bash
python test_persistence.py
```

This will:
1. Create files and store them on disk
2. Shutdown the system
3. Restart the system
4. Verify files still exist
5. Test downloading files after restart

### Method 2: Manual Testing

**Step 1: Start the system**
```bash
# Terminal 1: Start network controller
python main.py --network

# Terminal 2: Start node1
python main.py --node --node-id node1

# Terminal 3: Start node2
python main.py --node --node-id node2
```

**Step 2: Create and upload files**
```
[Node node1]> create test.txt Hello World from persistent storage!
[Node node1]> upload test.txt
[Node node1]> list
[Node node1]> cloud_files
```

**Step 3: Verify files on disk**
```bash
# In a new terminal
python verify_disk_storage.py
```

You should see:
- `storage_data/node1/` directory created
- `.dat` files containing your data
- `metadata.json` with file information
- `network_registry.json` with network state

**Step 4: Stop all programs**
- Press Ctrl+C in all terminals
- Or type `quit` in node terminals

**Step 5: Restart the system**
```bash
# Restart network and nodes (same commands as Step 1)
python main.py --network
python main.py --node --node-id node1
python main.py --node --node-id node2
```

**Step 6: Verify files still exist**
```
[Node node1]> list
[Node node1]> cloud_files
```

Your files should still be there! You can also download them:
```
[Node node2]> download test.txt
```

### Method 3: Verify Disk Storage

Check what's actually on disk:
```bash
python verify_disk_storage.py
```

This shows:
- All node directories
- All `.dat` files with sizes
- Metadata information
- Total storage used

To view a specific file's content:
```bash
python verify_disk_storage.py node1 <file_id>
```

## Implementation Details

### Storage Virtual Node Changes

**New Attributes:**
- `self.storage_dir` - Directory for this node's files
- `self.file_index` - Maps file_id to file_path (replaces local_files dict)

**New Methods:**
- `_load_existing_files()` - Load files from disk on startup
- `_load_metadata()` - Read metadata.json
- `_save_metadata()` - Write metadata.json with backup
- `_load_file_from_disk(file_id)` - Read file data from disk

**Modified Methods:**
- `_store_file_to_disk()` - Now actually writes to disk with fsync
- `create_file()` - Stores to disk, checks disk space
- `upload_file()` - Loads from disk instead of memory
- `download_file()` - Saves to disk after download
- `list_local_files()` - Verifies files exist on disk
- `get_storage_utilization()` - Calculates from actual file sizes
- `shutdown()` - Saves metadata before exit

### Network Controller Changes

**New Attributes:**
- `self.registry_dir` - Directory for network registry

**New Methods:**
- `_load_registry()` - Load file registry from disk on startup
- `_save_registry()` - Save file registry to disk with backup

**Modified Methods:**
- `_handle_file_upload()` - Saves registry after adding file
- `_handle_upload_complete()` - Saves registry after status change
- `_handle_node_failure()` - Saves registry after handling failure
- `stop()` - Saves registry before shutdown

## File Format

### Data Files (.dat)
- Binary format
- Contains raw file data
- Named with file_id: `{file_id}.dat`

### Metadata (metadata.json)
```json
{
  "abc123def456": {
    "file_name": "test.txt",
    "file_size": 1234,
    "checksum": "5d41402abc4b2a76b9719d911017c592",
    "upload_time": 1234567890.123,
    "file_id": "abc123def456",
    "node_id": "node1"
  }
}
```

### Network Registry (network_registry.json)
```json
{
  "file_registry": {
    "abc123def456": {
      "file_id": "abc123def456",
      "file_name": "test.txt",
      "file_size": 1234,
      "primary_nodes": ["node1"],
      "replica_nodes": ["node2"],
      "status": "available",
      "upload_time": 1234567890.123,
      "checksum": "5d41402abc4b2a76b9719d911017c592",
      "replication_factor": 2,
      "target_replicas": 2
    }
  },
  "node_files": {
    "node1": ["abc123def456"],
    "node2": ["abc123def456"]
  }
}
```

## Benefits

1. **True Persistence** - Files survive crashes and restarts
2. **Real Storage** - Actual disk space is used and tracked
3. **Data Recovery** - Files can be recovered after failures
4. **Realistic Simulation** - Behaves like real distributed storage
5. **Debugging** - Can inspect actual files on disk
6. **Testing** - Can verify data integrity manually

## Cleanup

To remove all stored data:
```bash
# Remove all storage data
rm -rf storage_data/

# Or on Windows
rmdir /s storage_data
```

## Notes

- Files are stored in binary format for efficiency
- Metadata is JSON for human readability
- Backups prevent data loss during updates
- fsync ensures data is written to disk
- File paths are relative to working directory
- Storage directory is created automatically

