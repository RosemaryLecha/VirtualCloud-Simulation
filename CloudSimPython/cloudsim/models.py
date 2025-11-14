import time
import enum
from dataclasses import dataclass, field
from typing import Dict, List


class TransferStatus(enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class NodeCapacity:
    cpu: int
    memory_gb: int
    storage_bytes: int
    bandwidth_bps: int


@dataclass
class NodeInfo:
    node_id: str
    host: str
    tcp_port: int
    udp_port: int
    capacity: NodeCapacity
    registered_at: float = field(default_factory=lambda: time.time())
    last_seen: float = field(default_factory=lambda: time.time())
    active: bool = True


@dataclass
class FileChunk:
    chunk_id: int
    size: int
    checksum: str
    status: TransferStatus = TransferStatus.PENDING
    stored_node: str | None = None


@dataclass
class FileTransfer:
    file_id: str
    file_name: str
    total_size: int
    chunks: List[FileChunk]
    status: TransferStatus = TransferStatus.PENDING
    created_at: float = field(default_factory=lambda: time.time())
    completed_at: float | None = None

    def is_complete(self) -> bool:
        return all(c.status == TransferStatus.COMPLETED for c in self.chunks)

    def mark_completed(self) -> None:
        self.status = TransferStatus.COMPLETED
        self.completed_at = time.time()


@dataclass
class NetworkStats:
    total_nodes: int
    active_nodes: int
    total_connections: int
    total_data_transferred: int
    total_storage_capacity: int
    total_bandwidth_capacity: int


def now_ms() -> int:
    return int(time.time() * 1000)
