# Quick Start: Testing Persistent Storage

## 🚀 Quick Test (5 minutes)

### Option 1: Automated Test

Run the automated test script:
```bash
python test_persistence.py
```

This will automatically:
- ✅ Create files
- ✅ Store them on disk
- ✅ Shutdown the system
- ✅ Restart everything
- ✅ Verify files still exist
- ✅ Test downloads after restart

### Option 2: Manual Test

**Step 1: Start the system** (3 terminals)

Terminal 1 - Network Controller:
```bash
python main.py --network
```

Terminal 2 - Node 1:
```bash
python main.py --node --node-id node1
```

Terminal 3 - Node 2:
```bash
python main.py --node --node-id node2
```

**Step 2: Create files** (in Terminal 2 - node1)

```
create hello.txt Hello from persistent storage!
create data.json {"test": "data", "persistent": true}
create readme.md # Cloud Storage with Real Persistence
```

**Step 3: Upload to cloud**

```
upload hello.txt
upload data.json
upload readme.md
```

**Step 4: Verify files**

```
list
cloud_files
status
```

**Step 5: Check disk** (new terminal)

```bash
python verify_disk_storage.py
```

You should see:
```
📁 Storage Directory: storage_data/
--------------------------------------------------
📁 Node Directory: node1/
   📄 metadata.json (XXX bytes)
      Files in metadata: 3
   
   💾 Data Files (3 files):
      • abc123.dat
        Original name: hello.txt
        Size: 32 bytes
      • def456.dat
        Original name: data.json
        Size: 45 bytes
      • ghi789.dat
        Original name: readme.md
        Size: 38 bytes
```

**Step 6: STOP EVERYTHING** (Ctrl+C in all terminals)

```
^C
[Node node1] Shutting down...
[Node node1] Saved metadata for 3 files
[Node node1] Shutdown complete - all files persisted to disk
```

**Step 7: Restart** (same commands as Step 1)

```bash
# Terminal 1
python main.py --network

# Terminal 2
python main.py --node --node-id node1

# Terminal 3
python main.py --node --node-id node2
```

**Step 8: Verify persistence** (in Terminal 2)

```
list
cloud_files
```

**Expected output:**
```
[Node node1] Loaded 3 existing files from disk (115 bytes)
[Node node1]> list
[Node node1] Local files:
  - hello.txt (32 bytes)
  - data.json (45 bytes)
  - readme.md (38 bytes)
```

**Step 9: Download on different node** (in Terminal 3 - node2)

```
download hello.txt
list
```

**Expected output:**
```
[Node node2] Downloading hello.txt from cloud storage...
[Node node2] File hello.txt downloaded successfully from node1 (attempt 1)
[Node node2] Local files:
  - hello.txt (32 bytes)
```

**Step 10: Verify on disk again**

```bash
python verify_disk_storage.py
```

Now you should see files in BOTH node1 and node2 directories!

## 🎯 What to Look For

### ✅ Success Indicators

1. **On startup:**
   ```
   [Node node1] Loaded X existing files from disk (XXX bytes)
   ```

2. **On file creation:**
   ```
   [Node node1] Stored file test.txt to disk (32 bytes)
   ```

3. **On shutdown:**
   ```
   [Node node1] Saved metadata for X files
   [Node node1] Shutdown complete - all files persisted to disk
   ```

4. **Directory structure exists:**
   ```
   storage_data/
   ├── network_registry.json
   ├── node1/
   │   ├── metadata.json
   │   └── *.dat files
   └── node2/
       ├── metadata.json
       └── *.dat files
   ```

5. **Files survive restart:**
   - Stop all programs
   - Restart all programs
   - Files still appear in `list` and `cloud_files`

### ❌ Troubleshooting

**Problem: "No existing files" on restart**
- Check if `storage_data/` directory exists
- Check if `.dat` files are in the directory
- Check if `metadata.json` exists

**Problem: "File not found" when downloading**
- Wait a few seconds for replication
- Check network controller is running
- Check nodes are registered (look for "ACTIVE" message)

**Problem: "Insufficient disk space"**
- Check actual disk space: `df -h` (Linux/Mac) or `dir` (Windows)
- Reduce file sizes or free up disk space

## 🧹 Cleanup

To start fresh:

```bash
# Remove all stored data
rm -rf storage_data/

# Or on Windows PowerShell
Remove-Item -Recurse -Force storage_data
```

## 📊 Verify Everything Works

Run this checklist:

- [ ] Files are created locally
- [ ] Files appear in `list` command
- [ ] Files can be uploaded to cloud
- [ ] Files appear in `cloud_files` command
- [ ] `storage_data/` directory exists
- [ ] `.dat` files exist in node directories
- [ ] `metadata.json` exists
- [ ] `network_registry.json` exists
- [ ] After restart, files still in `list`
- [ ] After restart, files still in `cloud_files`
- [ ] Can download files after restart
- [ ] `verify_disk_storage.py` shows files

If all checkboxes are ✅, persistence is working perfectly!

## 🎓 Next Steps

1. Try creating larger files
2. Test with more nodes
3. Test node failure scenarios
4. Examine the actual `.dat` files
5. Read the full PERSISTENCE_README.md

## 💡 Pro Tips

- Use `verify_disk_storage.py` frequently to see what's on disk
- Check file sizes match between `list` and actual disk
- Try stopping nodes mid-transfer to test recovery
- Examine `metadata.json` to understand the structure
- Look at `network_registry.json` to see replication info

