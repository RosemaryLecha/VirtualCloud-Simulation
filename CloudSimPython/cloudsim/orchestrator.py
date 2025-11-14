import hashlib
import random
import socket
import json
import threading
import time
from typing import Dict, List

from .models import FileChunk, FileTransfer, TransferStatus


def _calc_chunk_size(file_size: int) -> int:
    if file_size < 10 * 1024 * 1024:
        return 512 * 1024
    elif file_size < 100 * 1024 * 1024:
        return 2 * 1024 * 1024
    return 10 * 1024 * 1024


def _gen_chunks(file_id: str, file_size: int) -> List[FileChunk]:
    size = _calc_chunk_size(file_size)
    n = (file_size + size - 1) // size
    chunks: List[FileChunk] = []
    for i in range(n):
        part = min(size, file_size - i * size)
        checksum = hashlib.md5(f"{file_id}-{i}".encode("utf-8")).hexdigest()
        chunks.append(FileChunk(i, int(part), checksum))
    return chunks


class Orchestrator:
    def __init__(self, controller_host: str, controller_port: int):
        self.host = controller_host
        self.port = controller_port
        self._reserved: Dict[str, int] = {}  # node_id -> bytes reserved
        self._rnd = random.Random()

    def _request(self, payload: Dict[str, object]) -> Dict[str, object]:
        with socket.create_connection((self.host, self.port), timeout=5) as s:
            s.sendall(json.dumps(payload).encode("utf-8"))
            resp = s.recv(1_000_000)
            return json.loads(resp.decode("utf-8"))

    def _list_nodes(self) -> List[Dict[str, object]]:
        resp = self._request({"action": "LIST_NODES"})
        if resp.get("status") != "OK":
            return []
        return resp.get("nodes", [])

    def _estimated_available(self, node: Dict[str, object]) -> int:
        total = int(node["capacity"]["storage"])
        reserved = int(self._reserved.get(node["node_id"], 0))
        free = total - reserved
        return free if free > 0 else 0

    def _select_targets(self, nodes: List[Dict[str, object]], replication: int, file_size: int) -> List[str]:
        active = [n for n in nodes if n.get("active")]
        suitable = [n for n in active if self._estimated_available(n) >= file_size]
        suitable.sort(key=lambda n: (self._estimated_available(n), int(n["capacity"]["bandwidth"])), reverse=True)
        return [n["node_id"] for n in suitable[: replication]]

    def initiate_transfer(self, file_name: str, file_size: int, replication: int = 2) -> FileTransfer | None:
        file_id = f"{file_name.replace(' ', '_')}-{int(time.time()*1000)}-{self._rnd.randint(0,9999)}"
        nodes = self._list_nodes()
        targets = self._select_targets(nodes, replication, file_size)
        if not targets:
            print("[Orchestrator] No suitable nodes available")
            return None
        chunks = _gen_chunks(file_id, file_size)
        transfer = FileTransfer(file_id=file_id, file_name=file_name, total_size=file_size, chunks=chunks)
        for nid in targets:
            self._reserved[nid] = self._reserved.get(nid, 0) + file_size
        threading.Thread(target=self._execute, args=(transfer, targets), daemon=True).start()
        return transfer

    def _execute(self, transfer: FileTransfer, target_nodes: List[str]):
        transfer.status = TransferStatus.IN_PROGRESS
        try:
            futures = []
            for node_id in target_nodes:
                t = threading.Thread(target=self._simulate_to_node, args=(transfer, node_id), daemon=True)
                t.start()
                futures.append(t)
            for t in futures:
                t.join(timeout=30)
            if transfer.is_complete():
                transfer.mark_completed()
                print(f"[Orchestrator] Transfer completed: {transfer.file_name}")
            else:
                transfer.status = TransferStatus.FAILED
                print(f"[Orchestrator] Transfer failed: {transfer.file_name}")
        finally:
            for nid in target_nodes:
                self._reserved[nid] = self._reserved.get(nid, 0) - transfer.total_size

    def _simulate_to_node(self, transfer: FileTransfer, node_id: str):
        # Assume 100 Mbps baseline with +-20% jitter
        for c in transfer.chunks:
            bits = c.size * 8
            bps = 100 * 1_000_000
            jitter = 0.8 + self._rnd.random() * 0.4
            delay = bits / bps * jitter
            time.sleep(delay)
            c.status = TransferStatus.COMPLETED
            c.stored_node = node_id


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--file-name", required=True)
    ap.add_argument("--size-mb", type=int, default=10)
    ap.add_argument("--replication", type=int, default=2)
    args = ap.parse_args()

    orch = Orchestrator(args.host, args.port)
    transfer = orch.initiate_transfer(args.file_name, args.size_mb * 1024 * 1024, args.replication)
    if transfer is None:
        return
    # Wait for completion (up to 40s)
    start = time.time()
    while time.time() - start < 40:
        if transfer.status in (TransferStatus.COMPLETED, TransferStatus.FAILED):
            break
        time.sleep(0.5)
    print(f"[Orchestrator] Status: {transfer.status}")


if __name__ == "__main__":
    main()
