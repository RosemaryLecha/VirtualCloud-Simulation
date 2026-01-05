import argparse
import time
import socket
import threading
from storage_virtual_node import StorageVirtualNode
from storage_virtual_network import StorageVirtualNetwork

def find_available_port(start_port=6000, end_port=6999):
    """Find an available port in the specified range with better collision handling"""
    import random
    ports = list(range(start_port, end_port + 1))
    random.shuffle(ports)  # Randomize to reduce collision probability
    
    for port in ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('localhost', port))
                # Double-check port is actually available
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                    s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s2.bind(('localhost', port + 1000))  # Check heartbeat port too
                return port
        except OSError:
            continue
    raise RuntimeError("No available ports in range")

def interactive_node_interface(node):
    """Interactive command interface for node operations"""
    print(f"\n[Node {node.node_id}] Interactive mode started")
    print("Available commands:")
    print("  create <filename> <content>  - Create a new file with content locally")
    print("  upload <filename>     - Upload file to cloud storage")
    print("  download <filename>   - Download file from cloud storage")
    print("  list                  - List local files")
    print("  cloud_files           - List all files in cloud storage")
    print("  status                - Show node status")
    print("  network_status        - Show network status")
    print("  metrics               - Show performance metrics")
    print("  help                  - Show this help message")
    print("  quit                  - Shutdown node")
    print(f"[Node {node.node_id}]> ", end="", flush=True)
    
    while True:
        try:
            command = input().strip().split()
            if not command:
                print(f"[Node {node.node_id}]> ", end="", flush=True)
                continue
                
            cmd = command[0].lower()
            
            if cmd == 'create' and len(command) > 2:
                filename = command[1]
                content = ' '.join(command[2:])  # Join remaining args as content
                try:
                    result = node.create_file(filename, content)
                    if not result:
                        print(f"[Node {node.node_id}] File creation failed: {filename}")
                except Exception as e:
                    print(f"[Node {node.node_id}] Create file error: {e}")
            
            elif cmd == 'upload' and len(command) > 1:
                filename = command[1]
                try:
                    result = node.upload_file(filename)
                    if result:
                        print(f"[Node {node.node_id}] File uploaded to cloud storage with replication: {filename}")
                    else:
                        print(f"[Node {node.node_id}] Upload failed: {filename}")
                except Exception as e:
                    print(f"[Node {node.node_id}] Upload error: {e}")
                    
            elif cmd == 'download' and len(command) > 1:
                filename = command[1]
                try:
                    result = node.download_file(file_name=filename)
                    if result:
                        print(f"[Node {node.node_id}] File downloaded from cloud storage: {filename}")
                    else:
                        print(f"[Node {node.node_id}] Download failed: {filename}")
                except Exception as e:
                    print(f"[Node {node.node_id}] Download error: {e}")
                    
            elif cmd == 'list':
                files = node.list_local_files()
                if files:
                    print(f"[Node {node.node_id}] Local files:")
                    for f in files:
                        print(f"  - {f['file_name']} ({f['file_size']} bytes)")
                else:
                    print(f"[Node {node.node_id}] No local files")
                    
            elif cmd == 'cloud_files':
                files = node.list_cloud_files()
                if files:
                    print(f"[Node {node.node_id}] Cloud storage files:")
                    for f in files:
                        print(f"  - {f['file_name']} ({f['file_size']} bytes) - Status: {f.get('status', 'available')} [Replicated across multiple nodes]")
                else:
                    print(f"[Node {node.node_id}] No files in cloud storage")
                    
            elif cmd == 'status':
                storage_info = node.get_storage_utilization()
                network_info = node.get_network_utilization()
                print(f"[Node {node.node_id}] Status:")
                print(f"  Storage: {storage_info['used_bytes']}/{storage_info['total_bytes']} bytes ({storage_info['utilization_percent']:.1f}%)")
                print(f"  Network utilization: {network_info['utilization_percent']:.1f}%")
                print(f"  Active transfers: {storage_info['active_transfers']}")
                print(f"  Files stored: {storage_info['files_stored']}")
                print(f"  Fault tolerance: ACTIVE (files replicated across nodes)")
                
            elif cmd == 'network_status':
                print(f"[Node {node.node_id}] Network Status:")
                print(f"  Connected to controller: {node.network_host}:{node.network_port}")
                print(f"  Node service port: {getattr(node, 'service_port', 'N/A')}")
                print(f"  IP: {node.network_info['ip_address']}")
                print(f"  MAC: {node.network_info['mac_address']}")
                print(f"  Replication enabled: YES")
                
            elif cmd == 'metrics':
                metrics = node.get_performance_metrics()
                print(f"[Node {node.node_id}] Performance Metrics:")
                print(f"  Requests processed: {metrics['total_requests_processed']}")
                print(f"  Data transferred: {metrics['total_data_transferred_bytes']} bytes")
                print(f"  Failed transfers: {metrics['failed_transfers']}")
                print(f"  Current active transfers: {metrics['current_active_transfers']}")
                
            elif cmd == 'help':
                print("Available commands:")
                print("  create <filename> <content>  - Create a new file with content locally")
                print("  upload <filename>     - Upload file to cloud storage")
                print("  download <filename>   - Download file from cloud storage")
                print("  list                  - List local files")
                print("  cloud_files           - List all files in cloud storage")
                print("  status                - Show node status")
                print("  network_status        - Show network status")
                print("  metrics               - Show performance metrics")
                print("  help                  - Show this help message")
                print("  quit                  - Shutdown node")
                
            elif cmd == 'quit':
                print(f"[Node {node.node_id}] Shutting down...")
                node.shutdown()
                break
                
            else:
                print(f"[Node {node.node_id}] Unknown command: {' '.join(command)}")
                print("Type 'help' for available commands")
                
            print(f"[Node {node.node_id}]> ", end="", flush=True)
            
        except KeyboardInterrupt:
            print(f"\n[Node {node.node_id}] Shutting down...")
            node.shutdown()
            break
        except EOFError:
            print(f"\n[Node {node.node_id}] Shutting down...")
            node.shutdown()
            break
        except Exception as e:
            print(f"[Node {node.node_id}] Command error: {e}")
            print(f"[Node {node.node_id}]> ", end="", flush=True)

