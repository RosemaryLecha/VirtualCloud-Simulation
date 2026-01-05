# Persistent Storage Architecture

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Cloud Storage Simulation                     │
│                    WITH PERSISTENT STORAGE                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    Network Controller                            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  In-Memory State:                                          │ │
│  │  • file_registry (FileRecord objects)                      │ │
│  │  • node_files (node -> file_id mapping)                    │ │
│  │  • active nodes                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            ↕                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Persistent Storage:                                       │ │
│  │  📁 storage_data/network_registry.json                     │ │
│  │     • File registry (all files in system)                  │ │
│  │     • Node-file mappings                                   │ │
│  │     • Replication status                                   │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                            ↕ gRPC/Socket
┌─────────────────────────────────────────────────────────────────┐
│                    Storage Virtual Nodes                         │
│                                                                  │
│  ┌──────────────────────┐      ┌──────────────────────┐        │
│  │      Node 1          │      │      Node 2          │        │
│  │  ┌────────────────┐  │      │  ┌────────────────┐  │        │
│  │  │ In-Memory:     │  │      │  │ In-Memory:     │  │        │
│  │  │ • file_index   │  │      │  │ • file_index   │  │        │
│  │  │ • file_metadata│  │      │  │ • file_metadata│  │        │
│  │  │ • metrics      │  │      │  │ • metrics      │  │        │
│  │  └────────────────┘  │      │  └────────────────┘  │        │
│  │         ↕             │      │         ↕             │        │
│  │  ┌────────────────┐  │      │  ┌────────────────┐  │        │
│  │  │ Disk Storage:  │  │      │  │ Disk Storage:  │  │        │
│  │  │ 📁 node1/      │  │      │  │ 📁 node2/      │  │        │
│  │  │  metadata.json │  │      │  │  metadata.json │  │        │
│  │  │  abc123.dat    │  │      │  │  abc123.dat    │  │        │
│  │  │  def456.dat    │  │      │  │  xyz789.dat    │  │        │
│  │  └────────────────┘  │      │  └────────────────┘  │        │
│  └──────────────────────┘      └──────────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow: File Creation

```
1. User Command
   create test.txt "Hello World"
        ↓
2. StorageVirtualNode.create_file()
   • Generate file_id (MD5 hash)
   • Create metadata
   • Check storage capacity
   • Check disk space
        ↓
3. _store_file_to_disk()
   • Write to: storage_data/node1/{file_id}.dat
   • Update file_index
   • Update file_metadata
        ↓
4. _save_metadata()
   • Backup old metadata.json
   • Write new metadata.json
   • fsync to disk
        ↓
5. File Persisted ✅
   📁 storage_data/node1/abc123.dat (12 bytes)
   📄 storage_data/node1/metadata.json (updated)
```

## Data Flow: File Upload & Replication

```
1. User Command
   upload test.txt
        ↓
2. StorageVirtualNode.upload_file()
   • Find file in metadata
   • Load file from disk: _load_file_from_disk()
        ↓
3. Network Controller
   • Receive upload request
   • Select primary + replica nodes
   • Create FileRecord
   • Add to file_registry
        ↓
4. _save_registry()
   • Backup network_registry.json
   • Write updated registry
   • fsync to disk
        ↓
5. Trigger Replication
   • Send file to replica nodes
        ↓
6. Replica Nodes
   • Receive file data
   • _store_file_to_disk()
   • _save_metadata()
        ↓
7. File Replicated ✅
   📁 storage_data/node1/abc123.dat
   📁 storage_data/node2/abc123.dat (replica)
   📄 storage_data/network_registry.json (updated)
```

## Data Flow: System Restart

```
1. System Shutdown
   • Node.shutdown() → _save_metadata()
   • Network.stop() → _save_registry()
   • All data flushed to disk
        ↓
2. System Restart
   • Network Controller starts
        ↓
3. Network._load_registry()
   • Read network_registry.json
   • Reconstruct file_registry
   • Restore node_files mapping
        ↓
4. Storage Nodes start
        ↓
5. Node._load_existing_files()
   • Read metadata.json
   • Scan for .dat files
   • Rebuild file_index
   • Calculate used_storage
        ↓
6. System Ready ✅
   • All files available
   • Replication info restored
   • Can download/upload immediately
```

