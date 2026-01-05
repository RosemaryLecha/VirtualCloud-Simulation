import json
import socket
import threading
import time
import random
from typing import Dict

HEARTBEAT_INTERVAL_SECONDS = 2


class HeartbeatUDPServer(threading.Thread):
    def __init__(self, node_id: str, port: int = 0):
        super().__init__(name=f"HB-UDP-{node_id}", daemon=True)
        self.node_id = node_id
        self.port = port
        self._sock: socket.socket | None = None
        self._running = False

    def run(self):
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.port == 0:
            # Pick a port in 5001-9000 similar to Java impl
            self.port = random.randint(5001, 9000)
        self._sock.bind(("0.0.0.0", self.port))
        while self._running:
            try:
                data, addr = self._sock.recvfrom(1024)
                if data == b"PING":
                    payload = json.dumps({"node_id": self.node_id, "status": "ALIVE"}).encode("utf-8")
                    self._sock.sendto(payload, addr)
            except OSError:
                break
        if self._sock:
            self._sock.close()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass


class HeartbeatSender(threading.Thread):
    def __init__(self, node_id: str, controller_host: str, controller_port: int):
        super().__init__(name=f"HB-SEND-{node_id}", daemon=True)
        self.node_id = node_id
        self.host = controller_host
        self.port = controller_port
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            try:
                self._send_heartbeat()
                time.sleep(HEARTBEAT_INTERVAL_SECONDS)
            except Exception:
                time.sleep(HEARTBEAT_INTERVAL_SECONDS)

    def stop(self):
        self._running = False

    def _send_heartbeat(self):
        msg = {"action": "HEARTBEAT", "node_id": self.node_id}
        with socket.create_connection((self.host, self.port), timeout=3) as s:
            s.sendall(json.dumps(msg).encode("utf-8"))
            _ = s.recv(4096)


class StorageNode:
    def __init__(self, node_id: str, controller_host: str, controller_port: int,
                 cpu: int, memory_gb: int, storage_gb: int, bandwidth_mbps: int):
        self.node_id = node_id
        self.controller_host = controller_host
        self.controller_port = controller_port
        self.cpu = cpu
        self.memory_gb = memory_gb
        self.storage_bytes = storage_gb * 1024 * 1024 * 1024
        self.bandwidth_bps = bandwidth_mbps * 1_000_000
        self.hb_udp = HeartbeatUDPServer(node_id)
        self.hb_sender = HeartbeatSender(node_id, controller_host, controller_port)
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self.hb_udp.start()
        time.sleep(0.05)
        self._register()
        self.hb_sender.start()
        self._notify_active()
        print(f"[Node {self.node_id}] started (udp={self.hb_udp.port})")
        try:
            while self._running:
                time.sleep(0.5)
        finally:
            self.shutdown()

    def shutdown(self):
        self._running = False
        self.hb_sender.stop()
        self.hb_udp.stop()

    def _register(self):
        msg: Dict[str, object] = {
            "action": "REGISTER",
            "node_id": self.node_id,
            "host": "127.0.0.1",
            "port": self.hb_udp.port,
            "capacity": {
                "cpu": self.cpu,
                "memory": self.memory_gb,
                "storage": self.storage_bytes,
                "bandwidth": self.bandwidth_bps,
            },
        }
        with socket.create_connection((self.controller_host, self.controller_port), timeout=5) as s:
            s.sendall(json.dumps(msg).encode("utf-8"))
            _ = s.recv(4096)

    def _notify_active(self):
        msg = {"action": "ACTIVE_NOTIFICATION", "node_id": self.node_id}
        with socket.create_connection((self.controller_host, self.controller_port), timeout=3) as s:
            s.sendall(json.dumps(msg).encode("utf-8"))
            _ = s.recv(4096)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--node-id", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--network-port", type=int, default=8080)
    ap.add_argument("--cpu", type=int, default=4)
    ap.add_argument("--memory", type=int, default=8)
    ap.add_argument("--storage", type=int, default=100)
    ap.add_argument("--bandwidth", type=int, default=1000)
    args = ap.parse_args()

    node = StorageNode(
        node_id=args.node_id,
        controller_host=args.host,
        controller_port=args.network_port,
        cpu=args.cpu,
        memory_gb=args.memory,
        storage_gb=args.storage,
        bandwidth_mbps=args.bandwidth,
    )
    node.start()


if __name__ == "__main__":
    main()
