import argparse
import json
import socket
from typing import Dict


def request(host: str, port: int, payload: Dict[str, object]) -> Dict[str, object]:
    with socket.create_connection((host, port), timeout=5) as s:
        s.sendall(json.dumps(payload).encode("utf-8"))
        resp = s.recv(1_000_000)
        return json.loads(resp.decode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description="Compare/check Python controller runtime state")
    ap.add_argument("--controller-host", default="127.0.0.1")
    ap.add_argument("--controller-port", type=int, default=8080)
    args = ap.parse_args()

    stats = request(args.controller_host, args.controller_port, {"action": "STATS"})
    nodes = request(args.controller_host, args.controller_port, {"action": "LIST_NODES"})

    if stats.get("status") != "OK" or nodes.get("status") != "OK":
        print("[Compare] Controller did not respond OK")
        print("Stats:", stats)
        print("Nodes:", nodes)
        return

    s = stats["stats"]
    print("[Compare] Controller Stats")
    for k, v in s.items():
        print(f"  {k}: {v}")

    print("[Compare] Registered Nodes")
    for n in nodes["nodes"]:
        cap = n["capacity"]
        print(f"  - {n['node_id']}: active={n['active']}, host={n['host']} udp={n['udp_port']}\n"
              f"    capacity: cpu={cap['cpu']} mem={cap['memory']}GB storage={cap['storage']}B bw={cap['bandwidth']}bps")


if __name__ == "__main__":
    main()
