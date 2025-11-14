# Cloud Storage Simulation (Python)

This is a Python reimplementation of the Java CloudSim project, preserving the core conception and features:

- Network Controller: tracks nodes, handles registration and TCP heartbeats, and verifies liveness via UDP ping.
- Storage Node: registers with controller, runs a UDP heartbeat server, and sends TCP heartbeats periodically.
- File Transfer Orchestrator: chunks files, selects nodes by estimated available capacity and bandwidth, and simulates transfers.

## Requirements

- Python 3.9+
- Optional: psutil (for extended metrics). See `requirements.txt`.

## Quick start

1. Create a virtual environment (optional) and install deps:

```bash
python -m venv .venv
. .venv/Scripts/activate  # on Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

2. Start controller (default port 8080):

```bash
python -m cloudsim.controller --port 8080
```

3. Start nodes (each in a new terminal):

```bash
python -m cloudsim.node --node-id node1 --host 127.0.0.1 --network-port 8080 --cpu 4 --memory 8 --storage 100 --bandwidth 1000
python -m cloudsim.node --node-id node2 --host 127.0.0.1 --network-port 8080 --cpu 8 --memory 16 --storage 200 --bandwidth 2000
```

4. Initiate a simulated transfer via controller CLI:

```bash
python -m cloudsim.controller --transfer --file-name video.mp4 --size-mb 50 --replication 2
```

Alternatively, run the single-entry CLI that mirrors the Java app:

```bash
python cli.py --network --port 8080
# or
python cli.py --node --node-id node1 --network-port 8080
```

## Parity checklist (with Java)

- Registration via TCP with JSON messages: action=REGISTER, node info, capacities.
- Heartbeats via TCP; controller verifies via UDP ping before marking inactive.
- Node selection uses estimated available storage (capacity - reserved) and bandwidth.
- Chunking thresholds: 512KB (<10MB), 2MB (<100MB), 10MB otherwise.

## Compare utility

`compare/compare.py` can check basic parity:
- Query a running controller’s internal stats (Python instance) via a simple local socket command.
- Optionally ping Java controller using the same REGISTER/HEARTBEAT JSON to verify endpoint behavior.

Run:

```bash
python compare/compare.py --controller-host 127.0.0.1 --controller-port 8080
```
