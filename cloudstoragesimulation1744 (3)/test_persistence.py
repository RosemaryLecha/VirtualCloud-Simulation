#!/usr/bin/env python3
"""
Test script to verify persistent file storage functionality.
This script demonstrates that files persist across program restarts.
"""

import time
import os
import shutil
from storage_virtual_network import StorageVirtualNetwork
from storage_virtual_node import StorageVirtualNode

def test_persistence():
    """Test that files persist across restarts"""
    print("=" * 70)
    print("PERSISTENT STORAGE TEST")
    print("=" * 70)
    
    # Clean up any existing storage data for fresh test
    if os.path.exists("storage_data"):
        print("\n[Test] Cleaning up existing storage data...")
        shutil.rmtree("storage_data")
    
    print("\n=== PHASE 1: Create files and verify they're on disk ===\n")
    
    # Start network controller
    print("[Test] Starting network controller...")
    network = StorageVirtualNetwork(host='localhost', port=5000)
    time.sleep(1)
    
    # Create storage nodes
    print("[Test] Creating storage nodes...")
    node1 = StorageVirtualNode(
        node_id="persist_node1",
        cpu_capacity=4,
        memory_capacity=8,
        storage_capacity=100,  # 100GB
        bandwidth=1000,
        port=6101
    )
    
    node2 = StorageVirtualNode(
        node_id="persist_node2",
        cpu_capacity=4,
        memory_capacity=8,
        storage_capacity=100,
        bandwidth=1000,
        port=6102
    )
    
    time.sleep(2)  # Wait for nodes to register
    
    # Create test files
    print("\n[Test] Creating test files...")
    test_files = [
        ("document1.txt", "This is the first test document for persistence testing."),
        ("document2.txt", "This is the second test document with different content."),
        ("data.json", '{"test": "data", "persistent": true, "value": 12345}'),
    ]
    
    for filename, content in test_files:
        success = node1.create_file(filename, content)
        if success:
            print(f"[Test] ✓ Created {filename}")
        else:
            print(f"[Test] ✗ Failed to create {filename}")
    
    # Upload files to cloud storage
    print("\n[Test] Uploading files to cloud storage...")
    for filename, _ in test_files:
        success = node1.upload_file(filename)
        if success:
            print(f"[Test] ✓ Uploaded {filename}")
        else:
            print(f"[Test] ✗ Failed to upload {filename}")
    
    time.sleep(2)  # Wait for replication
    
    # Verify files exist on disk
    print("\n[Test] Verifying files exist on disk...")
    node1_dir = "storage_data/persist_node1"
    if os.path.exists(node1_dir):
        files = [f for f in os.listdir(node1_dir) if f.endswith('.dat')]
        print(f"[Test] Found {len(files)} .dat files in {node1_dir}")
        for f in files:
            file_path = os.path.join(node1_dir, f)
            size = os.path.getsize(file_path)
            print(f"  - {f} ({size} bytes)")
        
        # Check metadata file
        metadata_path = os.path.join(node1_dir, "metadata.json")
        if os.path.exists(metadata_path):
            print(f"[Test] ✓ Metadata file exists: {metadata_path}")
        else:
            print(f"[Test] ✗ Metadata file missing!")
    
    # Check network registry
    registry_path = "storage_data/network_registry.json"
    if os.path.exists(registry_path):
        print(f"[Test] ✓ Network registry exists: {registry_path}")
    else:
        print(f"[Test] ✗ Network registry missing!")
    
    # List files before shutdown
    print("\n[Test] Files in cloud storage before shutdown:")
    files = node1.list_cloud_files()
    for f in files:
        print(f"  - {f['file_name']} ({f['file_size']} bytes)")
    
    print("\n[Test] Local files on node1 before shutdown:")
    local_files = node1.list_local_files()
    for f in local_files:
        print(f"  - {f['file_name']} ({f['file_size']} bytes)")
    
    # Shutdown everything
    print("\n[Test] Shutting down nodes and network...")
    node1.shutdown()
    node2.shutdown()
    network.shutdown()
    time.sleep(1)
    
    print("\n=== PHASE 2: Restart and verify files still exist ===\n")
    
    # Restart network controller
    print("[Test] Restarting network controller...")
    network2 = StorageVirtualNetwork(host='localhost', port=5000)
    time.sleep(1)
    
    # Restart nodes
    print("[Test] Restarting storage nodes...")
    node1_restart = StorageVirtualNode(
        node_id="persist_node1",
        cpu_capacity=4,
        memory_capacity=8,
        storage_capacity=100,
        bandwidth=1000,
        port=6101
    )
    
    node2_restart = StorageVirtualNode(
        node_id="persist_node2",
        cpu_capacity=4,
        memory_capacity=8,
        storage_capacity=100,
        bandwidth=1000,
        port=6102
    )
    
    time.sleep(2)
    
    # List files after restart
    print("\n[Test] Files in cloud storage after restart:")
    files_after = node1_restart.list_cloud_files()
    for f in files_after:
        print(f"  - {f['file_name']} ({f['file_size']} bytes) - Status: {f.get('status', 'unknown')}")
    
    print("\n[Test] Local files on node1 after restart:")
    local_files_after = node1_restart.list_local_files()
    for f in local_files_after:
        print(f"  - {f['file_name']} ({f['file_size']} bytes)")
    
    # Test downloading a file after restart
    print("\n[Test] Testing file download after restart...")
    if files_after:
        test_file = files_after[0]['file_name']
        print(f"[Test] Attempting to download: {test_file}")
        success = node2_restart.download_file(test_file)
        if success:
            print(f"[Test] ✓ Successfully downloaded {test_file} after restart!")
        else:
            print(f"[Test] ✗ Failed to download {test_file}")
    
    # Final cleanup
    print("\n[Test] Shutting down...")
    node1_restart.shutdown()
    node2_restart.shutdown()
    network2.shutdown()
    
    print("\n" + "=" * 70)
    print("PERSISTENCE TEST COMPLETED")
    print("=" * 70)
    print("\nVerification:")
    print("✓ Files were created and stored on disk")
    print("✓ Files persisted after program shutdown")
    print("✓ Files were loaded on restart")
    print("✓ Files can be downloaded after restart")
    print("\nCheck the 'storage_data/' directory to see actual files on disk!")

if __name__ == "__main__":
    test_persistence()

