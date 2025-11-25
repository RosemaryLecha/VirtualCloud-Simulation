#!/usr/bin/env python3
"""
Demonstration of fault-tolerant file downloads in the cloud storage system.
Shows how files can be downloaded even when the original upload node goes offline.
"""

import time
import threading
import os
import tempfile
from fault_tolerant_client import FaultTolerantDownloadClient, download_file_fault_tolerant
from storage_virtual_network import StorageVirtualNetwork
from storage_virtual_node import StorageVirtualNode

def create_test_file(content: str, filename: str = None) -> str:
    """Create a temporary test file"""
    if filename is None:
        fd, filename = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
    
    with open(filename, 'w') as f:
        f.write(content)
    
    return filename

def simulate_node_failure(node):
    """Simulate a node going offline"""
    print(f"[Demo] Simulating failure of node {node.node_id}")
    node.shutdown()

def demonstrate_fault_tolerance():
    """Demonstrate fault-tolerant downloads"""
    print("=" * 60)
    print("FAULT-TOLERANT CLOUD STORAGE DEMONSTRATION")
    print("=" * 60)
    
    # Start network controller
    print("\n1. Starting network controller...")
    network = StorageVirtualNetwork(host='localhost', port=5000)
    time.sleep(1)
    
    # Create storage nodes
    print("\n2. Creating storage nodes...")
    node1 = StorageVirtualNode(
        node_id="node1",
        cpu_capacity=4,
        memory_capacity=8,
        storage_capacity=100,  # 100GB
        bandwidth=1000,  # 1Gbps
        port=6001
    )
    
    node2 = StorageVirtualNode(
        node_id="node2", 
        cpu_capacity=4,
        memory_capacity=8,
        storage_capacity=100,
        bandwidth=1000,
        port=6002
    )
    
    node3 = StorageVirtualNode(
        node_id="node3",
        cpu_capacity=4, 
        memory_capacity=8,
        storage_capacity=100,
        bandwidth=1000,
        port=6003
    )
    
    # Wait for nodes to register
    time.sleep(3)
    
    # Create test file
    print("\n3. Creating test file...")
    test_content = "This is a test file for fault tolerance demonstration.\n" * 100
    test_file = create_test_file(test_content, "test_document.txt")
    print(f"Created test file: {test_file} ({len(test_content)} bytes)")
    
    # Upload file from node1 (will be replicated to other nodes)
    print("\n4. Uploading file to cloud storage...")
    file_id = node1.upload_file(test_file, "test_document.txt")
    
    if file_id:
        print(f"File uploaded successfully with ID: {file_id}")
        time.sleep(2)  # Wait for replication to complete
    else:
        print("Upload failed!")
        return
    
    # Show network status
    print("\n5. Network status after upload:")
    files = network.list_files()
    for file_info in files:
        print(f"  File: {file_info['file_name']}")
        print(f"    Primary nodes: {file_info['primary_nodes']}")
        print(f"    Replica nodes: {file_info['replica_nodes']}")
        print(f"    Active replicas: {file_info.get('active_replicas', 'unknown')}")
        print(f"    Replication health: {file_info.get('replication_health', 'unknown')}")
    
    # Test normal download (all nodes online)
    print("\n6. Testing normal download (all nodes online)...")
    client = FaultTolerantDownloadClient()
    
    download_path = "downloaded_normal.txt"
    result = client.download_file_with_fault_tolerance(
        file_id=file_id,
        save_path=download_path,
        requesting_node="demo_client"
    )
    
    if result['status'] == 'OK':
        print(f"✓ Normal download successful from node {result['source_node']}")
        print(f"  Downloaded {result['bytes_downloaded']} bytes")
        print(f"  Attempts made: {result['attempts_made']}")
        os.remove(download_path)
    else:
        print(f"✗ Normal download failed: {result['error']}")
    
    # Simulate node1 (original uploader) going offline
    print(f"\n7. Simulating failure of original upload node (node1)...")
    threading.Thread(target=simulate_node_failure, args=(node1,), daemon=True).start()
    time.sleep(2)  # Wait for failure detection
    
    # Test fault-tolerant download (original node offline)
    print("\n8. Testing fault-tolerant download (original node offline)...")
    download_path = "downloaded_fault_tolerant.txt"
    result = client.download_file_with_fault_tolerance(
        file_id=file_id,
        save_path=download_path,
        requesting_node="demo_client"
    )
    
    if result['status'] == 'OK':
        print(f"✓ Fault-tolerant download successful from node {result['source_node']}")
        print(f"  Downloaded {result['bytes_downloaded']} bytes")
        print(f"  Attempts made: {result['attempts_made']}")
        print(f"  Nodes tried: {result['nodes_tried']}")
        
        # Verify file integrity
        with open(download_path, 'r') as f:
            downloaded_content = f.read()
        
        if downloaded_content == test_content:
            print("✓ File integrity verified - content matches original")
        else:
            print("✗ File integrity check failed - content differs")
        
        os.remove(download_path)
    else:
        print(f"✗ Fault-tolerant download failed: {result['error']}")
        print(f"  Nodes tried: {result.get('nodes_tried', 0)}")
        print(f"  Available nodes: {result.get('available_nodes', [])}")
    
    # Show node health status
    print("\n9. Node health status:")
    health_status = client.get_node_health_status()
    for node_id, status in health_status.items():
        print(f"  Node {node_id}:")
        print(f"    Status: {status['status']}")
        print(f"    Failure count: {status['failure_count']}")
        print(f"    Available: {status['is_available']}")
    
    # Test multiple node failures
    print(f"\n10. Simulating additional node failure (node2)...")
    threading.Thread(target=simulate_node_failure, args=(node2,), daemon=True).start()
    time.sleep(2)
    
    print("\n11. Testing download with multiple node failures...")
    download_path = "downloaded_multi_failure.txt"
    result = client.download_file_with_fault_tolerance(
        file_id=file_id,
        save_path=download_path,
        requesting_node="demo_client"
    )
    
    if result['status'] == 'OK':
        print(f"✓ Download successful despite multiple failures from node {result['source_node']}")
        print(f"  Downloaded {result['bytes_downloaded']} bytes")
        os.remove(download_path)
    else:
        print(f"✗ Download failed with multiple node failures: {result['error']}")
    
    # Test convenience function
    print("\n12. Testing convenience function...")
    download_path = "downloaded_convenience.txt"
    result = download_file_fault_tolerant(
        file_id=file_id,
        save_path=download_path,
        requesting_node="convenience_client"
    )
    
    if result['status'] == 'OK':
        print(f"✓ Convenience function download successful")
        os.remove(download_path)
    else:
        print(f"✗ Convenience function download failed: {result['error']}")
    
    # Cleanup
    print("\n13. Cleaning up...")
    os.remove(test_file)
    node3.shutdown()
    network.shutdown()
    
    print("\n" + "=" * 60)
    print("DEMONSTRATION COMPLETED")
    print("=" * 60)
    print("\nKey features demonstrated:")
    print("✓ File replication across multiple nodes")
    print("✓ Fault-tolerant downloads when original node fails")
    print("✓ Automatic failover to replica nodes")
    print("✓ Circuit breaker pattern for failed nodes")
    print("✓ Retry logic with exponential backoff")
    print("✓ File integrity verification")
    print("✓ Health monitoring and status tracking")

if __name__ == "__main__":
    demonstrate_fault_tolerance()
