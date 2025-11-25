import time
import socket
import threading
import pickle
import random
import os
import json
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict
from dataclasses import dataclass, asdict
from enum import Enum

class FileStatus(Enum):
    UPLOADING = "uploading"
    AVAILABLE = "available"
    REPLICATING = "replicating"
    CORRUPTED = "corrupted"
    DEGRADED = "degraded"  # Added degraded status for files with insufficient replicas

@dataclass
class FileRecord:
    file_id: str
    file_name: str
    file_size: int
    primary_nodes: List[str]  # Nodes storing the file
    replica_nodes: List[str]  # Backup copies
    status: FileStatus
    upload_time: float
    checksum: str
    replication_factor: int = 2  # Default replication factor
    target_replicas: int = 2  # Target number of replicas for this file

class NetworkController(threading.Thread):
    def __init__(self, host: str = '0.0.0.0', port: int = 5000):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.nodes = {}
        self.lock = threading.Lock()
        self.running = False
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.heartbeat_timeout = 5
        self.transfer_operations = defaultdict(dict)

        # Persistent storage setup
        self.registry_dir = "storage_data"
        os.makedirs(self.registry_dir, exist_ok=True)

        self.file_registry = {}  # file_id -> FileRecord
        self.node_files = defaultdict(set)  # node_id -> set of file_ids
        self.replication_queue = []  # Files waiting for replication
        self.replication_factor = 2  # Default number of replicas

        # Load existing registry from disk
        self._load_registry()

        self.replication_monitor = threading.Thread(target=self._monitor_replication, daemon=True)
        self.replication_active = False

    def _load_registry(self):
        """Load file registry from disk on startup"""
        registry_path = os.path.join(self.registry_dir, 'network_registry.json')
        try:
            if os.path.exists(registry_path):
                with open(registry_path, 'r') as f:
                    data = json.load(f)

                # Restore file registry
                for file_id, record_data in data.get('file_registry', {}).items():
                    # Reconstruct FileRecord from JSON data
                    file_record = FileRecord(
                        file_id=record_data['file_id'],
                        file_name=record_data['file_name'],
                        file_size=record_data['file_size'],
                        primary_nodes=record_data['primary_nodes'],
                        replica_nodes=record_data['replica_nodes'],
                        status=FileStatus(record_data['status']),
                        upload_time=record_data['upload_time'],
                        checksum=record_data['checksum'],
                        replication_factor=record_data.get('replication_factor', 2),
                        target_replicas=record_data.get('target_replicas', 2)
                    )
                    self.file_registry[file_id] = file_record

                # Restore node_files mapping
                for node_id, file_ids in data.get('node_files', {}).items():
                    self.node_files[node_id] = set(file_ids)

                print(f"[Network] Loaded {len(self.file_registry)} files from registry")
        except Exception as e:
            print(f"[Network] Error loading registry: {e}")

    def _save_registry(self):
        """Save file registry to disk"""
        registry_path = os.path.join(self.registry_dir, 'network_registry.json')
        try:
            # Convert FileRecord objects to dictionaries
            file_registry_data = {}
            for file_id, record in self.file_registry.items():
                file_registry_data[file_id] = {
                    'file_id': record.file_id,
                    'file_name': record.file_name,
                    'file_size': record.file_size,
                    'primary_nodes': record.primary_nodes,
                    'replica_nodes': record.replica_nodes,
                    'status': record.status.value,
                    'upload_time': record.upload_time,
                    'checksum': record.checksum,
                    'replication_factor': record.replication_factor,
                    'target_replicas': record.target_replicas
                }

            # Convert node_files sets to lists for JSON serialization
            node_files_data = {node_id: list(file_ids) for node_id, file_ids in self.node_files.items()}

            data = {
                'file_registry': file_registry_data,
                'node_files': node_files_data
            }

            # Create backup before overwriting
            if os.path.exists(registry_path):
                backup_path = registry_path + '.backup'
                os.replace(registry_path, backup_path)

            # Write new registry
            with open(registry_path, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

        except Exception as e:
            print(f"[Network] Error saving registry: {e}")

    def run(self):
        self.running = True
        self.replication_active = True
        self.replication_monitor.start()
        
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen()
            print(f"[Network] Controller started on {self.host}:{self.port}")
            
            while self.running:
                try:
                    conn, addr = self.socket.accept()
                    threading.Thread(
                        target=self._handle_connection,
                        args=(conn,),
                        daemon=True
                    ).start()
                except OSError as e:
                    if self.running:
                        print(f"[Network] Accept error: {e}")
                    break
        except OSError as e:
            print(f"[Network] Failed to start: {e}")
        finally:
            self.socket.close()

    def _monitor_replication(self):
        """Monitor and maintain file replication levels"""
        while self.replication_active:
            try:
                with self.lock:
                    # Process replication queue
                    if self.replication_queue:
                        file_id = self.replication_queue.pop(0)
                        self._process_replication_request(file_id)
                    
                    # Check all files for adequate replication
                    for file_id, file_record in self.file_registry.items():
                        self._check_file_replication_health(file_id, file_record)
                
                time.sleep(2)  # Check every 2 seconds
            except Exception as e:
                print(f"[Network] Replication monitor error: {e}")
                time.sleep(5)

    def _check_file_replication_health(self, file_id: str, file_record: FileRecord):
        """Check if a file has adequate replication and fix if needed"""
        # Count active replicas
        active_nodes = []
        all_storage_nodes = file_record.primary_nodes + file_record.replica_nodes
        
        for node_id in all_storage_nodes:
            if node_id in self.nodes and self.nodes[node_id]['status'] == 'active':
                active_nodes.append(node_id)
        
        current_replicas = len(active_nodes)
        target_replicas = file_record.target_replicas
        
        if current_replicas < target_replicas:
            if file_record.status != FileStatus.DEGRADED:
                print(f"[Network] File {file_record.file_name} is under-replicated ({current_replicas}/{target_replicas})")
                file_record.status = FileStatus.DEGRADED
            
            # Schedule for re-replication if not already queued
            if file_id not in self.replication_queue:
                self.replication_queue.append(file_id)
        elif current_replicas >= target_replicas and file_record.status == FileStatus.DEGRADED:
            print(f"[Network] File {file_record.file_name} replication restored ({current_replicas}/{target_replicas})")
            file_record.status = FileStatus.AVAILABLE

    def _process_replication_request(self, file_id: str):
        """Process a file that needs replication"""
        if file_id not in self.file_registry:
            return
        
        file_record = self.file_registry[file_id]
        
        # Find active nodes with the file
        source_nodes = []
        all_storage_nodes = file_record.primary_nodes + file_record.replica_nodes
        
        for node_id in all_storage_nodes:
            if node_id in self.nodes and self.nodes[node_id]['status'] == 'active':
                source_nodes.append(node_id)
        
        if not source_nodes:
            print(f"[Network] Cannot replicate {file_record.file_name} - no source nodes available")
            return
        
        # Find available target nodes (not already storing the file)
        available_targets = []
        for node_id, node_info in self.nodes.items():
            if (node_info['status'] == 'active' and 
                node_id not in all_storage_nodes and
                self._has_storage_capacity(node_id, file_record.file_size)):
                available_targets.append(node_id)
        
        if not available_targets:
            print(f"[Network] No available nodes for replicating {file_record.file_name}")
            return
        
        # Calculate how many more replicas we need
        current_replicas = len(source_nodes)
        needed_replicas = max(0, file_record.target_replicas - current_replicas)
        
        # Select target nodes for replication
        target_nodes = random.sample(available_targets, min(needed_replicas, len(available_targets)))
        
        # Initiate replication to each target
        source_node = random.choice(source_nodes)  # Pick a random source
        for target_node in target_nodes:
            print(f"[Network] Initiating replication of {file_record.file_name} from {source_node} to {target_node}")
            if self._initiate_replication(file_id, source_node, target_node):
                # Add to replica nodes if successful
                file_record.replica_nodes.append(target_node)
                self.node_files[target_node].add(file_id)

    def _has_storage_capacity(self, node_id: str, file_size: int) -> bool:
        """Check if a node has sufficient storage capacity"""
        if node_id not in self.nodes:
            return False
        
        node_capacity = self.nodes[node_id]['capacity']
        total_storage = node_capacity.get('storage', 0)
        
        # Estimate used storage (simplified - in real implementation, track actual usage)
        estimated_used = len(self.node_files.get(node_id, set())) * (file_size * 0.5)  # Rough estimate
        
        return (total_storage - estimated_used) > file_size
            
    def _handle_connection(self, conn):
        try:
            data = conn.recv(4096)
            if not data:
                return

            message = pickle.loads(data)
            with self.lock:
                if message['action'] == 'REGISTER':
                    node_id = message['node_id']
                    if node_id not in self.nodes:
                        print(f"[Network] Node {node_id} registered (came ONLINE)")
                    self.nodes[node_id] = {
                        'host': message['host'],
                        'port': message['port'],
                        'capacity': message['capacity'],
                        'last_seen': 0,  # 0 means registered but not yet active
                        'status': 'registered'
                    }
                    conn.sendall(pickle.dumps({'status': 'OK'}))

                elif message['action'] == 'ACTIVE_NOTIFICATION':
                    node_id = message['node_id']
                    if node_id in self.nodes:
                        if self.nodes[node_id]['status'] != 'active':
                            print(f"[Network] Node {node_id} is now ACTIVE")
                        self.nodes[node_id]['status'] = 'active'
                        self.nodes[node_id]['last_seen'] = time.time()
                        conn.sendall(pickle.dumps({'status': 'ACK'}))

                elif message['action'] == 'HEARTBEAT':
                    node_id = message['node_id']
                    if node_id in self.nodes:
                        if self.nodes[node_id]['status'] == 'registered':
                            print(f"[Network] Node {node_id} is now ACTIVE")
                            self.nodes[node_id]['status'] = 'active'
                        self.nodes[node_id]['last_seen'] = time.time()
                        conn.sendall(pickle.dumps({'status': 'ACK'}))
                    else:
                        conn.sendall(pickle.dumps({
                            'status': 'ERROR',
                            'error': 'Node not registered'
                        }))
                
                elif message['action'] == 'UPLOAD_FILE':
                    response = self._handle_file_upload(message)
                    conn.sendall(pickle.dumps(response))
                
                elif message['action'] == 'DOWNLOAD_FILE':
                    response = self._handle_file_download(message)
                    conn.sendall(pickle.dumps(response))
                
                elif message['action'] == 'UPLOAD_COMPLETE':
                    response = self._handle_upload_complete(message)
                    conn.sendall(pickle.dumps(response))
                
                elif message['action'] == 'LIST_CLOUD_FILES':
                    response = self._handle_list_cloud_files(message)
                    conn.sendall(pickle.dumps(response))
                
                elif message['action'] == 'GET_AVAILABLE_REPLICAS':
                    response = self._handle_get_available_replicas(message)
                    conn.sendall(pickle.dumps(response))
                    
        except Exception as e:
            print(f"[Network] Connection error: {e}")
        finally:
            conn.close()

    def _handle_file_upload(self, message) -> Dict:
        """Handle file upload request from a node"""
        file_id = message['file_id']
        file_name = message['file_name']
        file_size = message['file_size']
        requesting_node = message['node_id']
        
        available_nodes = [node_id for node_id, info in self.nodes.items() 
                          if info['status'] == 'active']
        
        # Include requesting node as primary storage
        if requesting_node not in available_nodes:
            available_nodes.append(requesting_node)
        
        if len(available_nodes) == 0:
            return {
                'status': 'ERROR',
                'error': 'No active nodes available'
            }
        
        target_replicas = min(self.replication_factor, len(available_nodes) - 1)
        
        # Select primary node (requesting node) and replica nodes
        primary_node = requesting_node
        other_nodes = [node for node in available_nodes if node != requesting_node]
        
        suitable_replicas = []
        for node_id in other_nodes:
            if self._has_storage_capacity(node_id, file_size):
                suitable_replicas.append(node_id)
        
        replica_nodes = random.sample(suitable_replicas, min(target_replicas, len(suitable_replicas)))
        
        # Create file record
        file_record = FileRecord(
            file_id=file_id,
            file_name=file_name,
            file_size=file_size,
            primary_nodes=[primary_node],
            replica_nodes=replica_nodes,
            status=FileStatus.UPLOADING,
            upload_time=time.time(),
            checksum=message.get('checksum', ''),
            replication_factor=target_replicas,
            target_replicas=self.replication_factor  # Always aim for full replication
        )
        
        self.file_registry[file_id] = file_record
        self.node_files[primary_node].add(file_id)
        for replica_node in replica_nodes:
            self.node_files[replica_node].add(file_id)

        # Save registry to disk after adding new file
        self._save_registry()

        if len(replica_nodes) >= self.replication_factor:
            print(f"[Network] File {file_name} will be stored with full redundancy ({len(replica_nodes)} replicas)")
        elif len(replica_nodes) > 0:
            print(f"[Network] File {file_name} will be stored with partial redundancy ({len(replica_nodes)} replicas)")
        else:
            print(f"[Network] File {file_name} will be stored with no redundancy (single copy)")

        return {
            'status': 'OK',
            'primary_node': primary_node,
            'replica_nodes': replica_nodes,
            'node_info': {node_id: self.nodes[node_id] for node_id in [primary_node] + replica_nodes if node_id in self.nodes}
        }

    def _handle_file_download(self, message) -> Dict:
        """Handle file download request - retrieve and send file data directly with fault tolerance"""
        file_id = message.get('file_id')
        file_name = message.get('file_name')
        requesting_node = message['node_id']
        
        # Find file by ID or name
        file_record = None
        if file_id and file_id in self.file_registry:
            file_record = self.file_registry[file_id]
        elif file_name:
            for record in self.file_registry.values():
                if record.file_name == file_name:
                    file_record = record
                    break
        
        if not file_record:
            return {
                'status': 'ERROR',
                'error': 'File not found'
            }
        
        available_nodes = []
        all_storage_nodes = file_record.primary_nodes + file_record.replica_nodes
        
        for node_id in all_storage_nodes:
            if node_id in self.nodes and self.nodes[node_id]['status'] == 'active':
                available_nodes.append(node_id)
        
        if not available_nodes:
            return {
                'status': 'ERROR',
                'error': 'File not available - all storage nodes offline'
            }
        
        preferred_order = []
        # First, add active primary nodes
        for node_id in file_record.primary_nodes:
            if node_id in available_nodes:
                preferred_order.append(node_id)
        # Then, add active replica nodes
        for node_id in file_record.replica_nodes:
            if node_id in available_nodes and node_id not in preferred_order:
                preferred_order.append(node_id)
        
        last_error = None
        for attempt, selected_node in enumerate(preferred_order):
            try:
                print(f"[Network] Attempting to retrieve {file_record.file_name} from node {selected_node} (attempt {attempt + 1}/{len(preferred_order)})")
                
                # Connect to storage node and get file data
                storage_node_info = self.nodes[selected_node]
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(15)  # Increased timeout for large files
                    s.connect((storage_node_info['host'], storage_node_info['port']))
                    s.sendall(pickle.dumps({
                        'action': 'TRANSFER_FILE',
                        'file_id': file_record.file_id,
                        'requesting_node': requesting_node
                    }))
                    
                    response_data = b''
                    expected_size = None
                    
                    while True:
                        try:
                            chunk = s.recv(8192)  # Larger chunks for better performance
                            if not chunk:
                                break
                            response_data += chunk
                            
                            # Try to parse response periodically
                            if len(response_data) > 1024:  # Only try parsing after we have some data
                                try:
                                    response = pickle.loads(response_data)
                                    break
                                except (pickle.UnpicklingError, EOFError):
                                    # Continue receiving more data
                                    continue
                        except socket.timeout:
                            print(f"[Network] Timeout receiving data from node {selected_node}")
                            break
                    
                    # Parse the final response
                    try:
                        response = pickle.loads(response_data)
                    except (pickle.UnpicklingError, EOFError) as e:
                        last_error = f'Node {selected_node} sent invalid data: {str(e)}'
                        print(f"[Network] {last_error}")
                        continue
                    
                    if response.get('status') == 'OK':
                        file_data = response['file_data']
                        
                        if file_record.checksum:
                            import hashlib
                            actual_checksum = hashlib.md5(file_data).hexdigest()
                            if actual_checksum != file_record.checksum:
                                last_error = f'Node {selected_node} returned corrupted file (checksum mismatch)'
                                print(f"[Network] {last_error}")
                                continue
                        
                        print(f"[Network] Successfully retrieved {file_record.file_name} from node {selected_node}")
                        
                        # Return file data directly to requesting node
                        return {
                            'status': 'OK',
                            'file_id': file_record.file_id,
                            'file_name': file_record.file_name,
                            'file_size': file_record.file_size,
                            'file_data': file_data,
                            'source_node': selected_node,
                            'node_info': storage_node_info
                        }
                    else:
                        last_error = f'Node {selected_node} failed: {response.get("error", "Unknown error")}'
                        print(f"[Network] {last_error}")
                        continue
                        
            except socket.timeout:
                last_error = f'Node {selected_node} connection timeout'
                print(f"[Network] {last_error}")
                continue
            except ConnectionRefusedError:
                last_error = f'Node {selected_node} connection refused - node may be offline'
                print(f"[Network] {last_error}")
                # Mark node as potentially offline
                if selected_node in self.nodes:
                    self.nodes[selected_node]['status'] = 'offline'
                continue
            except Exception as e:
                last_error = f'Node {selected_node} connection failed: {str(e)}'
                print(f"[Network] {last_error}")
                continue
        
        return {
            'status': 'ERROR',
            'error': f'All {len(preferred_order)} storage nodes failed. File may be corrupted or nodes are offline. Last error: {last_error}',
            'attempted_nodes': preferred_order,
            'available_replicas': len(available_nodes)
        }

    def _handle_get_available_replicas(self, message) -> Dict:
        """Handle request to get available replica nodes for a file"""
        file_id = message.get('file_id')
        requesting_node = message['node_id']
        
        if file_id not in self.file_registry:
            return {
                'status': 'ERROR',
                'error': 'File not found'
            }
        
        file_record = self.file_registry[file_id]
        available_nodes = []
        all_storage_nodes = file_record.primary_nodes + file_record.replica_nodes
        
        for node_id in all_storage_nodes:
            if node_id in self.nodes and self.nodes[node_id]['status'] == 'active':
                available_nodes.append(self.nodes[node_id])
        
        primary_node = None
        if file_record.primary_nodes and file_record.primary_nodes[0] in self.nodes:
            if self.nodes[file_record.primary_nodes[0]]['status'] == 'active':
                primary_node = file_record.primary_nodes[0]
        
        return {
            'status': 'OK',
            'available_nodes': available_nodes,
            'primary_node': primary_node,
            'total_replicas': len(available_nodes)
        }

    def _handle_upload_complete(self, message) -> Dict:
        """Handle notification that file upload is complete"""
        file_id = message['file_id']
        node_id = message['node_id']

        if file_id in self.file_registry:
            file_record = self.file_registry[file_id]
            if node_id in file_record.primary_nodes + file_record.replica_nodes:
                file_record.status = FileStatus.AVAILABLE
                print(f"[Network] File {file_record.file_name} upload completed on node {node_id}")

                # Save registry after status change
                self._save_registry()

                # Trigger replication if needed
                self._trigger_replication(file_id)

                return {'status': 'OK'}

        return {'status': 'ERROR', 'error': 'File or node not found'}

    def _trigger_replication(self, file_id: str):
        """Trigger replication of a file to replica nodes"""
        if file_id not in self.file_registry:
            return
        
        file_record = self.file_registry[file_id]
        primary_node = file_record.primary_nodes[0]
        
        # Check if primary node is still active
        if primary_node not in self.nodes or self.nodes[primary_node]['status'] != 'active':
            return
        
        # Replicate to each replica node
        for replica_node in file_record.replica_nodes:
            if replica_node in self.nodes and self.nodes[replica_node]['status'] == 'active':
                self._initiate_replication(file_id, primary_node, replica_node)

    def _initiate_replication(self, file_id: str, source_node: str, target_node: str) -> bool:
        """Initiate replication between two nodes"""
        try:
            # Send replication command to target node
            target_info = self.nodes[target_node]
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)  # Increased timeout for replication
                s.connect((target_info['host'], target_info['port']))
                s.sendall(pickle.dumps({
                    'action': 'REPLICATE_FILE',
                    'file_id': file_id,
                    'source_node': source_node,
                    'source_info': self.nodes[source_node]
                }))
                response = pickle.loads(s.recv(1024))
                
                if response.get('status') == 'OK':
                    print(f"[Network] File replication from {source_node} to {target_node} completed")
                    return True
                else:
                    print(f"[Network] Replication failed from {source_node} to {target_node}: {response.get('error', 'Unknown error')}")
                    return False
                    
        except Exception as e:
            print(f"[Network] Replication error from {source_node} to {target_node}: {e}")
            return False

    def check_node_status(self):
        """Check which nodes are offline and handle file recovery"""
        current_time = time.time()
        offline_nodes = []

        with self.lock:
            for node_id, info in list(self.nodes.items()):
                if info['status'] == 'registered':
                    continue  # New node not yet active
                    
                if current_time - info['last_seen'] > self.heartbeat_timeout:
                    offline_nodes.append(node_id)
                    print(f"[Network] Node {node_id} went OFFLINE")
                    
                    self._handle_node_failure(node_id)
                    del self.nodes[node_id]

        return offline_nodes

    def _handle_node_failure(self, failed_node: str):
        """Handle files when a node goes offline"""
        affected_files = self.node_files.get(failed_node, set())

        for file_id in affected_files:
            if file_id in self.file_registry:
                file_record = self.file_registry[file_id]

                # Remove failed node from file record
                if failed_node in file_record.primary_nodes:
                    file_record.primary_nodes.remove(failed_node)
                    if file_record.replica_nodes:
                        new_primary = file_record.replica_nodes.pop(0)
                        file_record.primary_nodes.append(new_primary)
                        print(f"[Network] Promoted {new_primary} to primary for file {file_record.file_name}")

                if failed_node in file_record.replica_nodes:
                    file_record.replica_nodes.remove(failed_node)

                # Check if we need more replicas
                total_copies = len(file_record.primary_nodes) + len(file_record.replica_nodes)
                if total_copies < file_record.target_replicas:
                    print(f"[Network] File {file_record.file_name} needs re-replication due to node failure")
                    file_record.status = FileStatus.DEGRADED
                    self._schedule_re_replication(file_id)

        # Clear node files
        if failed_node in self.node_files:
            del self.node_files[failed_node]

        # Save registry after handling node failure
        self._save_registry()

    def _schedule_re_replication(self, file_id: str):
        """Schedule a file for re-replication"""
        if file_id not in self.replication_queue:
            self.replication_queue.append(file_id)

    def list_files(self) -> List[Dict]:
        """List all files in the system"""
        with self.lock:
            files = []
            for file_record in self.file_registry.values():
                active_replicas = 0
                all_storage_nodes = file_record.primary_nodes + file_record.replica_nodes
                for node_id in all_storage_nodes:
                    if node_id in self.nodes and self.nodes[node_id]['status'] == 'active':
                        active_replicas += 1
                
                files.append({
                    'file_id': file_record.file_id,
                    'file_name': file_record.file_name,
                    'file_size': file_record.file_size,
                    'status': file_record.status.value,
                    'primary_nodes': file_record.primary_nodes,
                    'replica_nodes': file_record.replica_nodes,
                    'upload_time': file_record.upload_time,
                    'active_replicas': active_replicas,
                    'target_replicas': file_record.target_replicas,
                    'replication_health': 'healthy' if active_replicas >= file_record.target_replicas else 'degraded'
                })
            return files

    def _handle_list_cloud_files(self, message) -> Dict:
        """Handle request to list all cloud files"""
        requesting_node = message['node_id']
        
        cloud_files = []
        for file_record in self.file_registry.values():
            if file_record.status in [FileStatus.AVAILABLE, FileStatus.DEGRADED]:
                active_replicas = 0
                all_storage_nodes = file_record.primary_nodes + file_record.replica_nodes
                for node_id in all_storage_nodes:
                    if node_id in self.nodes and self.nodes[node_id]['status'] == 'active':
                        active_replicas += 1
                
                cloud_files.append({
                    'file_id': file_record.file_id,
                    'file_name': file_record.file_name,
                    'file_size': file_record.file_size,
                    'upload_time': file_record.upload_time,
                    'status': 'available' if active_replicas > 0 else 'unavailable',
                    'replicas': active_replicas,
                    'replication_health': 'healthy' if active_replicas >= file_record.target_replicas else 'degraded'
                })
        
        return {
            'status': 'OK',
            'files': cloud_files
        }

    def stop(self):
        self.running = False
        self.replication_active = False

        # Save registry before shutdown
        print("[Network] Saving file registry before shutdown...")
        self._save_registry()
        print(f"[Network] Saved registry with {len(self.file_registry)} files")

        # Create temporary connection to unblock accept()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
        except:
            pass

