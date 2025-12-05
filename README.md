# VirtualCloud-Simulation
A virtual cloud simulation project to enlarge our ideaology on distributed systems and cloud computing
A complete, secure cloud storage system built with gRPC for authentication and distributed file storage. This project simulates a real-world cloud platform where users can sign up, authenticate with 2FA (OTP), and upload/download files with per-user quotas (1GB free on signup). Files are persistently stored and replicated across nodes for fault tolerance, inspired by systems like Google Drive or AWS S3.
Originally based on a simple gRPC calculator demo (as shown in the screenshot), it has evolved into a full auth + storage system with web UI integration.
Features

User Authentication: Signup, login with password + OTP (via Gmail SMTP), password reset, JWT tokens (access/refresh), session management (view/revoke/logout).
Storage Quota: 1GB free per user on signup; enforces limits on uploads ("No more space" error when full).
File Operations: Upload, download, list, delete files—tied to user ownership.
Distributed Storage: Files replicated selectively across nodes (default factor: 2) for redundancy; persistent on disk (survives restarts).
Fault Tolerance: Node heartbeats, auto-failover on downloads, re-replication on failures.
Web UI: FastAPI-based dashboard for signup/login/upload/download, with quota progress bars.
Auditing & Security: Bcrypt hashing, rate limiting (lockouts after failed attempts), audit logs for all events.
gRPC Integration: Efficient streaming for large files; JWT interceptors for secure access.

Architecture

Security Service: gRPC server (port 51234) for auth flows, using SQLite for users/OTPs/sessions/audits.
Storage Service: Network controller (port 5000) + nodes (ports 6000+); gRPC for ops, sockets for internal comms; persistent .dat files + JSON metadata.
Merged Backend: Shared SQLite DB (quotas, file ownership); JWT validation on storage RPCs.
UI Layer: FastAPI with Jinja2 templates; calls gRPC via wrappers.
Tech Stack: Python 3, gRPC, FastAPI, SQLite, bcrypt, pyjwt, smtplib.

High-level diagram:
text[User/UI/CLI] --> [FastAPI REST] --> [Security gRPC (Auth/JWT/Quota)] <--> [Shared SQLite DB]
                                      |
                                      v
                               [Storage gRPC (Upload/Download)] <--> [Controller + Nodes (Replication/Failover)]
Setup & Installation

Clone the Repo:textgit clone https://github.com/yourusername/secure-cloud-storage.git
cd secure-cloud-storage
Install Dependencies:textpip install -r requirements.txt(Includes grpcio, grpcio-tools, protobuf, fastapi, uvicorn, jinja2, python-multipart, bcrypt, pyjwt.)
Configure Environment (.env file):textDATABASE_URL=sqlite:///cloud.db  # Or your DB path
JWT_SECRET=your-secret-key-here  # For token signing
SMTP_EMAIL=sasbergson@gmail.com
SMTP_APP_PASSWORD=tgnw azxw lfjr jsuz  # Gmail app password
Generate gRPC Code (if needed):textpython generate_grpc.py
Initialize DB:
Run the system once or manually create tables (see database.py for schema).


Running the System

Full Merged Backend + UI:textpython main.py --secure-storage
Access UI: http://localhost:8000 (signup/login/dashboard).
gRPC Ports: 51234 (security), 5000 (storage controller).

Test Nodes (in separate terminals):textpython main.py --node --node-id node1
python main.py --node --node-id node2

Usage Examples
CLI (client.py)

Signup: python client.py signup rosyy example@email.com NewPassword999! → OTP sent.
Verify OTP: python client.py verify rosyy 123456 signup → Account activated with 1GB quota.
Login: python client.py login rosyy NewPassword999! → OTP sent.
Verify Login OTP: python client.py verify rosyy 654321 login → Get JWT tokens.
Upload File: python client.py upload myfile.txt --token eyJ... → Checks quota, replicates to nodes.
List Files: python client.py list --token eyJ... → Shows owned files with sizes/used quota.
Download: python client.py download abc123 --token eyJ... --save-to localfile.txt.

Web UI

Visit http://localhost:8000/signup → Fill form → OTP email → Verify on /verify-otp.
Login → Dashboard: See file list, quota bar (e.g., "500MB/1GB used"), upload button.
Upload: Select file → If over quota, alert "No more space." Else, progress bar, adds to list.
Download: Click file → Saves locally.

Testing

Basic Tests: python test_persistence.py (verifies storage survives restarts).
Fault Tolerance: python demo_fault_tolerance.py (simulates node failures, failovers).
End-to-End: Signup → Upload small file (success) → Upload over 1GB (fail) → Delete → Download.

Contributing
Fork the repo, create a branch, submit PRs. Focus on: gRPC-Web for UI, more replication, encryption.
License
MIT License. See LICENSE file.
Acknowledgments
Inspired by gRPC demos from Engr. Daniel Moune (ICT University). Evolved into secure storage simulation.
