import grpc
from concurrent import futures
import time
import threading
import asyncio
import hashlib
import os
from typing import Dict, List, Optional, Iterator
import cloud_storage_pb2
import cloud_storage_pb2_grpc

class NodeManagementService(cloud_storage_pb2_grpc.NodeManagementServicer):
    def __init__(self, network_controller):
        self.controller = network_controller
    
    def RegisterNode(self, request, context):
        """Handle node registration"""
        try:
            with self.controller.lock:
                node_id = request.node_id
                if node_id not in self.controller.nodes:
                    print(f"[Network] Node {node_id} registered (came ONLINE)")
                
                self.controller.nodes[node_id] = {
                    'host': request.host,
                    'port': request.port,
                    'capacity': {
                        'cpu': request.capacity.cpu,
                        'memory': request.capacity.memory,
                        'storage': request.capacity.storage,
                        'bandwidth': request.capacity.bandwidth
                    },
                    'network_info': {
                        'ip_address': request.network_info.ip_address,
                        'mac_address': request.network_info.mac_address,
                        'interface': request.network_info.interface,
                        'subnet_mask': request.network_info.subnet_mask,
                        'gateway': request.network_info.gateway
                    },
                    'last_seen': 0,
                    'status': 'registered'
                }
                
                return cloud_storage_pb2.RegisterNodeResponse(status='OK')
        except Exception as e:
            return cloud_storage_pb2.RegisterNodeResponse(
                status='ERROR',
                error=str(e)
            )
    
    def SendHeartbeat(self, request, context):
        """Handle heartbeat from node"""
        try:
            with self.controller.lock:
                node_id = request.node_id
                if node_id in self.controller.nodes:
                    if self.controller.nodes[node_id]['status'] == 'registered':
                        print(f"[Network] Node {node_id} is now ACTIVE")
                        self.controller.nodes[node_id]['status'] = 'active'
                    self.controller.nodes[node_id]['last_seen'] = time.time()
                    return cloud_storage_pb2.HeartbeatResponse(status='ACK')
                else:
                    return cloud_storage_pb2.HeartbeatResponse(
                        status='ERROR',
                        error='Node not registered'
                    )
        except Exception as e:
            return cloud_storage_pb2.HeartbeatResponse(
                status='ERROR',
                error=str(e)
            )
    
    def NotifyActive(self, request, context):
        """Handle active notification from node"""
        try:
            with self.controller.lock:
                node_id = request.node_id
                if node_id in self.controller.nodes:
                    if self.controller.nodes[node_id]['status'] != 'active':
                        print(f"[Network] Node {node_id} is now ACTIVE")
                    self.controller.nodes[node_id]['status'] = 'active'
                    self.controller.nodes[node_id]['last_seen'] = time.time()
                    return cloud_storage_pb2.ActiveNotificationResponse(status='ACK')
        except Exception as e:
            pass
        return cloud_storage_pb2.ActiveNotificationResponse(status='ERROR')

