import time
import socket
import threading
import pickle
import hashlib
import os
import json
import random
import shutil
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict

@dataclass
class NetworkInfo:
    ip_address: str
    mac_address: str
    bandwidth: int
    latency: float = 0.0

class StorageVirtualNode:
    def __init__(self, node_id: str, cpu_capacity: int, memory_capacity: int,
                 storage_capacity: int, bandwidth: int, network_host: str = 'localhost',
                 network_port: int = 5000, port: int = 6000):
        self.node_id = node_id
        self.cpu_capacity = cpu_capacity
        self.memory_capacity = memory_capacity
        self.storage_capacity = storage_capacity * 1024 * 1024 * 1024  # Convert GB to bytes
        self.bandwidth = bandwidth
        self.network_host = network_host
        self.network_port = network_port
        self.port = port
        self.service_port = port

        # Persistent storage setup
        self.storage_dir = f"storage_data/{self.node_id}"
        os.makedirs(self.storage_dir, exist_ok=True)

        # Storage management - now using file index instead of storing data in memory
        self.used_storage = 0
        self.file_index = {}  # file_id -> file_path mapping
        self.file_metadata = {}  # file_id -> metadata
        self.file_lock = threading.Lock()
        
        # Network info
        self.network_info = NetworkInfo(
            ip_address=f"192.168.1.{random.randint(10, 254)}",
            mac_address=f"02:00:00:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}",
            bandwidth=bandwidth
        )
        
        # Performance metrics
        self.metrics = {
            'total_requests_processed': 0,
            'total_data_transferred_bytes': 0,
            'failed_transfers': 0,
            'current_active_transfers': 0
        }
        
        # Server socket for handling requests
        self.server_socket = None
        self.running = False

        # Load existing files from disk (persistence)
        self._load_existing_files()

        # Start the node
        self._start_server()
        self._register_with_network()
        self._start_heartbeat()
        
    def _load_existing_files(self):
        """Load existing files from disk on startup"""
        try:
            # Load metadata from JSON file
            metadata = self._load_metadata()

            # Scan storage directory for actual files
            if os.path.exists(self.storage_dir):
                for filename in os.listdir(self.storage_dir):
                    if filename.endswith('.dat'):
                        file_id = filename[:-4]  # Remove .dat extension
                        file_path = os.path.join(self.storage_dir, filename)

                        # Add to file index
                        self.file_index[file_id] = file_path

                        # Get file size
                        file_size = os.path.getsize(file_path)
                        self.used_storage += file_size

                        # Restore metadata if available
                        if file_id in metadata:
                            self.file_metadata[file_id] = metadata[file_id]
                        else:
                            # Create basic metadata if not found
                            self.file_metadata[file_id] = {
                                'file_name': f'recovered_{file_id}',
                                'file_size': file_size,
                                'checksum': '',
                                'upload_time': os.path.getmtime(file_path),
                                'file_id': file_id,
                                'node_id': self.node_id
                            }

                if self.file_index:
                    print(f"[Node {self.node_id}] Loaded {len(self.file_index)} existing files from disk ({self.used_storage:,} bytes)")

        except Exception as e:
            print(f"[Node {self.node_id}] Error loading existing files: {e}")

    def _load_metadata(self) -> Dict:
        """Load metadata from JSON file"""
        metadata_path = os.path.join(self.storage_dir, 'metadata.json')
        try:
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Node {self.node_id}] Error loading metadata: {e}")
        return {}

    def _save_metadata(self):
        """Save metadata to JSON file"""
        metadata_path = os.path.join(self.storage_dir, 'metadata.json')
        try:
            # Create backup of existing metadata
            if os.path.exists(metadata_path):
                backup_path = metadata_path + '.backup'
                shutil.copy2(metadata_path, backup_path)

            # Write new metadata
            with open(metadata_path, 'w') as f:
                json.dump(self.file_metadata, f, indent=2)

            # Ensure data is written to disk
            f.flush()
            os.fsync(f.fileno())

        except Exception as e:
            print(f"[Node {self.node_id}] Error saving metadata: {e}")

    def _start_server(self):
        """Start the node server to handle incoming requests"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('localhost', self.port))
        self.server_socket.listen(5)
        self.running = True

        # Start server thread
        self.server_thread = threading.Thread(target=self._handle_requests, daemon=True)
        self.server_thread.start()
        
    def _handle_requests(self):
        """Handle incoming requests from other nodes or network controller"""
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()
            except OSError:
                if self.running:
                    print(f"[Node {self.node_id}] Server socket error")
                break
                
    def _handle_connection(self, conn):
        """Handle individual connection"""
        try:
            data = conn.recv(4096)
            if not data:
                return
                
            message = pickle.loads(data)
            action = message.get('action')
            
            if action == 'TRANSFER_FILE':
                response = self._handle_file_transfer_request(message)
                conn.sendall(pickle.dumps(response))
            elif action == 'REPLICATE_FILE':
                response = self._handle_replication_request(message)
                conn.sendall(pickle.dumps(response))
            else:
                conn.sendall(pickle.dumps({'status': 'ERROR', 'error': 'Unknown action'}))
                
        except Exception as e:
            print(f"[Node {self.node_id}] Connection handling error: {e}")
        finally:
            conn.close()
            
    def _load_file_from_disk(self, file_id: str) -> Tuple[Optional[bytes], Optional[Dict]]:
        """Load file data from disk"""
        try:
            if file_id not in self.file_index:
                return None, None

            file_path = self.file_index[file_id]

            # Check if file exists
            if not os.path.exists(file_path):
                print(f"[Node {self.node_id}] File {file_id} not found on disk at {file_path}")
                return None, None

            # Read file data
            with open(file_path, 'rb') as f:
                file_data = f.read()

            # Get metadata
            metadata = self.file_metadata.get(file_id, {})

            return file_data, metadata

        except Exception as e:
            print(f"[Node {self.node_id}] Error loading file {file_id} from disk: {e}")
            return None, None

    def _handle_file_transfer_request(self, message) -> Dict:
        """Handle file transfer request from another node"""
        file_id = message.get('file_id')
        requesting_node = message.get('requesting_node')

        print(f"[Node {self.node_id}] Processing file transfer request for {file_id} from {requesting_node}")

        with self.file_lock:
            # Load file from disk instead of memory
            file_data, metadata = self._load_file_from_disk(file_id)

            if file_data is not None and metadata:
                print(f"[Node {self.node_id}] Successfully serving file {metadata.get('file_name', file_id)} to {requesting_node}")

                self.metrics['total_requests_processed'] += 1
                self.metrics['total_data_transferred_bytes'] += len(file_data)

                return {
                    'status': 'OK',
                    'file_data': file_data,
                    'file_size': len(file_data),
                    'metadata': metadata
                }
            else:
                self.metrics['failed_transfers'] += 1
                return {
                    'status': 'ERROR',
                    'error': 'File not found'
                }
                
    def _handle_replication_request(self, message) -> Dict:
        """Handle file replication request"""
        file_id = message.get('file_id')
        source_node = message.get('source_node')
        source_info = message.get('source_info')

        print(f"[Node {self.node_id}] Receiving file replication from cloud storage")

        try:
            # Connect to source node and get file
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect((source_info['host'], source_info['port']))
                s.sendall(pickle.dumps({
                    'action': 'TRANSFER_FILE',
                    'file_id': file_id,
                    'requesting_node': self.node_id
                }))

                response_data = b''
                while True:
                    chunk = s.recv(8192)
                    if not chunk:
                        break
                    response_data += chunk

                response = pickle.loads(response_data)

                if response.get('status') == 'OK':
                    file_data = response['file_data']
                    metadata = response['metadata']

                    # Store the replicated file to disk
                    with self.file_lock:
                        if self._store_file_to_disk(file_id, file_data, metadata):
                            self.used_storage += len(file_data)
                            print(f"[Node {self.node_id}] Replicated file {metadata.get('file_name', file_id)} stored to disk")
                            return {'status': 'OK'}
                        else:
                            return {'status': 'ERROR', 'error': 'Failed to store replicated file to disk'}
                else:
                    return {'status': 'ERROR', 'error': response.get('error', 'Replication failed')}

        except Exception as e:
            return {'status': 'ERROR', 'error': str(e)}
            
    def _register_with_network(self):
        """Register this node with the network controller"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((self.network_host, self.network_port))
                s.sendall(pickle.dumps({
                    'action': 'REGISTER',
                    'node_id': self.node_id,
                    'host': 'localhost',
                    'port': self.port,
                    'capacity': {
                        'cpu': self.cpu_capacity,
                        'memory': self.memory_capacity,
                        'storage': self.storage_capacity,
                        'bandwidth': self.bandwidth
                    }
                }))
                response = pickle.loads(s.recv(1024))
                if response.get('status') == 'OK':
                    print(f"[Node {self.node_id}] Registered with network controller")
                    self._send_active_notification()
                else:
                    print(f"[Node {self.node_id}] Registration failed")
        except Exception as e:
            print(f"[Node {self.node_id}] Registration error: {e}")
            
    def _send_active_notification(self):
        """Send active notification to network controller"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((self.network_host, self.network_port))
                s.sendall(pickle.dumps({
                    'action': 'ACTIVE_NOTIFICATION',
                    'node_id': self.node_id
                }))
                response = pickle.loads(s.recv(1024))
        except Exception as e:
            print(f"[Node {self.node_id}] Active notification error: {e}")
            
    def _start_heartbeat(self):
        """Start heartbeat thread"""
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        
    def _heartbeat_loop(self):
        """Send periodic heartbeats to network controller"""
        while self.running:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect((self.network_host, self.network_port))
                    s.sendall(pickle.dumps({
                        'action': 'HEARTBEAT',
                        'node_id': self.node_id
                    }))
                    response = pickle.loads(s.recv(1024))
            except Exception:
                pass  # Heartbeat failures are expected occasionally
            time.sleep(2)
            
    def create_file(self, filename: str, content: str) -> bool:
        """Create a new file locally and store on disk"""
        try:
            file_id = hashlib.md5(f"{filename}_{time.time()}".encode()).hexdigest()
            file_data = content.encode('utf-8')

            metadata = {
                'file_name': filename,
                'file_size': len(file_data),
                'checksum': hashlib.md5(file_data).hexdigest(),
                'upload_time': time.time(),
                'file_id': file_id,
                'node_id': self.node_id
            }

            with self.file_lock:
                # Check storage capacity
                if self.used_storage + len(file_data) > self.storage_capacity:
                    print(f"[Node {self.node_id}] Insufficient storage space")
                    return False

                # Check actual disk space
                disk_usage = shutil.disk_usage(self.storage_dir)
                if disk_usage.free < len(file_data):
                    print(f"[Node {self.node_id}] Insufficient disk space")
                    return False

                # Store file to disk
                if self._store_file_to_disk(file_id, file_data, metadata):
                    self.used_storage += len(file_data)
                    print(f"[Node {self.node_id}] Created file: {filename} ({len(file_data)} bytes)")
                    return True
                else:
                    print(f"[Node {self.node_id}] Failed to store file to disk")
                    return False

        except Exception as e:
            print(f"[Node {self.node_id}] File creation error: {e}")
            return False
            
    def upload_file(self, filename: str) -> bool:
        """Upload a file to cloud storage"""
        try:
            # Find the file locally
            file_id = None
            file_data = None
            metadata = None

            with self.file_lock:
                for fid, meta in self.file_metadata.items():
                    if meta['file_name'] == filename:
                        file_id = fid
                        # Load file data from disk
                        file_data, metadata = self._load_file_from_disk(fid)
                        break

            if not file_id or file_data is None:
                print(f"[Node {self.node_id}] File not found locally: {filename}")
                return False
                
            # Request upload from network controller
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect((self.network_host, self.network_port))
                s.sendall(pickle.dumps({
                    'action': 'UPLOAD_FILE',
                    'node_id': self.node_id,
                    'file_id': file_id,
                    'file_name': filename,
                    'file_size': len(file_data),
                    'checksum': metadata['checksum']
                }))
                
                response = pickle.loads(s.recv(4096))
                
                if response.get('status') == 'OK':
                    # Notify upload complete
                    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s2.settimeout(5)
                    s2.connect((self.network_host, self.network_port))
                    s2.sendall(pickle.dumps({
                        'action': 'UPLOAD_COMPLETE',
                        'node_id': self.node_id,
                        'file_id': file_id
                    }))
                    s2.close()
                    
                    print(f"[Node {self.node_id}] File uploaded successfully: {filename}")
                    return True
                else:
                    print(f"[Node {self.node_id}] Upload failed: {response.get('error', 'Unknown error')}")
                    return False
                    
        except Exception as e:
            print(f"[Node {self.node_id}] Upload error: {e}")
            return False

    def download_file(self, file_name: str) -> bool:
        """Download a file from the cloud storage network with enhanced fault tolerance"""
        print(f"[Node {self.node_id}] Downloading {file_name} from cloud storage...")
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(20)  # Increased timeout for better reliability
                    s.connect((self.network_host, self.network_port))
                    s.sendall(pickle.dumps({
                        'action': 'DOWNLOAD_FILE',
                        'node_id': self.node_id,
                        'file_name': file_name
                    }))
                    
                    response_data = b''
                    
                    while True:
                        try:
                            chunk = s.recv(16384)  # Larger buffer for better performance
                            if not chunk:
                                break
                            response_data += chunk
                        except socket.timeout:
                            if attempt < max_retries - 1:
                                print(f"[Node {self.node_id}] Download timeout, retrying... (attempt {attempt + 1}/{max_retries})")
                                break
                            else:
                                raise
                    
                    try:
                        response = pickle.loads(response_data)
                    except (pickle.UnpicklingError, EOFError) as e:
                        if attempt < max_retries - 1:
                            print(f"[Node {self.node_id}] Invalid response data, retrying... (attempt {attempt + 1}/{max_retries})")
                            time.sleep(retry_delay)
                            continue
                        else:
                            print(f"[Node {self.node_id}] Failed to parse response after {max_retries} attempts: {e}")
                            return False
                    
                    if response.get('status') == 'OK':
                        file_data = response['file_data']
                        file_size = response['file_size']
                        source_node = response.get('source_node', 'unknown')
                        
                        # Verify downloaded data integrity
                        if len(file_data) != file_size:
                            if attempt < max_retries - 1:
                                print(f"[Node {self.node_id}] File size mismatch, retrying... (attempt {attempt + 1}/{max_retries})")
                                time.sleep(retry_delay)
                                continue
                            else:
                                print(f"[Node {self.node_id}] File size mismatch after {max_retries} attempts")
                                return False
                        
                        try:
                            # Generate file_id and create proper metadata
                            file_id = response.get('file_id') or hashlib.md5(f"{file_name}_{time.time()}".encode()).hexdigest()
                            checksum = hashlib.md5(file_data).hexdigest()
                            
                            metadata = {
                                'file_name': file_name,
                                'file_size': len(file_data),
                                'checksum': checksum,
                                'upload_time': time.time(),
                                'file_id': file_id,
                                'node_id': self.node_id,
                                'source_node': source_node
                            }
                            
                            # Use proper storage method to save file and update registry
                            with self.file_lock:
                                if self._store_file_to_disk(file_id, file_data, metadata):
                                    self.used_storage += len(file_data)
                                    print(f"[Node {self.node_id}] File {file_name} downloaded successfully from {source_node} (attempt {attempt + 1})")
                                    return True
                                else:
                                    print(f"[Node {self.node_id}] Error storing downloaded file to disk")
                                    return False
                        except Exception as save_error:
                            print(f"[Node {self.node_id}] Error saving file: {save_error}")
                            return False
                    else:
                        error_msg = response.get('error', 'Unknown error')
                        if 'all storage nodes failed' in error_msg.lower() or 'nodes offline' in error_msg.lower():
                            if attempt < max_retries - 1:
                                print(f"[Node {self.node_id}] Storage nodes unavailable, retrying... (attempt {attempt + 1}/{max_retries})")
                                time.sleep(retry_delay * 2)  # Longer delay for node failures
                                continue
                            else:
                                print(f"[Node {self.node_id}] Download failed after {max_retries} attempts: {error_msg}")
                                return False
                        else:
                            print(f"[Node {self.node_id}] Download failed: {error_msg}")
                            return False
                        
            except ConnectionRefusedError:
                if attempt < max_retries - 1:
                    print(f"[Node {self.node_id}] Network controller unavailable, retrying... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"[Node {self.node_id}] Network controller unavailable after {max_retries} attempts")
                    return False
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[Node {self.node_id}] Download error, retrying... (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"[Node {self.node_id}] Download failed after {max_retries} attempts: {e}")
                    return False
        
        return False

    def _store_file_to_disk(self, file_id: str, file_data: bytes, metadata: Dict) -> bool:
        """Store file data and metadata to persistent disk storage"""
        try:
            # Create file path
            file_path = os.path.join(self.storage_dir, f"{file_id}.dat")

            # Write file data to disk
            with open(file_path, 'wb') as f:
                f.write(file_data)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk

            # Update file index
            self.file_index[file_id] = file_path

            # Update metadata
            self.file_metadata[file_id] = metadata

            # Save metadata to JSON
            self._save_metadata()

            print(f"[Node {self.node_id}] Stored file {metadata.get('file_name', file_id)} to disk ({len(file_data)} bytes)")
            return True

        except IOError as e:
            print(f"[Node {self.node_id}] Disk I/O error: {e}")
            return False
        except Exception as e:
            print(f"[Node {self.node_id}] Storage error: {e}")
            return False
            
    def list_local_files(self) -> List[Dict]:
        """List all local files stored on disk"""
        with self.file_lock:
            files = []
            for file_id, metadata in self.file_metadata.items():
                # Verify file still exists on disk
                if file_id in self.file_index:
                    file_path = self.file_index[file_id]
                    if os.path.exists(file_path):
                        # Get actual file size from disk
                        actual_size = os.path.getsize(file_path)
                        files.append({
                            'file_id': file_id,
                            'file_name': metadata['file_name'],
                            'file_size': actual_size,
                            'upload_time': metadata['upload_time']
                        })
            return files
            
    def list_cloud_files(self) -> List[Dict]:
        """List all files in cloud storage"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((self.network_host, self.network_port))
                s.sendall(pickle.dumps({
                    'action': 'LIST_CLOUD_FILES',
                    'node_id': self.node_id
                }))
                
                response = pickle.loads(s.recv(8192))
                
                if response.get('status') == 'OK':
                    return response.get('files', [])
                else:
                    print(f"[Node {self.node_id}] Failed to list cloud files: {response.get('error', 'Unknown error')}")
                    return []
                    
        except Exception as e:
            print(f"[Node {self.node_id}] List cloud files error: {e}")
            return []
            
    def get_storage_utilization(self) -> Dict:
        """Get storage utilization information based on actual disk usage"""
        with self.file_lock:
            # Calculate actual disk usage
            actual_used = 0
            for file_id in self.file_index:
                file_path = self.file_index[file_id]
                if os.path.exists(file_path):
                    actual_used += os.path.getsize(file_path)

            # Update used_storage to match actual disk usage
            self.used_storage = actual_used

            return {
                'total_bytes': self.storage_capacity,
                'used_bytes': self.used_storage,
                'available_bytes': self.storage_capacity - self.used_storage,
                'utilization_percent': (self.used_storage / self.storage_capacity) * 100 if self.storage_capacity > 0 else 0,
                'files_stored': len(self.file_index),
                'active_transfers': self.metrics['current_active_transfers']
            }
            
    def get_network_utilization(self) -> Dict:
        """Get network utilization information"""
        # Simplified network utilization calculation
        return {
            'bandwidth_bps': self.bandwidth * 1024 * 1024,  # Convert Mbps to bps
            'utilization_percent': random.uniform(10, 30),  # Simulated utilization
            'latency_ms': self.network_info.latency
        }
        
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        return self.metrics.copy()
        
    def shutdown(self):
        """Shutdown the node and ensure all data is persisted"""
        print(f"[Node {self.node_id}] Shutting down...")
        self.running = False

        # Save metadata one final time before shutdown
        with self.file_lock:
            self._save_metadata()
            print(f"[Node {self.node_id}] Saved metadata for {len(self.file_metadata)} files")

        if self.server_socket:
            self.server_socket.close()

        print(f"[Node {self.node_id}] Shutdown complete - all files persisted to disk")
