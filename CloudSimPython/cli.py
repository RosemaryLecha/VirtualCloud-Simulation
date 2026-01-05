import argparse
import sys
from cloudsim.controller import NetworkController
from cloudsim.node import StorageNode


def main():
    ap = argparse.ArgumentParser(description="Cloud Storage Simulation (Python)")
    ap.add_argument("--network", action="store_true", help="Start as network controller")
    ap.add_argument("--node", action="store_true", help="Start as storage node")
    ap.add_argument("--help2", action="store_true", help="Show help")

    # Controller options
    ap.add_argument("--port", type=int, default=8080, help="Controller TCP port")

    # Node options
    ap.add_argument("--node-id")
    ap.add_argument("--host", default="127.0.0.1", help="Controller host")
    ap.add_argument("--network-port", type=int, default=8080, help="Controller port")
    ap.add_argument("--cpu", type=int, default=4)
    ap.add_argument("--memory", type=int, default=8)
    ap.add_argument("--storage", type=int, default=100, help="GB")
    ap.add_argument("--bandwidth", type=int, default=1000, help="Mbps")

    args = ap.parse_args()

    if args.help2 or (not args.network and not args.node):
        ap.print_help()
        print("\nExamples:")
        print("  python cli.py --network --port 8080")
        print("  python cli.py --node --node-id node1 --host 127.0.0.1 --network-port 8080")
        sys.exit(0)

    if args.network:
        controller = NetworkController(port=args.port)
        controller.start()
    elif args.node:
        if not args.node_id:
            print("Error: --node-id is required for --node mode", file=sys.stderr)
            sys.exit(1)
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