class FileManagementService(cloud_storage_pb2_grpc.FileManagementServicer):
    def __init__(self, network_controller):
        self.controller = network_controller
        self.active_uploads = {}  # Track active streaming uploads
        self.upload_lock = threading.Lock()
    
    def UploadFile(self, request, context):
        """Handle file upload request"""
        try:
            response_data = self.controller._handle_file_upload({
                'file_id': request.file_id,
                'file_name': request.file_name,
                'file_size': request.file_size,
                'node_id': request.node_id,
                'checksum': request.checksum
            })
            
            if response_data['status'] == 'OK':
                # Convert node_info to protobuf format
                node_info_pb = {}
                for node_id, info in response_data['node_info'].items():
                    node_info_pb[node_id] = cloud_storage_pb2.NodeInfo(
                        node_id=node_id,
                        host=info['host'],
                        port=info['port'],
                        capacity=cloud_storage_pb2.NodeCapacity(
                            cpu=info['capacity']['cpu'],
                            memory=info['capacity']['memory'],
                            storage=info['capacity']['storage'],
                            bandwidth=info['capacity']['bandwidth']
                        ),
                        status=info['status']
                    )
                
                return cloud_storage_pb2.UploadFileResponse(
                    status='OK',
                    primary_node=response_data['primary_node'],
                    replica_nodes=response_data['replica_nodes'],
                    node_info=node_info_pb
                )
            else:
                return cloud_storage_pb2.UploadFileResponse(
                    status='ERROR',
                    error=response_data['error']
                )
        except Exception as e:
            return cloud_storage_pb2.UploadFileResponse(
                status='ERROR',
                error=str(e)
            )

    def StreamUpload(self, request_iterator, context):
        """Handle streaming file upload (client-streaming RPC)"""
        try:
            file_chunks = []
            file_metadata = None
            bytes_received = 0
            
            print(f"[Network] Starting streaming upload...")
            
            # Collect all chunks from the stream
            for chunk in request_iterator:
                if file_metadata is None:
                    file_metadata = {
                        'file_id': chunk.file_id,
                        'file_name': chunk.file_name,
                        'total_size': chunk.total_size,
                        'node_id': chunk.node_id,
                        'total_chunks': chunk.total_chunks
                    }
                    print(f"[Network] Receiving streaming upload for {chunk.file_name} ({chunk.total_size} bytes)")
                
                file_chunks.append({
                    'chunk_number': chunk.chunk_number,
                    'data': chunk.data,
                    'checksum': chunk.checksum,
                    'is_last_chunk': chunk.is_last_chunk
                })
                
                bytes_received += len(chunk.data)
                
                # Progress reporting
                if chunk.chunk_number % 10 == 0 or chunk.is_last_chunk:
                    progress = (bytes_received / file_metadata['total_size']) * 100
                    print(f"[Network] Upload progress: {progress:.1f}% ({bytes_received}/{file_metadata['total_size']} bytes)")
                
                if chunk.is_last_chunk:
                    break
            
            if not file_metadata:
                return cloud_storage_pb2.StreamUploadResponse(
                    status='ERROR',
                    error='No chunks received'
                )
            
            # Reassemble file data from chunks
            file_chunks.sort(key=lambda x: x['chunk_number'])
            file_data = b''.join(chunk['data'] for chunk in file_chunks)
            
            # Verify file integrity
            actual_checksum = hashlib.md5(file_data).hexdigest()
            
            # Handle the upload through network controller
            upload_response = self.controller._handle_file_upload({
                'file_id': file_metadata['file_id'],
                'file_name': file_metadata['file_name'],
                'file_size': len(file_data),
                'node_id': file_metadata['node_id'],
                'checksum': actual_checksum
            })
            
            if upload_response['status'] == 'OK':
                # Store file data to primary and replica nodes
                replica_nodes = upload_response.get('replica_nodes', [])
                
                print(f"[Network] Streaming upload completed for {file_metadata['file_name']}")
                
                return cloud_storage_pb2.StreamUploadResponse(
                    status='OK',
                    file_id=file_metadata['file_id'],
                    replica_nodes=replica_nodes,
                    bytes_received=bytes_received
                )
            else:
                return cloud_storage_pb2.StreamUploadResponse(
                    status='ERROR',
                    error=upload_response.get('error', 'Upload failed')
                )
                
        except Exception as e:
            print(f"[Network] Streaming upload error: {e}")
            return cloud_storage_pb2.StreamUploadResponse(
                status='ERROR',
                error=str(e)
            )

    def StreamDownload(self, request, context):
        """Handle streaming file download (server-streaming RPC) with improved fault tolerance"""
        try:
            file_id = request.file_id
            requesting_node = request.node_id
            start_chunk = request.start_chunk
            end_chunk = request.end_chunk
            
            print(f"[Network] Starting streaming download for file {file_id}")
            
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    # Get file information with fault tolerance
                    download_response = self.controller._handle_file_download({
                        'node_id': requesting_node,
                        'file_id': file_id
                    })
                    
                    if download_response['status'] == 'OK':
                        break  # Success, exit retry loop
                    else:
                        retry_count += 1
                        if retry_count < max_retries:
                            print(f"[Network] Download attempt {retry_count} failed, retrying... ({download_response.get('error', 'Unknown error')})")
                            time.sleep(1)  # Brief delay before retry
                            continue
                        else:
                            # Final failure after all retries
                            yield cloud_storage_pb2.FileChunk(
                                file_id=file_id,
                                file_name='error',
                                total_size=0,
                                chunk_number=0,
                                total_chunks=1,
                                data=f"Download failed after {max_retries} attempts: {download_response.get('error', 'All replica nodes unavailable')}".encode(),
                                checksum='',
                                is_last_chunk=True,
                                node_id=requesting_node
                            )
                            return
                            
                except Exception as e:
                    retry_count += 1
                    if retry_count < max_retries:
                        print(f"[Network] Download attempt {retry_count} failed with exception, retrying... ({str(e)})")
                        time.sleep(1)
                        continue
                    else:
                        yield cloud_storage_pb2.FileChunk(
                            file_id=file_id,
                            file_name='error',
                            total_size=0,
                            chunk_number=0,
                            total_chunks=1,
                            data=f"Download failed after {max_retries} attempts: {str(e)}".encode(),
                            checksum='',
                            is_last_chunk=True,
                            node_id=requesting_node
                        )
                        return
            
            file_data = download_response['file_data']
            file_name = download_response['file_name']
            file_size = len(file_data)
            source_node = download_response['source_node']
            
            print(f"[Network] Successfully retrieved {file_name} from {source_node} for streaming download")
            
            # Calculate chunk size (1MB chunks for streaming)
            chunk_size = 1024 * 1024  # 1MB
            total_chunks = (file_size + chunk_size - 1) // chunk_size
            
            # Apply chunk range if specified
            actual_start = max(0, start_chunk) if start_chunk > 0 else 0
            actual_end = min(total_chunks - 1, end_chunk) if end_chunk > 0 else total_chunks - 1
            
            print(f"[Network] Streaming {file_name} in chunks {actual_start}-{actual_end} ({total_chunks} total) from {source_node}")
            
            for chunk_num in range(actual_start, actual_end + 1):
                try:
                    start_byte = chunk_num * chunk_size
                    end_byte = min(start_byte + chunk_size, file_size)
                    chunk_data = file_data[start_byte:end_byte]
                    
                    chunk_checksum = hashlib.md5(chunk_data).hexdigest()
                    is_last = (chunk_num == actual_end)
                    
                    yield cloud_storage_pb2.FileChunk(
                        file_id=file_id,
                        file_name=file_name,
                        total_size=file_size,
                        chunk_number=chunk_num,
                        total_chunks=total_chunks,
                        data=chunk_data,
                        checksum=chunk_checksum,
                        is_last_chunk=is_last,
                        node_id=requesting_node
                    )
                    
                    # Progress reporting
                    if chunk_num % 10 == 0 or is_last:
                        progress = ((chunk_num - actual_start + 1) / (actual_end - actual_start + 1)) * 100
                        print(f"[Network] Download progress: {progress:.1f}% (chunk {chunk_num}/{actual_end}) from {source_node}")
                    
                    time.sleep(0.005)  # Smaller delay for faster streaming
                    
                except Exception as chunk_error:
                    print(f"[Network] Error streaming chunk {chunk_num}: {chunk_error}")
                    # Send error chunk and terminate
                    yield cloud_storage_pb2.FileChunk(
                        file_id=file_id,
                        file_name='error',
                        total_size=0,
                        chunk_number=chunk_num,
                        total_chunks=1,
                        data=f"Chunk {chunk_num} streaming error: {str(chunk_error)}".encode(),
                        checksum='',
                        is_last_chunk=True,
                        node_id=requesting_node
                    )
                    return
            
            print(f"[Network] Streaming download completed for {file_name} from {source_node}")
            
        except Exception as e:
            print(f"[Network] Streaming download error: {e}")
            # Send error chunk
            yield cloud_storage_pb2.FileChunk(
                file_id=file_id or 'unknown',
                file_name='error',
                total_size=0,
                chunk_number=0,
                total_chunks=1,
                data=f"Streaming download failed: {str(e)}".encode(),
                checksum='',
                is_last_chunk=True,
                node_id=requesting_node
            )
    
    def GetAvailableReplicas(self, request, context):
        """Handle request to get available replica nodes for a file"""
        try:
            response_data = self.controller._handle_get_available_replicas({
                'file_id': request.file_id,
                'node_id': request.requesting_node
            })
            
            if response_data['status'] == 'OK':
                available_nodes = []
                for node_info in response_data['available_nodes']:
                    available_nodes.append(cloud_storage_pb2.NodeInfo(
                        node_id=node_info.get('node_id', ''),
                        host=node_info['host'],
                        port=node_info['port'],
                        status=node_info['status']
                    ))
                
                return cloud_storage_pb2.ReplicaResponse(
                    status='OK',
                    available_nodes=available_nodes,
                    primary_node=response_data.get('primary_node', '')
                )
            else:
                return cloud_storage_pb2.ReplicaResponse(
                    status='ERROR'
                )
        except Exception as e:
            return cloud_storage_pb2.ReplicaResponse(status='ERROR')
    
    def DownloadFile(self, request, context):
        """Handle file download request"""
        try:
            response_data = self.controller._handle_file_download({
                'node_id': request.node_id,
                'file_id': request.file_id if request.file_id else None,
                'file_name': request.file_name if request.file_name else None
            })
            
            if response_data['status'] == 'OK':
                node_info = response_data['node_info']
                return cloud_storage_pb2.DownloadFileResponse(
                    status='OK',
                    file_id=response_data['file_id'],
                    file_name=response_data['file_name'],
                    file_size=response_data['file_size'],
                    source_node=response_data['source_node'],
                    node_info=cloud_storage_pb2.NodeInfo(
                        node_id=response_data['source_node'],
                        host=node_info['host'],
                        port=node_info['port'],
                        status=node_info['status']
                    )
                )
            else:
                return cloud_storage_pb2.DownloadFileResponse(
                    status='ERROR',
                    error=response_data['error']
                )
        except Exception as e:
            return cloud_storage_pb2.DownloadFileResponse(
                status='ERROR',
                error=str(e)
            )
    
    def ListFiles(self, request, context):
        """Handle list files request"""
        try:
            files = self.controller.list_files()
            file_infos = []
            
            for file_data in files:
                file_infos.append(cloud_storage_pb2.FileInfo(
                    file_id=file_data['file_id'],
                    file_name=file_data['file_name'],
                    file_size=file_data['file_size'],
                    status=file_data['status'],
                    primary_nodes=file_data['primary_nodes'],
                    replica_nodes=file_data['replica_nodes'],
                    upload_time=int(file_data['upload_time']),
                    checksum=file_data.get('checksum', '')
                ))
            
            return cloud_storage_pb2.ListFilesResponse(
                status='OK',
                files=file_infos
            )
        except Exception as e:
            return cloud_storage_pb2.ListFilesResponse(status='ERROR')
    
    def NotifyUploadComplete(self, request, context):
        """Handle upload completion notification"""
        try:
            response_data = self.controller._handle_upload_complete({
                'file_id': request.file_id,
                'node_id': request.node_id
            })
            
            return cloud_storage_pb2.UploadCompleteResponse(
                status=response_data['status'],
                error=response_data.get('error', '')
            )
        except Exception as e:
            return cloud_storage_pb2.UploadCompleteResponse(
                status='ERROR',
                error=str(e)
            )