def run_node(node_id, cpu, memory, storage, bandwidth, network_host, network_port):
    try:
        max_retries = 5
        for attempt in range(max_retries):
            try:
                node_port = find_available_port()
                print(f"[Node {node_id}] Assigned unique port: {node_port}")
                break
            except RuntimeError:
                if attempt == max_retries - 1:
                    raise
                print(f"[Node {node_id}] Port assignment failed, retrying... ({attempt + 1}/{max_retries})")
                time.sleep(1)
        
        print(f"Starting node {node_id}...")
        node = StorageVirtualNode(
            node_id=node_id,
            cpu_capacity=cpu,
            memory_capacity=memory,
            storage_capacity=storage,
            bandwidth=bandwidth,
            network_host=network_host,
            network_port=network_port,
            port=node_port
        )
        
        print(f"[Node {node_id}] Node started successfully on port {node_port}")
        print(f"[Node {node_id}] Connected to network controller at {network_host}:{network_port}")
        print(f"[Node {node_id}] Resources: CPU={cpu}, Memory={memory}GB, Storage={storage}GB, Bandwidth={bandwidth}Mbps")
        print(f"[Node {node_id}] Cloud storage features enabled with automatic replication and fault tolerance")
        
        interactive_node_interface(node)
        
    except KeyboardInterrupt:
        print(f"\n[Node {node_id}] Shutting down...")
        if 'node' in locals():
            node.shutdown()
        print(f"[Node {node_id}] Node stopped")
    except Exception as e:
        print(f"[Node {node_id}] Startup failed: {e}")

def run_network(host, port):
    try:
        print("Starting network controller...")
        network = StorageVirtualNetwork(host=host, port=port)
        
        print(f"[Network] Controller started on {host}:{port}")
        print(f"Network controller running on {host}:{port}. Press Ctrl+C to stop.")
        
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[Network] Shutting down network controller...")
        network.shutdown()
        print("[Network] Network controller stopped")
    except Exception as e:
        print(f"[Network] Startup failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Cloud Storage Simulation')
    parser.add_argument('--node', action='store_true', help='Run as a node')
    parser.add_argument('--network', action='store_true', help='Run as network controller')
    parser.add_argument('--node-id', type=str, help='Node ID')
    parser.add_argument('--cpu', type=int, default=4, help='CPU capacity')
    parser.add_argument('--memory', type=int, default=16, help='Memory capacity (GB)')
    parser.add_argument('--storage', type=int, default=500, help='Storage capacity (GB)')
    parser.add_argument('--bandwidth', type=int, default=1000, help='Bandwidth (Mbps)')
    parser.add_argument('--network-host', type=str, default='localhost', help='Network controller host')
    parser.add_argument('--network-port', type=int, default=5000, help='Network controller port')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind to (for network)')
    
    args = parser.parse_args()
    
    if args.network:
        run_network(args.host, args.network_port)
    elif args.node and args.node_id:
        run_node(
            args.node_id, 
            args.cpu, 
            args.memory, 
            args.storage, 
            args.bandwidth,
            args.network_host,
            args.network_port
        )
    else:
        print("Error: Please specify either --network or --node with --node-id")
        print("\nUsage examples:")
        print("  Network Controller: python main.py --network --host 0.0.0.0 --network-port 5000")
        print("  Storage Node: python main.py --node --node-id node1 --cpu 4 --memory 32 --storage 500 --bandwidth 1000 --network-host localhost --network-port 5000")
        print("  Create multiple nodes: Run the same command with different --node-id values in separate terminals")
