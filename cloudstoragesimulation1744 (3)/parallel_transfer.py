import time
import threading
import socket
import random
import hashlib
import struct
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum, auto
import concurrent.futures
from collections import defaultdict

class PacketType(Enum):
    DATA = 1
    ACK = 2
    NACK = 3
    START_TRANSFER = 4
    END_TRANSFER = 5
    HEARTBEAT = 6

class TransferState(Enum):
    INITIALIZING = auto()
    TRANSFERRING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()

@dataclass
class NetworkPacket:
    """Represents a network packet with all required details"""
    packet_id: str
    packet_type: PacketType
    sequence_number: int
    total_packets: int
    file_id: str
    chunk_id: int
    data: bytes
    checksum: str
    source_ip: str
    source_mac: str
    source_port: int
    dest_ip: str
    dest_mac: str
    dest_port: int
    timestamp: float
    protocol: str = "TCP"
    
    def to_bytes(self) -> bytes:
        """Serialize packet to bytes for network transmission"""
        header = struct.pack(
            '!I I I I I I I Q 16s 18s 18s 8s',
            len(self.packet_id.encode()),
            self.packet_type.value,
            self.sequence_number,
            self.total_packets,
            self.chunk_id,
            self.source_port,
            self.dest_port,
            int(self.timestamp * 1000000),  # microseconds
            self.source_ip.encode()[:16].ljust(16, b'\0'),
            self.source_mac.encode()[:18].ljust(18, b'\0'),
            self.dest_mac.encode()[:18].ljust(18, b'\0'),
            self.protocol.encode()[:8].ljust(8, b'\0')
        )
        
        packet_id_bytes = self.packet_id.encode()
        file_id_bytes = self.file_id.encode()
        checksum_bytes = self.checksum.encode()
        
        return (header + 
                struct.pack('!I', len(file_id_bytes)) + file_id_bytes +
                struct.pack('!I', len(checksum_bytes)) + checksum_bytes +
                struct.pack('!I', len(self.data)) + self.data)
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'NetworkPacket':
        """Deserialize packet from bytes"""
        header_size = struct.calcsize('!I I I I I I I Q 16s 18s 18s 8s')
        header = struct.unpack('!I I I I I I I Q 16s 18s 18s 8s', data[:header_size])
        
        packet_id_len = header[0]
        packet_type = PacketType(header[1])
        sequence_number = header[2]
        total_packets = header[3]
        chunk_id = header[4]
        source_port = header[5]
        dest_port = header[6]
        timestamp = header[7] / 1000000.0
        source_ip = header[8].decode().rstrip('\0')
        source_mac = header[9].decode().rstrip('\0')
        dest_mac = header[10].decode().rstrip('\0')
        protocol = header[11].decode().rstrip('\0')
        
        offset = header_size
        packet_id = data[offset+4:offset+4+packet_id_len].decode()
        offset += 4 + packet_id_len
        
        file_id_len = struct.unpack('!I', data[offset:offset+4])[0]
        offset += 4
        file_id = data[offset:offset+file_id_len].decode()
        offset += file_id_len
        
        checksum_len = struct.unpack('!I', data[offset:offset+4])[0]
        offset += 4
        checksum = data[offset:offset+checksum_len].decode()
        offset += checksum_len
        
        data_len = struct.unpack('!I', data[offset:offset+4])[0]
        offset += 4
        packet_data = data[offset:offset+data_len]
        
        return cls(
            packet_id=packet_id,
            packet_type=packet_type,
            sequence_number=sequence_number,
            total_packets=total_packets,
            file_id=file_id,
            chunk_id=chunk_id,
            data=packet_data,
            checksum=checksum,
            source_ip=source_ip,
            source_mac=source_mac,
            source_port=source_port,
            dest_ip="",  # Will be filled by receiver
            dest_mac="",  # Will be filled by receiver
            dest_port=dest_port,
            timestamp=timestamp,
            protocol=protocol
        )