class StorageVirtualNetwork:
    def __init__(self, host: str = '0.0.0.0', port: int = 5000):
        self.controller = NetworkController(host, port)
        self.controller.start()
        self.heartbeat_checker = threading.Thread(
            target=self._check_heartbeats,
            daemon=True
        )
        self.heartbeat_checker.start()
        
    def _check_heartbeats(self):
        while self.controller.running:
            self.controller.check_node_status()
            time.sleep(1)
            
    def add_node(self, node_id: str, host: str, port: int, capacity: Dict):
        """Manually add a node"""
        with self.controller.lock:
            self.controller.nodes[node_id] = {
                'host': host,
                'port': port,
                'capacity': capacity,
                'last_seen': time.time(),
                'status': 'active'
            }
            print(f"[Network] Manually added node {node_id}")
            
    def connect_nodes(self, node1_id: str, node2_id: str, bandwidth: int):
        """Connect two nodes with specified bandwidth"""
        if node1_id in self.controller.nodes and node2_id in self.controller.nodes:
            self._send_connection_info(node1_id, node2_id, bandwidth)
            self._send_connection_info(node2_id, node1_id, bandwidth)
            return True
        return False
        
    def _send_connection_info(self, target_node: str, peer_node: str, bandwidth: int):
        """Send connection information to a node"""
        peer_info = self.controller.nodes[peer_node]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(2)
                s.connect((peer_info['host'], peer_info['port']))
                s.sendall(pickle.dumps({
                    'action': 'CONNECT',
                    'node_id': peer_node,
                    'host': peer_info['host'],
                    'port': peer_info['port'],
                    'bandwidth': bandwidth
                }))
            except ConnectionRefusedError:
                print(f"[Network] Could not connect to node {peer_node}")

    def upload_file(self, node_id: str, file_id: str, file_name: str, file_size: int, checksum: str = '') -> Dict:
        """Request file upload through the network"""
        message = {
            'action': 'UPLOAD_FILE',
            'node_id': node_id,
            'file_id': file_id,
            'file_name': file_name,
            'file_size': file_size,
            'checksum': checksum
        }
        return self.controller._handle_file_upload(message)

    def download_file(self, node_id: str, file_id: str = None, file_name: str = None) -> Dict:
        """Request file download through the network"""
        message = {
            'action': 'DOWNLOAD_FILE',
            'node_id': node_id,
            'file_id': file_id,
            'file_name': file_name
        }
        return self.controller._handle_file_download(message)

    def list_files(self) -> List[Dict]:
        """List all files in the network"""
        return self.controller.list_files()

    def list_cloud_files(self, node_id: str) -> Dict:
        """Request list of all cloud files"""
        message = {
            'action': 'LIST_CLOUD_FILES',
            'node_id': node_id
        }
        return self.controller._handle_list_cloud_files(message)

    def get_network_stats(self) -> Dict[str, float]:
        """Get overall network statistics"""
        with self.controller.lock:
            total_bandwidth = sum(n['capacity']['bandwidth'] for n in self.controller.nodes.values())
            used_bandwidth = sum(n['capacity']['bandwidth'] * 0.5 for n in self.controller.nodes.values())  # Simulated
            total_storage = sum(n['capacity']['storage'] for n in self.controller.nodes.values())
            used_storage = sum(n['capacity']['storage'] * 0.3 for n in self.controller.nodes.values())  # Simulated
            
            return {
                "total_nodes": len(self.controller.nodes),
                "active_nodes": sum(1 for n in self.controller.nodes.values() if n['status'] == 'active'),
                "total_files": len(self.controller.file_registry),
                "files_replicating": len(self.controller.replication_queue),
                "total_bandwidth_bps": total_bandwidth,
                "used_bandwidth_bps": used_bandwidth,
                "bandwidth_utilization": (used_bandwidth / total_bandwidth) * 100 if total_bandwidth > 0 else 0,
                "total_storage_bytes": total_storage,
                "used_storage_bytes": used_storage,
                "storage_utilization": (used_storage / total_storage) * 100 if total_storage > 0 else 0,
                "active_transfers": sum(len(t) for t in self.controller.transfer_operations.values())
            }

    def shutdown(self):
        """Graceful shutdown"""
        print("[Network] Shutting down controller...")
        self.controller.stop()
        self.controller.join()
        print("[Network] Controller shutdown complete")