class FileTransferService(cloud_storage_pb2_grpc.FileTransferServicer):
    def __init__(self, storage_node):
        self.node = storage_node
        self.transfer_lock = threading.Lock()
    
    def TransferFile(self, request, context):
        """Handle file transfer request from another node"""
        try:
            file_id = request.file_id
            requesting_node = request.requesting_node
            
            # Load file from disk
            file_data, metadata = self.node._load_file_from_disk(file_id)
            
            if file_data is not None and metadata:
                return cloud_storage_pb2.TransferFileResponse(
                    status='OK',
                    file_data=file_data,
                    metadata=cloud_storage_pb2.FileMetadata(
                        file_name=metadata['file_name'],
                        file_size=metadata['file_size'],
                        checksum=metadata['checksum'],
                        upload_time=int(metadata['upload_time'])
                    )
                )
            else:
                return cloud_storage_pb2.TransferFileResponse(
                    status='ERROR',
                    error='File not found'
                )
        except Exception as e:
            return cloud_storage_pb2.TransferFileResponse(
                status='ERROR',
                error=str(e)
            )

    def StreamTransfer(self, request_iterator, context):
        """Handle streaming file transfer between nodes"""
        try:
            file_chunks = []
            file_metadata = None
            bytes_received = 0
            
            print(f"[Node {self.node.node_id}] Starting streaming transfer reception...")
            
            # Collect all chunks from the stream
            for chunk in request_iterator:
                if file_metadata is None:
                    file_metadata = {
                        'file_id': chunk.file_id,
                        'file_name': chunk.file_name,
                        'total_size': chunk.total_size,
                        'total_chunks': chunk.total_chunks
                    }
                    print(f"[Node {self.node.node_id}] Receiving {chunk.file_name} via streaming transfer")
                
                file_chunks.append({
                    'chunk_number': chunk.chunk_number,
                    'data': chunk.data,
                    'checksum': chunk.checksum,
                    'is_last_chunk': chunk.is_last_chunk
                })
                
                bytes_received += len(chunk.data)
                
                if chunk.is_last_chunk:
                    break
            
            if not file_metadata:
                return cloud_storage_pb2.StreamTransferResponse(
                    status='ERROR',
                    error='No chunks received'
                )
            
            # Reassemble file data from chunks
            file_chunks.sort(key=lambda x: x['chunk_number'])
            file_data = b''.join(chunk['data'] for chunk in file_chunks)
            
            # Store file to disk
            metadata = {
                'file_name': file_metadata['file_name'],
                'file_size': len(file_data),
                'checksum': hashlib.md5(file_data).hexdigest(),
                'upload_time': time.time(),
                'file_id': file_metadata['file_id'],
                'node_id': self.node.node_id
            }
            
            with self.node.file_lock:
                if self.node._store_file_to_disk(file_metadata['file_id'], file_data, metadata):
                    self.node.used_storage += len(file_data)
                    print(f"[Node {self.node.node_id}] Streaming transfer completed for {file_metadata['file_name']}")
                    
                    return cloud_storage_pb2.StreamTransferResponse(
                        status='OK',
                        file_id=file_metadata['file_id'],
                        bytes_transferred=bytes_received
                    )
                else:
                    return cloud_storage_pb2.StreamTransferResponse(
                        status='ERROR',
                        error='Failed to store file to disk'
                    )
                    
        except Exception as e:
            print(f"[Node {self.node.node_id}] Streaming transfer error: {e}")
            return cloud_storage_pb2.StreamTransferResponse(
                status='ERROR',
                error=str(e)
            )
    
    def ConnectNodes(self, request, context):
        """Handle node connection request"""
        try:
            self.node.add_connection(
                request.node_id,
                request.host,
                request.port,
                request.bandwidth
            )
            print(f"[Node {self.node.node_id}] Connected to node {request.node_id}")
            return cloud_storage_pb2.ConnectNodesResponse(status='OK')
        except Exception as e:
            return cloud_storage_pb2.ConnectNodesResponse(status='ERROR')