@dataclass
class ChunkTransfer:
    """Manages transfer of a single file chunk"""
    chunk_id: int
    file_id: str
    total_size: int
    packets: Dict[int, NetworkPacket] = field(default_factory=dict)
    received_packets: Set[int] = field(default_factory=set)
    missing_packets: Set[int] = field(default_factory=set)
    state: TransferState = TransferState.INITIALIZING
    start_time: float = field(default_factory=time.time)
    completion_time: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def is_complete(self) -> bool:
        """Check if all packets have been received"""
        if not self.packets:
            return False
        expected_packets = max(self.packets.keys()) + 1 if self.packets else 0
        return len(self.received_packets) == expected_packets
    
    def get_missing_packets(self) -> List[int]:
        """Get list of missing packet sequence numbers"""
        if not self.packets:
            return []
        expected_packets = set(range(max(self.packets.keys()) + 1))
        return list(expected_packets - self.received_packets)
    
    def reassemble_data(self) -> bytes:
        """Reassemble data from received packets in correct order"""
        if not self.is_complete():
            raise ValueError("Cannot reassemble incomplete transfer")
        
        sorted_packets = sorted(self.packets.items())
        return b''.join(packet.data for _, packet in sorted_packets)

class ParallelTransferManager:
    """Manages parallel file transfers with segmentation and reassembly"""
    
    def __init__(self, node_id: str, network_info: Dict, max_concurrent_transfers: int = 5):
        self.node_id = node_id
        self.network_info = network_info
        self.max_concurrent_transfers = max_concurrent_transfers
        
        # Transfer tracking
        self.active_transfers: Dict[str, ChunkTransfer] = {}
        self.completed_transfers: Dict[str, ChunkTransfer] = {}
        self.transfer_lock = threading.RLock()
        
        # Network configuration
        self.packet_size = 1024  # bytes per packet
        self.timeout = 5.0  # seconds
        self.max_retries = 3
        
        # Threading
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_concurrent_transfers * 2
        )
        self.running = True
        
        # Statistics
        self.stats = {
            'packets_sent': 0,
            'packets_received': 0,
            'packets_lost': 0,
            'retransmissions': 0,
            'transfers_completed': 0,
            'transfers_failed': 0,
            'total_bytes_transferred': 0
        }
        
        # Start background tasks
        self.cleanup_thread = threading.Thread(target=self._cleanup_completed_transfers, daemon=True)
        self.cleanup_thread.start()
        
    def create_packets(self, file_id: str, chunk_id: int, data: bytes) -> List[NetworkPacket]:
        """Create network packets from chunk data"""
        packets = []
        total_packets = (len(data) + self.packet_size - 1) // self.packet_size
        
        for i in range(total_packets):
            start_idx = i * self.packet_size
            end_idx = min(start_idx + self.packet_size, len(data))
            packet_data = data[start_idx:end_idx]
            
            packet = NetworkPacket(
                packet_id=f"{file_id}_{chunk_id}_{i}",
                packet_type=PacketType.DATA,
                sequence_number=i,
                total_packets=total_packets,
                file_id=file_id,
                chunk_id=chunk_id,
                data=packet_data,
                checksum=hashlib.md5(packet_data).hexdigest(),
                source_ip=self.network_info['ip_address'],
                source_mac=self.network_info['mac_address'],
                source_port=random.randint(49152, 65535),
                dest_ip="",  # Will be set by caller
                dest_mac="",  # Will be set by caller
                dest_port=0,  # Will be set by caller
                timestamp=time.time()
            )
            packets.append(packet)
            
        return packets
    
    def send_chunk_parallel(
        self, 
        file_id: str, 
        chunk_id: int, 
        data: bytes, 
        dest_host: str, 
        dest_port: int,
        dest_network_info: Dict
    ) -> str:
        """Send a chunk using parallel packet transmission"""
        transfer_id = f"{file_id}_{chunk_id}_{int(time.time())}"
        
        # Create packets
        packets = self.create_packets(file_id, chunk_id, data)
        
        # Set destination info
        for packet in packets:
            packet.dest_ip = dest_network_info.get('ip_address', dest_host)
            packet.dest_mac = dest_network_info.get('mac_address', '00:00:00:00:00:00')
            packet.dest_port = dest_port
        
        # Create transfer record
        chunk_transfer = ChunkTransfer(
            chunk_id=chunk_id,
            file_id=file_id,
            total_size=len(data)
        )
        
        for packet in packets:
            chunk_transfer.packets[packet.sequence_number] = packet
        
        with self.transfer_lock:
            self.active_transfers[transfer_id] = chunk_transfer
        
        # Submit parallel transmission tasks
        futures = []
        for packet in packets:
            future = self.executor.submit(
                self._send_packet_with_retry,
                packet, dest_host, dest_port, transfer_id
            )
            futures.append(future)
        
        # Monitor transmission
        self.executor.submit(
            self._monitor_transfer,
            transfer_id, futures, dest_host, dest_port
        )
        
        print(f"[Node {self.node_id}] Started parallel transfer {transfer_id} with {len(packets)} packets")
        return transfer_id
    
    def _send_packet_with_retry(
        self, 
        packet: NetworkPacket, 
        dest_host: str, 
        dest_port: int, 
        transfer_id: str
    ) -> bool:
        """Send a single packet with retry logic"""
        for attempt in range(self.max_retries):
            try:
                # Simulate network delay and potential packet loss
                if random.random() < 0.05:  # 5% packet loss simulation
                    if attempt < self.max_retries - 1:
                        print(f"[Node {self.node_id}] Packet {packet.sequence_number} lost, retrying...")
                        self.stats['packets_lost'] += 1
                        time.sleep(random.uniform(0.1, 0.5))
                        continue
                
                # Simulate variable network delay
                network_delay = random.uniform(0.01, 0.1)
                time.sleep(network_delay)
                
                # In a real implementation, this would use actual sockets
                # For simulation, we'll just track the packet as sent
                self.stats['packets_sent'] += 1
                
                if attempt > 0:
                    self.stats['retransmissions'] += 1
                
                print(f"[Node {self.node_id}] Sent packet {packet.sequence_number} for transfer {transfer_id}")
                return True
                
            except Exception as e:
                print(f"[Node {self.node_id}] Error sending packet {packet.sequence_number}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(random.uniform(0.5, 1.0))
        
        return False
    
    def _monitor_transfer(
        self, 
        transfer_id: str, 
        futures: List[concurrent.futures.Future], 
        dest_host: str, 
        dest_port: int
    ):
        """Monitor transfer completion and handle failures"""
        try:
            # Wait for all packets to be sent
            completed = 0
            failed = 0
            
            for future in concurrent.futures.as_completed(futures, timeout=30):
                try:
                    success = future.result()
                    if success:
                        completed += 1
                    else:
                        failed += 1
                except Exception as e:
                    print(f"[Node {self.node_id}] Packet transmission error: {e}")
                    failed += 1
            
            with self.transfer_lock:
                if transfer_id in self.active_transfers:
                    transfer = self.active_transfers[transfer_id]
                    
                    if failed == 0:
                        transfer.state = TransferState.COMPLETED
                        transfer.completion_time = time.time()
                        self.stats['transfers_completed'] += 1
                        self.stats['total_bytes_transferred'] += transfer.total_size
                        print(f"[Node {self.node_id}] Transfer {transfer_id} completed successfully")
                    else:
                        transfer.state = TransferState.FAILED
                        self.stats['transfers_failed'] += 1
                        print(f"[Node {self.node_id}] Transfer {transfer_id} failed ({failed} packets failed)")
                        
        except concurrent.futures.TimeoutError:
            print(f"[Node {self.node_id}] Transfer {transfer_id} timed out")
            with self.transfer_lock:
                if transfer_id in self.active_transfers:
                    self.active_transfers[transfer_id].state = TransferState.FAILED
                    self.stats['transfers_failed'] += 1
    
    def receive_packet(self, packet_data: bytes, source_addr: Tuple[str, int]) -> bool:
        """Receive and process an incoming packet"""
        try:
            packet = NetworkPacket.from_bytes(packet_data)
            packet.dest_ip = self.network_info['ip_address']
            packet.dest_mac = self.network_info['mac_address']
            
            transfer_id = f"{packet.file_id}_{packet.chunk_id}_recv"
            
            with self.transfer_lock:
                # Create transfer record if it doesn't exist
                if transfer_id not in self.active_transfers:
                    self.active_transfers[transfer_id] = ChunkTransfer(
                        chunk_id=packet.chunk_id,
                        file_id=packet.file_id,
                        total_size=0  # Will be calculated from packets
                    )
                
                transfer = self.active_transfers[transfer_id]
                
                # Add packet to transfer
                transfer.packets[packet.sequence_number] = packet
                transfer.received_packets.add(packet.sequence_number)
                
                self.stats['packets_received'] += 1
                
                # Check if transfer is complete
                if packet.total_packets > 0 and len(transfer.received_packets) == packet.total_packets:
                    transfer.state = TransferState.COMPLETED
                    transfer.completion_time = time.time()
                    transfer.total_size = sum(len(p.data) for p in transfer.packets.values())
                    
                    print(f"[Node {self.node_id}] Received complete chunk {packet.chunk_id} for file {packet.file_id}")
                    self.stats['transfers_completed'] += 1
                    self.stats['total_bytes_transferred'] += transfer.total_size
                    
                    # Move to completed transfers
                    self.completed_transfers[transfer_id] = transfer
                    del self.active_transfers[transfer_id]
                    
                    return True
                else:
                    missing = transfer.get_missing_packets()
                    if missing:
                        print(f"[Node {self.node_id}] Chunk {packet.chunk_id} progress: {len(transfer.received_packets)}/{packet.total_packets}, missing: {len(missing)}")
            
            return False
            
        except Exception as e:
            print(f"[Node {self.node_id}] Error processing received packet: {e}")
            return False
    
    def get_completed_chunk(self, file_id: str, chunk_id: int) -> Optional[bytes]:
        """Get reassembled data for a completed chunk"""
        transfer_id = f"{file_id}_{chunk_id}_recv"
        
        with self.transfer_lock:
            if transfer_id in self.completed_transfers:
                transfer = self.completed_transfers[transfer_id]
                if transfer.state == TransferState.COMPLETED:
                    try:
                        return transfer.reassemble_data()
                    except Exception as e:
                        print(f"[Node {self.node_id}] Error reassembling chunk {chunk_id}: {e}")
                        return None
        
        return None
    
    def _cleanup_completed_transfers(self):
        """Background task to clean up old completed transfers"""
        while self.running:
            try:
                current_time = time.time()
                cleanup_age = 300  # 5 minutes
                
                with self.transfer_lock:
                    to_remove = []
                    for transfer_id, transfer in self.completed_transfers.items():
                        if (transfer.completion_time and 
                            current_time - transfer.completion_time > cleanup_age):
                            to_remove.append(transfer_id)
                    
                    for transfer_id in to_remove:
                        del self.completed_transfers[transfer_id]
                    
                    if to_remove:
                        print(f"[Node {self.node_id}] Cleaned up {len(to_remove)} old transfers")
                
                time.sleep(60)  # Check every minute
                
            except Exception as e:
                print(f"[Node {self.node_id}] Cleanup error: {e}")
                time.sleep(60)
    
    def get_transfer_stats(self) -> Dict:
        """Get transfer statistics"""
        with self.transfer_lock:
            active_count = len(self.active_transfers)
            completed_count = len(self.completed_transfers)
        
        return {
            **self.stats,
            'active_transfers': active_count,
            'completed_transfers': completed_count,
            'success_rate': (
                self.stats['transfers_completed'] / 
                max(1, self.stats['transfers_completed'] + self.stats['transfers_failed'])
            ) * 100
        }
    
    def shutdown(self):
        """Graceful shutdown"""
        print(f"[Node {self.node_id}] Shutting down parallel transfer manager...")
        self.running = False
        self.executor.shutdown(wait=True)
        print(f"[Node {self.node_id}] Parallel transfer manager shutdown complete")

class NetworkSimulator:
    """Simulates network conditions for testing"""
    
    def __init__(self):
        self.packet_loss_rate = 0.02  # 2% packet loss
        self.min_delay = 0.01  # 10ms minimum delay
        self.max_delay = 0.1   # 100ms maximum delay
        self.jitter = 0.02     # 20ms jitter
        
    def simulate_transmission(self, packet: NetworkPacket) -> bool:
        """Simulate network transmission with realistic conditions"""
        # Simulate packet loss
        if random.random() < self.packet_loss_rate:
            return False
        
        # Simulate network delay with jitter
        base_delay = random.uniform(self.min_delay, self.max_delay)
        jitter_delay = random.uniform(-self.jitter, self.jitter)
        total_delay = max(0, base_delay + jitter_delay)
        
        time.sleep(total_delay)
        return True
    
    def set_network_conditions(self, loss_rate: float, min_delay: float, max_delay: float, jitter: float):
        """Configure network simulation parameters"""
        self.packet_loss_rate = loss_rate
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.jitter = jitter
