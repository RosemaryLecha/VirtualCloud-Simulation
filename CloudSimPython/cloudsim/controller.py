import json
import socket
import threading
import time
from typing import Dict, Tuple

from .models import NodeCapacity, NodeInfo, NetworkStats

HEARTBEAT_TIMEOUT_SECONDS = 10
HEARTBEAT_CHECK_INTERVAL_SECONDS = 5


class NetworkController:
    def __init__(self, port: int = 8080):
        self.port = port
        self._server_socket: socket.socket | None = None
        self._running = False
        self._registered: Dict[str, NodeInfo] = {}
        self._last_hb: Dict[str, float] = {}
        self._total_connections = 0
        self._total_data_transferred = 0
        self._lock = threading.RLock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(("0.0.0.0", self.port))
        self._server_socket.listen(128)
        threading.Thread(target=self._accept_loop, name="Controller-Accept", daemon=True).start()
        threading.Thread(target=self._heartbeat_monitor, name="Controller-HB", daemon=True).start()
        print(f"[Controller] Listening on TCP {self.port}")
        try:
            while self._running:
                time.sleep(0.5)
        finally:
            self.shutdown()

    def _accept_loop(self):
        assert self._server_socket is not None
        while self._running:
            try:
                client, addr = self._server_socket.accept()
                self._total_connections += 1
                threading.Thread(target=self._handle_client, args=(client, addr), daemon=True).start()
            except OSError:
                break

    def _handle_client(self, client: socket.socket, addr: Tuple[str, int]):
        with client:
            try:
                client.settimeout(5)
                data = client.recv(65536)
                if not data:
                    return
                message = json.loads(data.decode("utf-8"))
                action = message.get("action")
                response: Dict[str, object] = {}
                if action == "REGISTER":
                    response = self._handle_register(message)
                elif action == "HEARTBEAT":
                    response = self._handle_heartbeat(message)
                elif action == "ACTIVE_NOTIFICATION":
                    response = self._handle_active(message)
                elif action == "LIST_NODES":
                    response = self._handle_list_nodes()
                elif action == "STATS":
                    response = self._handle_stats()
                else:
                    response = {"status": "ERROR", "message": f"Unknown action: {action}"}
                client.sendall(json.dumps(response).encode("utf-8"))
            except Exception as e:
                # Swallow per-connection errors for simulation
                pass

    def _handle_register(self, msg: Dict[str, object]) -> Dict[str, object]:
        try:
            node_id = str(msg["node_id"])  # required
            host = str(msg.get("host", "127.0.0.1"))
            tcp_port = int(msg.get("tcp_port", self.port))
            udp_port = int(msg.get("port", 0))
            cap = msg.get("capacity", {})
            capacity = NodeCapacity(
                cpu=int(cap.get("cpu", 4)),
                memory_gb=int(cap.get("memory", 8)),
                storage_bytes=int(cap.get("storage", 100 * 1024 * 1024 * 1024)),
                bandwidth_bps=int(cap.get("bandwidth", 1_000_000_000)),
            )
            with self._lock:
                self._registered[node_id] = NodeInfo(node_id, host, tcp_port, udp_port, capacity)
                self._last_hb[node_id] = time.time()
            print(f"[Controller] Registered {node_id} capacity={capacity}")
            return {"status": "OK"}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

    def _handle_heartbeat(self, msg: Dict[str, object]) -> Dict[str, object]:
        node_id = str(msg.get("node_id", ""))
        with self._lock:
            if node_id in self._registered:
                self._last_hb[node_id] = time.time()
                self._registered[node_id].last_seen = time.time()
                return {"status": "ACK"}
            else:
                return {"status": "ERROR", "message": "Node not registered"}

    def _handle_active(self, msg: Dict[str, object]) -> Dict[str, object]:
        node_id = str(msg.get("node_id", ""))
        with self._lock:
            if node_id in self._registered:
                info = self._registered[node_id]
                info.active = True
                info.last_seen = time.time()
                self._last_hb[node_id] = time.time()
                print(f"[Controller] Node {node_id} is now active")
                return {"status": "ACK"}
            else:
                return {"status": "ERROR", "message": "Node not registered"}

    def _heartbeat_monitor(self):
        while self._running:
            time.sleep(HEARTBEAT_CHECK_INTERVAL_SECONDS)
            cutoff = time.time() - HEARTBEAT_TIMEOUT_SECONDS
            with self._lock:
                for node_id, last in list(self._last_hb.items()):
                    if last < cutoff:
                        info = self._registered.get(node_id)
                        if not info:
                            continue
                        if self._ping_udp(info.host, info.udp_port):
                            self._last_hb[node_id] = time.time()
                            info.active = True
                            print(f"[Controller] Refreshed {node_id} via UDP ping")
                        elif info.active:
                            info.active = False
                            print(f"[Controller] Node {node_id} marked inactive (timeout)")

    def _ping_udp(self, host: str, port: int) -> bool:
        if port <= 0:
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(1)
                s.sendto(b"PING", (host, port))
                data, _ = s.recvfrom(512)
                return b"ALIVE" in data
        except Exception:
            return False

    def get_stats(self) -> NetworkStats:
        with self._lock:
            total_storage = sum(n.capacity.storage_bytes for n in self._registered.values())
            total_bw = sum(n.capacity.bandwidth_bps for n in self._registered.values())
            active = sum(1 for n in self._registered.values() if n.active)
            return NetworkStats(
                total_nodes=len(self._registered),
                active_nodes=active,
                total_connections=self._total_connections,
                total_data_transferred=self._total_data_transferred,
                total_storage_capacity=total_storage,
                total_bandwidth_capacity=total_bw,
            )

    def _handle_list_nodes(self) -> Dict[str, object]:
        with self._lock:
            nodes = []
            for n in self._registered.values():
                nodes.append({
                    "node_id": n.node_id,
                    "host": n.host,
                    "tcp_port": n.tcp_port,
                    "udp_port": n.udp_port,
                    "active": n.active,
                    "capacity": {
                        "cpu": n.capacity.cpu,
                        "memory": n.capacity.memory_gb,
                        "storage": n.capacity.storage_bytes,
                        "bandwidth": n.capacity.bandwidth_bps,
                    },
                })
            return {"status": "OK", "nodes": nodes}

    def _handle_stats(self) -> Dict[str, object]:
        s = self.get_stats()
        return {
            "status": "OK",
            "stats": {
                "total_nodes": s.total_nodes,
                "active_nodes": s.active_nodes,
                "total_connections": s.total_connections,
                "total_data_transferred": s.total_data_transferred,
                "total_storage_capacity": s.total_storage_capacity,
                "total_bandwidth_capacity": s.total_bandwidth_capacity,
            }
        }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--transfer", action="store_true")
    ap.add_argument("--file-name", type=str, default="file.bin")
    ap.add_argument("--size-mb", type=int, default=10)
    ap.add_argument("--replication", type=int, default=2)
    args = ap.parse_args()

    controller = NetworkController(port=args.port)
    controller.start()


if __name__ == "__main__":
    main()
