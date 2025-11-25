import grpc
import time
import random
import hashlib
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import threading
import cloud_storage_pb2
import cloud_storage_pb2_grpc

class NodeStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    RECOVERING = "recovering"

@dataclass
class NodeHealth:
    node_id: str
    status: NodeStatus
    failure_count: int = 0
    last_failure: float = 0
    last_success: float = 0
    circuit_breaker_until: float = 0

class FaultTolerantDownloadClient:
    """
    Fault-tolerant client that can download files even when original nodes are offline.
    Implements retry logic, circuit breakers, and automatic failover to replica nodes.
    """
    
    def __init__(self, network_host='localhost', network_port=5000):
        self.network_host = network_host
        self.network_port = network_port
        self.node_health = {}  # node_id -> NodeHealth
        self.health_lock = threading.Lock()
        
        # Fault tolerance configuration
        self.max_retries = 3
        self.retry_delay_base = 1.0  # Base delay for exponential backoff
        self.circuit_breaker_threshold = 3  # Failures before circuit breaker opens
        self.circuit_breaker_timeout = 30.0  # Seconds to wait before trying again
        self.connection_timeout = 10.0
        
    def _get_node_health(self, node_id: str) -> NodeHealth:
        """Get or create node health tracking"""
        with self.health_lock:
            if node_id not in self.node_health:
                self.node_health[node_id] = NodeHealth(node_id, NodeStatus.HEALTHY)
            return self.node_health[node_id]
    
    def _update_node_health(self, node_id: str, success: bool):
        """Update node health based on operation result"""
        with self.health_lock:
            health = self._get_node_health(node_id)
            current_time = time.time()
            
            if success:
                health.last_success = current_time
                health.failure_count = max(0, health.failure_count - 1)
                
                if health.status == NodeStatus.FAILED and health.failure_count == 0:
                    health.status = NodeStatus.RECOVERING
                    print(f"[FaultTolerant] Node {node_id} is recovering")
                elif health.status == NodeStatus.RECOVERING:
                    health.status = NodeStatus.HEALTHY
                    print(f"[FaultTolerant] Node {node_id} is healthy again")
            else:
                health.last_failure = current_time
                health.failure_count += 1
                
                if health.failure_count >= self.circuit_breaker_threshold:
                    health.status = NodeStatus.FAILED
                    health.circuit_breaker_until = current_time + self.circuit_breaker_timeout
                    print(f"[FaultTolerant] Node {node_id} marked as failed (circuit breaker activated)")
                elif health.failure_count > 1:
                    health.status = NodeStatus.DEGRADED
                    print(f"[FaultTolerant] Node {node_id} is degraded ({health.failure_count} failures)")
    
    def _is_node_available(self, node_id: str) -> bool:
        """Check if a node is available for operations"""
        health = self._get_node_health(node_id)
        current_time = time.time()
        
        if health.status == NodeStatus.FAILED:
            if current_time < health.circuit_breaker_until:
                return False
            else:
                # Circuit breaker timeout expired, allow retry
                health.status = NodeStatus.RECOVERING
                return True
        
        return health.status in [NodeStatus.HEALTHY, NodeStatus.DEGRADED, NodeStatus.RECOVERING]
    
    def _get_available_replicas(self, file_id: str, requesting_node: str) -> List[Dict]:
        """Get list of available replica nodes for a file"""
        try:
            # Connect to network controller to get replica information
            channel = grpc.insecure_channel(f'{self.network_host}:{self.network_port}')
            stub = cloud_storage_pb2_grpc.FileManagementStub(channel)
            
            request = cloud_storage_pb2.ReplicaRequest(
                file_id=file_id,
                requesting_node=requesting_node
            )
            
            response = stub.GetAvailableReplicas(request)
            channel.close()
            
            if response.status == 'OK':
                available_nodes = []
                for node_info in response.available_nodes:
                    if self._is_node_available(node_info.node_id):
                        available_nodes.append({
                            'node_id': node_info.node_id,
                            'host': node_info.host,
                            'port': node_info.port,
                            'is_primary': node_info.node_id == response.primary_node
                        })
                
                # Sort by preference: primary first, then by health
                available_nodes.sort(key=lambda x: (
                    not x['is_primary'],  # Primary nodes first
                    self._get_node_health(x['node_id']).failure_count  # Healthier nodes first
                ))
                
                return available_nodes
            else:
                print(f"[FaultTolerant] Failed to get replicas for {file_id}")
                return []
                
        except Exception as e:
            print(f"[FaultTolerant] Error getting replicas: {e}")
            return []
    
    def _download_from_node(self, node_info: Dict, file_id: str, requesting_node: str) -> Tuple[bool, Optional[bytes], Optional[str]]:
        """Attempt to download file from a specific node"""
        node_id = node_info['node_id']
        host = node_info['host']
        port = node_info['port']
        
        try:
            print(f"[FaultTolerant] Attempting download from node {node_id} ({host}:{port})")
            
            # Create gRPC connection with timeout
            channel = grpc.insecure_channel(f'{host}:{port}')
            stub = cloud_storage_pb2_grpc.FileTransferStub(channel)
            
            # Set deadline for the request
            deadline = time.time() + self.connection_timeout
            
            request = cloud_storage_pb2.TransferFileRequest(
                file_id=file_id,
                requesting_node=requesting_node
            )
            
            response = stub.TransferFile(request, timeout=self.connection_timeout)
            channel.close()
            
            if response.status == 'OK':
                file_data = response.file_data
                file_name = response.metadata.file_name
                
                # Verify file integrity
                expected_checksum = response.metadata.checksum
                if expected_checksum:
                    actual_checksum = hashlib.md5(file_data).hexdigest()
                    if actual_checksum != expected_checksum:
                        print(f"[FaultTolerant] Checksum mismatch from node {node_id}")
                        return False, None, "Checksum verification failed"
                
                print(f"[FaultTolerant] Successfully downloaded from node {node_id}")
                self._update_node_health(node_id, True)
                return True, file_data, file_name
            else:
                error_msg = response.error or "Unknown error"
                print(f"[FaultTolerant] Download failed from node {node_id}: {error_msg}")
                self._update_node_health(node_id, False)
                return False, None, error_msg
                
        except grpc.RpcError as e:
            error_msg = f"gRPC error: {e.code()} - {e.details()}"
            print(f"[FaultTolerant] gRPC error from node {node_id}: {error_msg}")
            self._update_node_health(node_id, False)
            return False, None, error_msg
        except Exception as e:
            error_msg = f"Connection error: {str(e)}"
            print(f"[FaultTolerant] Connection error to node {node_id}: {error_msg}")
            self._update_node_health(node_id, False)
            return False, None, error_msg
    
    def _stream_download_from_node(self, node_info: Dict, file_id: str, requesting_node: str) -> Tuple[bool, Optional[bytes], Optional[str]]:
        """Attempt to download file using streaming from a specific node"""
        node_id = node_info['node_id']
        host = node_info['host']
        port = node_info['port']
        
        try:
            print(f"[FaultTolerant] Attempting streaming download from node {node_id}")
            
            # Create gRPC connection for streaming
            channel = grpc.insecure_channel(f'{host}:{port}')
            stub = cloud_storage_pb2_grpc.FileManagementStub(channel)
            
            request = cloud_storage_pb2.StreamDownloadRequest(
                file_id=file_id,
                node_id=requesting_node,
                start_chunk=0,
                end_chunk=0  # Download all chunks
            )
            
            chunks = []
            total_bytes = 0
            file_name = None
            
            # Stream chunks with timeout handling
            for chunk in stub.StreamDownload(request, timeout=self.connection_timeout * 3):
                if chunk.file_name == 'error':
                    error_msg = chunk.data.decode()
                    print(f"[FaultTolerant] Streaming error from node {node_id}: {error_msg}")
                    channel.close()
                    self._update_node_health(node_id, False)
                    return False, None, error_msg
                
                if file_name is None:
                    file_name = chunk.file_name
                
                # Verify chunk integrity
                if chunk.checksum:
                    actual_checksum = hashlib.md5(chunk.data).hexdigest()
                    if actual_checksum != chunk.checksum:
                        print(f"[FaultTolerant] Chunk {chunk.chunk_number} checksum mismatch from node {node_id}")
                        channel.close()
                        self._update_node_health(node_id, False)
                        return False, None, "Chunk checksum verification failed"
                
                chunks.append((chunk.chunk_number, chunk.data))
                total_bytes += len(chunk.data)
                
                if chunk.is_last_chunk:
                    break
            
            channel.close()
            
            if not chunks:
                print(f"[FaultTolerant] No chunks received from node {node_id}")
                self._update_node_health(node_id, False)
                return False, None, "No data received"
            
            # Sort chunks and reassemble file
            chunks.sort(key=lambda x: x[0])
            file_data = b''.join(chunk[1] for chunk in chunks)
            
            print(f"[FaultTolerant] Successfully streamed {total_bytes} bytes from node {node_id}")
            self._update_node_health(node_id, True)
            return True, file_data, file_name
            
        except grpc.RpcError as e:
            error_msg = f"Streaming gRPC error: {e.code()} - {e.details()}"
            print(f"[FaultTolerant] {error_msg}")
            self._update_node_health(node_id, False)
            return False, None, error_msg
        except Exception as e:
            error_msg = f"Streaming error: {str(e)}"
            print(f"[FaultTolerant] {error_msg}")
            self._update_node_health(node_id, False)
            return False, None, error_msg
    
    def download_file_with_fault_tolerance(
        self, 
        file_id: str = None, 
        file_name: str = None, 
        requesting_node: str = "fault_tolerant_client",
        save_path: str = None,
        use_streaming: bool = True
    ) -> Dict:
        """
        Download a file with full fault tolerance.
        Tries multiple replica nodes and implements retry logic.
        """
        if not file_id and not file_name:
            return {'status': 'ERROR', 'error': 'Must specify either file_id or file_name'}
        
        # If we only have file_name, we need to get file_id from network controller
        if not file_id:
            # This would require additional network controller API to lookup by name
            # For now, assume we have file_id
            return {'status': 'ERROR', 'error': 'file_id is required for fault-tolerant download'}
        
        print(f"[FaultTolerant] Starting fault-tolerant download for file {file_id}")
        
        # Get available replica nodes
        available_nodes = self._get_available_replicas(file_id, requesting_node)
        
        if not available_nodes:
            return {
                'status': 'ERROR', 
                'error': 'No available replica nodes found'
            }
        
        print(f"[FaultTolerant] Found {len(available_nodes)} available replica nodes")
        
        last_error = None
        
        # Try each available node with retry logic
        for node_info in available_nodes:
            node_id = node_info['node_id']
            
            # Skip nodes that are circuit-broken
            if not self._is_node_available(node_id):
                print(f"[FaultTolerant] Skipping node {node_id} (circuit breaker active)")
                continue
            
            # Retry logic for this node
            for attempt in range(self.max_retries):
                try:
                    if attempt > 0:
                        # Exponential backoff
                        delay = self.retry_delay_base * (2 ** (attempt - 1))
                        jitter = random.uniform(0, delay * 0.1)  # Add jitter
                        print(f"[FaultTolerant] Retrying node {node_id} in {delay + jitter:.2f}s (attempt {attempt + 1})")
                        time.sleep(delay + jitter)
                    
                    # Try download (streaming or regular)
                    if use_streaming:
                        success, file_data, downloaded_file_name = self._stream_download_from_node(
                            node_info, file_id, requesting_node
                        )
                    else:
                        success, file_data, downloaded_file_name = self._download_from_node(
                            node_info, file_id, requesting_node
                        )
                    
                    if success and file_data:
                        # Save file if path specified
                        if save_path:
                            try:
                                with open(save_path, 'wb') as f:
                                    f.write(file_data)
                                print(f"[FaultTolerant] File saved to {save_path}")
                            except Exception as e:
                                return {
                                    'status': 'ERROR',
                                    'error': f'Failed to save file: {str(e)}'
                                }
                        
                        return {
                            'status': 'OK',
                            'file_data': file_data,
                            'file_name': downloaded_file_name or file_name,
                            'source_node': node_id,
                            'bytes_downloaded': len(file_data),
                            'attempts_made': attempt + 1,
                            'nodes_tried': available_nodes.index(node_info) + 1
                        }
                    else:
                        last_error = downloaded_file_name  # Error message is in file_name field
                        if attempt == self.max_retries - 1:
                            print(f"[FaultTolerant] All retries exhausted for node {node_id}")
                            break
                        
                except Exception as e:
                    last_error = str(e)
                    print(f"[FaultTolerant] Unexpected error with node {node_id}: {e}")
                    break
        
        # All nodes failed
        return {
            'status': 'ERROR',
            'error': f'All replica nodes failed. Last error: {last_error}',
            'nodes_tried': len(available_nodes),
            'available_nodes': [n['node_id'] for n in available_nodes]
        }
    
    def get_node_health_status(self) -> Dict[str, Dict]:
        """Get health status of all tracked nodes"""
        with self.health_lock:
            status = {}
            for node_id, health in self.node_health.items():
                status[node_id] = {
                    'status': health.status.value,
                    'failure_count': health.failure_count,
                    'last_failure': health.last_failure,
                    'last_success': health.last_success,
                    'circuit_breaker_until': health.circuit_breaker_until,
                    'is_available': self._is_node_available(node_id)
                }
            return status
    
    def reset_node_health(self, node_id: str = None):
        """Reset health status for a specific node or all nodes"""
        with self.health_lock:
            if node_id:
                if node_id in self.node_health:
                    self.node_health[node_id] = NodeHealth(node_id, NodeStatus.HEALTHY)
                    print(f"[FaultTolerant] Reset health for node {node_id}")
            else:
                self.node_health.clear()
                print(f"[FaultTolerant] Reset health for all nodes")

# Convenience function for easy usage
def download_file_fault_tolerant(
    file_id: str,
    save_path: str,
    network_host: str = 'localhost',
    network_port: int = 5000,
    requesting_node: str = "client",
    use_streaming: bool = True
) -> Dict:
    """
    Convenience function to download a file with fault tolerance.
    
    Args:
        file_id: ID of the file to download
        save_path: Path where to save the downloaded file
        network_host: Network controller host
        network_port: Network controller port
        requesting_node: ID of the requesting node
        use_streaming: Whether to use streaming download
    
    Returns:
        Dict with status and result information
    """
    client = FaultTolerantDownloadClient(network_host, network_port)
    return client.download_file_with_fault_tolerance(
        file_id=file_id,
        save_path=save_path,
        requesting_node=requesting_node,
        use_streaming=use_streaming
    )
