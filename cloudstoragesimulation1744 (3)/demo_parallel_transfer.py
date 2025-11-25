#!/usr/bin/env python3
"""
Demonstration script for parallel file transfer capabilities
"""

import time
import threading
import random
from parallel_transfer import ParallelTransferManager, NetworkSimulator

def demo_parallel_transfer():
    """Demonstrate parallel file transfer with realistic network conditions"""
    print("=== Parallel File Transfer Demonstration ===\n")
    
    # Create network info for two nodes
    node1_info = {
        'ip_address': '192.168.1.10',
        'mac_address': '00:1B:44:11:3A:B7',
        'interface': 'eth0'
    }
    
    node2_info = {
        'ip_address': '192.168.1.20',
        'mac_address': '00:1B:44:11:3A:B8',
        'interface': 'eth0'
    }
    
    # Create transfer managers
    sender = ParallelTransferManager("node1", node1_info, max_concurrent_transfers=3)
    receiver = ParallelTransferManager("node2", node2_info, max_concurrent_transfers=3)
    
    # Create network simulator
    network_sim = NetworkSimulator()
    network_sim.set_network_conditions(
        loss_rate=0.03,    # 3% packet loss
        min_delay=0.02,    # 20ms minimum delay
        max_delay=0.15,    # 150ms maximum delay
        jitter=0.03        # 30ms jitter
    )
    
    print("Network Conditions:")
    print(f"- Packet Loss Rate: {network_sim.packet_loss_rate * 100:.1f}%")
    print(f"- Delay Range: {network_sim.min_delay * 1000:.0f}-{network_sim.max_delay * 1000:.0f}ms")
    print(f"- Jitter: ±{network_sim.jitter * 1000:.0f}ms\n")
    
    # Generate test data
    test_files = [
        ("small_file.txt", b"Hello, World! " * 100),  # ~1.3KB
        ("medium_file.dat", b"X" * 50000),             # ~50KB
        ("large_file.bin", b"Y" * 500000),             # ~500KB
    ]
    
    print("Starting parallel file transfers...\n")
    
    for file_name, file_data in test_files:
        print(f"Transferring {file_name} ({len(file_data):,} bytes)")
        
        # Start transfer
        transfer_id = sender.send_chunk_parallel(
            file_id=f"demo_{file_name}",
            chunk_id=0,
            data=file_data,
            dest_host=node2_info['ip_address'],
            dest_port=8080,
            dest_network_info=node2_info
        )
        
        # Monitor progress
        start_time = time.time()
        while True:
            time.sleep(0.5)
            
            sender_stats = sender.get_transfer_stats()
            receiver_stats = receiver.get_transfer_stats()
            
            elapsed = time.time() - start_time
            
            print(f"  Progress: Sent {sender_stats['packets_sent']} packets, "
                  f"Received {receiver_stats['packets_received']} packets "
                  f"({elapsed:.1f}s)")
            
            # Check if transfer completed (simplified)
            if elapsed > 10 or sender_stats['transfers_completed'] > 0:
                break
        
        print(f"  Transfer completed in {elapsed:.2f}s\n")
    
    # Display final statistics
    print("=== Final Transfer Statistics ===")
    
    sender_stats = sender.get_transfer_stats()
    receiver_stats = receiver.get_transfer_stats()
    
    print(f"Sender Statistics:")
    print(f"  - Packets Sent: {sender_stats['packets_sent']}")
    print(f"  - Packets Lost: {sender_stats['packets_lost']}")
    print(f"  - Retransmissions: {sender_stats['retransmissions']}")
    print(f"  - Transfers Completed: {sender_stats['transfers_completed']}")
    print(f"  - Transfers Failed: {sender_stats['transfers_failed']}")
    print(f"  - Success Rate: {sender_stats['success_rate']:.1f}%")
    print(f"  - Total Bytes: {sender_stats['total_bytes_transferred']:,}")
    
    print(f"\nReceiver Statistics:")
    print(f"  - Packets Received: {receiver_stats['packets_received']}")
    print(f"  - Transfers Completed: {receiver_stats['transfers_completed']}")
    print(f"  - Total Bytes: {receiver_stats['total_bytes_transferred']:,}")
    
    # Cleanup
    sender.shutdown()
    receiver.shutdown()
    
    print("\nDemonstration completed!")

if __name__ == '__main__':
    demo_parallel_transfer()