def create_grpc_server(network_controller=None, storage_node=None, port=50051):
    """Create and configure gRPC server with thread pool for concurrency"""
    # Use larger thread pool for concurrent streaming operations
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
    
    if network_controller:
        # Add network controller services
        cloud_storage_pb2_grpc.add_NodeManagementServicer_to_server(
            NodeManagementService(network_controller), server
        )
        cloud_storage_pb2_grpc.add_FileManagementServicer_to_server(
            FileManagementService(network_controller), server
        )
    
    if storage_node:
        # Add storage node services
        cloud_storage_pb2_grpc.add_FileTransferServicer_to_server(
            FileTransferService(storage_node), server
        )
    
    listen_addr = f'[::]:{port}'
    server.add_insecure_port(listen_addr)
    
    return server

def create_grpc_client(host='localhost', port=50051):
    """Create gRPC client stubs"""
    channel = grpc.insecure_channel(f'{host}:{port}')
    
    return {
        'node_management': cloud_storage_pb2_grpc.NodeManagementStub(channel),
        'file_management': cloud_storage_pb2_grpc.FileManagementStub(channel),
        'file_transfer': cloud_storage_pb2_grpc.FileTransferStub(channel),
        'channel': channel
    }

class StreamingFileClient:
    """Client helper for streaming file operations"""
    
    def __init__(self, host='localhost', port=50051):
        self.channel = grpc.insecure_channel(f'{host}:{port}')
        self.file_management_stub = cloud_storage_pb2_grpc.FileManagementStub(self.channel)
        self.file_transfer_stub = cloud_storage_pb2_grpc.FileTransferStub(self.channel)
    
    def stream_upload_file(self, file_path: str, file_id: str, node_id: str, chunk_size: int = 1024*1024) -> Dict:
        """Upload a file using streaming RPC"""
        try:
            if not os.path.exists(file_path):
                return {'status': 'ERROR', 'error': 'File not found'}
            
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            total_chunks = (file_size + chunk_size - 1) // chunk_size
            
            def chunk_generator():
                with open(file_path, 'rb') as f:
                    chunk_num = 0
                    while True:
                        chunk_data = f.read(chunk_size)
                        if not chunk_data:
                            break
                        
                        chunk_checksum = hashlib.md5(chunk_data).hexdigest()
                        is_last = (chunk_num == total_chunks - 1)
                        
                        yield cloud_storage_pb2.FileChunk(
                            file_id=file_id,
                            file_name=file_name,
                            total_size=file_size,
                            chunk_number=chunk_num,
                            total_chunks=total_chunks,
                            data=chunk_data,
                            checksum=chunk_checksum,
                            is_last_chunk=is_last,
                            node_id=node_id
                        )
                        
                        chunk_num += 1
            
            response = self.file_management_stub.StreamUpload(chunk_generator())
            
            return {
                'status': response.status,
                'error': response.error if response.status == 'ERROR' else None,
                'file_id': response.file_id,
                'bytes_received': response.bytes_received
            }
            
        except Exception as e:
            return {'status': 'ERROR', 'error': str(e)}
    
    def stream_download_file(self, file_id: str, node_id: str, save_path: str, start_chunk: int = 0, end_chunk: int = 0) -> Dict:
        """Download a file using streaming RPC"""
        try:
            request = cloud_storage_pb2.StreamDownloadRequest(
                file_id=file_id,
                node_id=node_id,
                start_chunk=start_chunk,
                end_chunk=end_chunk
            )
            
            chunks = []
            total_bytes = 0
            
            for chunk in self.file_management_stub.StreamDownload(request):
                if chunk.file_name == 'error':
                    return {'status': 'ERROR', 'error': chunk.data.decode()}
                
                chunks.append((chunk.chunk_number, chunk.data))
                total_bytes += len(chunk.data)
                
                if chunk.is_last_chunk:
                    break
            
            # Sort chunks and reassemble file
            chunks.sort(key=lambda x: x[0])
            file_data = b''.join(chunk[1] for chunk in chunks)
            
            # Save to file
            with open(save_path, 'wb') as f:
                f.write(file_data)
            
            return {
                'status': 'OK',
                'bytes_downloaded': total_bytes,
                'chunks_received': len(chunks)
            }
            
        except Exception as e:
            return {'status': 'ERROR', 'error': str(e)}
    
    def close(self):
        """Close the gRPC channel"""
        self.channel.close()