## File Lifecycle

```
┌─────────────┐
│   CREATE    │  User creates file
└──────┬──────┘
       ↓
┌─────────────┐
│ STORE DISK  │  Write to {file_id}.dat
└──────┬──────┘  Update metadata.json
       ↓
┌─────────────┐
│   UPLOAD    │  Send to network controller
└──────┬──────┘
       ↓
┌─────────────┐
│  REPLICATE  │  Copy to replica nodes
└──────┬──────┘  Each node stores to disk
       ↓
┌─────────────┐
│  AVAILABLE  │  File accessible from any node
└──────┬──────┘  Survives restarts
       ↓
┌─────────────┐
│  DOWNLOAD   │  Load from disk
└──────┬──────┘  Transfer to requesting node
       ↓
┌─────────────┐
│   PERSIST   │  Exists across sessions
└─────────────┘  Real file on disk
```

## Storage Hierarchy

```
Physical Disk
    ↓
storage_data/                          ← Root directory
    ├── network_registry.json          ← Network state
    ├── network_registry.json.backup   ← Safety backup
    │
    ├── node1/                         ← Node directory
    │   ├── metadata.json              ← File metadata
    │   ├── metadata.json.backup       ← Safety backup
    │   ├── abc123def456.dat           ← File data (binary)
    │   ├── 789ghi012jkl.dat           ← File data (binary)
    │   └── ...
    │
    ├── node2/                         ← Another node
    │   ├── metadata.json
    │   ├── abc123def456.dat           ← Replica of node1's file
    │   └── ...
    │
    └── node3/
        └── ...
```

## Memory vs Disk

### Before (In-Memory)
```
Python Process Memory
┌─────────────────────┐
│ self.local_files = {│
│   "abc123": b"data",│  ← Lost on shutdown
│   "def456": b"more" │
│ }                   │
└─────────────────────┘
```

### After (Persistent)
```
Python Process Memory          Physical Disk
┌─────────────────────┐       ┌──────────────────────┐
│ self.file_index = { │       │ abc123.dat           │
│   "abc123": "path1",│──────→│   [binary data]      │
│   "def456": "path2" │       │                      │
│ }                   │       │ def456.dat           │
│                     │       │   [binary data]      │
│ (paths only)        │       │                      │
└─────────────────────┘       │ (actual files)       │
                              └──────────────────────┘
                                     ↓
                              Survives restart ✅
```

## Consistency Guarantees

```
Write Operation
    ↓
┌─────────────────┐
│ Write to disk   │  open(path, 'wb')
└────────┬────────┘
         ↓
┌─────────────────┐
│ Flush buffer    │  f.flush()
└────────┬────────┘
         ↓
┌─────────────────┐
│ Sync to disk    │  os.fsync(f.fileno())
└────────┬────────┘
         ↓
┌─────────────────┐
│ Data persisted  │  ✅ Safe from crashes
└─────────────────┘
```

## Backup Strategy

```
Before Update:
┌──────────────────┐
│ metadata.json    │  Existing file
└──────────────────┘
         ↓
┌──────────────────┐
│ Copy to backup   │  metadata.json.backup
└──────────────────┘
         ↓
┌──────────────────┐
│ Write new data   │  metadata.json (new)
└──────────────────┘
         ↓
If write fails:
  → Restore from backup ✅
If write succeeds:
  → Keep backup for safety ✅
```

## Key Design Decisions

1. **Binary .dat files** - Efficient storage, any data type
2. **JSON metadata** - Human-readable, easy to debug
3. **Separate index** - Fast lookups without loading files
4. **fsync on writes** - Durability guarantee
5. **Backup before update** - Safety against corruption
6. **Load on startup** - Automatic recovery
7. **Save on changes** - Always consistent
8. **Per-node directories** - Isolation and organization

## Performance Characteristics

- **Write**: O(1) + disk I/O + fsync
- **Read**: O(1) + disk I/O
- **List**: O(n) metadata only (no file reads)
- **Startup**: O(n) scan directory + read metadata
- **Shutdown**: O(1) save metadata

Where n = number of files

