#!/usr/bin/env python3
"""
Unified Main - Cloud Security & Storage System

This module launches both the authentication system and the distributed
storage system in a single process, providing a complete cloud platform.

Components:
- Auth gRPC Server (port 51234): User authentication, JWT tokens
- Auth REST API (port 8000): HTTP endpoints for web access
- Storage Network Controller (port 5000): Node coordination
- Storage gRPC Server (port 50051): File operations with JWT auth

Usage:
    python unified_main.py [--no-auth-grpc] [--no-rest] [--no-storage] [--require-storage-auth]
"""

import sys
import os
import time
import signal
import argparse
import threading
import logging
from concurrent import futures

# Add storage system to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'cloudstoragesimulation1744 (3)'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global references for cleanup
auth_grpc_server = None
rest_api_thread = None
storage_network = None
running = True


def start_auth_grpc_server():
    """Start the authentication gRPC server."""
    global auth_grpc_server
    import grpc
    import cloudsecurity_pb2_grpc
    from cloud import UserServiceSkeleton
    from params import GRPC_SERVER_PORT, GRPC_MAX_WORKERS

    auth_grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=GRPC_MAX_WORKERS))
    cloudsecurity_pb2_grpc.add_UserServiceServicer_to_server(UserServiceSkeleton(), auth_grpc_server)
    auth_grpc_server.add_insecure_port(f'[::]:{GRPC_SERVER_PORT}')
    auth_grpc_server.start()
    logger.info(f"[Auth] gRPC server started on port {GRPC_SERVER_PORT}")
    return auth_grpc_server


def start_rest_api():
    """Start the REST API server in a separate thread."""
    import uvicorn
    from rest_api import app
    
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def start_storage_system(require_auth: bool = False):
    """Start the distributed storage system."""
    global storage_network
    from storage_virtual_network import StorageVirtualNetwork
    from database import get_database
    
    # Get shared database for quota checking
    db = get_database() if require_auth else None
    
    storage_network = StorageVirtualNetwork(
        host='localhost',
        port=5000,
        grpc_port=50051,
        enable_grpc=True,
        require_auth=require_auth,
        database=db
    )
    logger.info("[Storage] Network controller started")
    return storage_network


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    logger.info("\nShutdown signal received...")
    running = False


def main():
    global rest_api_thread, running
    
    parser = argparse.ArgumentParser(description='Unified Cloud Security & Storage System')
    parser.add_argument('--no-auth-grpc', action='store_true', help='Disable auth gRPC server')
    parser.add_argument('--no-rest', action='store_true', help='Disable REST API')
    parser.add_argument('--no-storage', action='store_true', help='Disable storage system')
    parser.add_argument('--require-storage-auth', action='store_true', 
                        help='Require JWT auth for storage operations')
    args = parser.parse_args()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("=" * 60)
    print("UNIFIED CLOUD SECURITY & STORAGE SYSTEM")
    print("=" * 60)
    
    try:
        # Start Auth gRPC Server
        if not args.no_auth_grpc:
            start_auth_grpc_server()
        
        # Start REST API in background thread
        if not args.no_rest:
            rest_api_thread = threading.Thread(target=start_rest_api, daemon=True)
            rest_api_thread.start()
            logger.info("[REST] API server starting on port 8000")
        
        # Start Storage System
        if not args.no_storage:
            start_storage_system(require_auth=args.require_storage_auth)
        
        print("\n" + "=" * 60)
        print("SYSTEM READY")
        print("=" * 60)
        print("\nEndpoints:")
        if not args.no_auth_grpc:
            print("  - Auth gRPC:     localhost:51234")
        if not args.no_rest:
            print("  - REST API:      http://localhost:8000")
            print("  - API Docs:      http://localhost:8000/docs")
        if not args.no_storage:
            print("  - Storage Ctrl:  localhost:5000 (socket)")
            print("  - Storage gRPC:  localhost:50051")
        print("\nPress Ctrl+C to shutdown...")
        
        # Keep main thread alive
        while running:
            time.sleep(1)
            
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down...")
        if storage_network:
            storage_network.shutdown()
        if auth_grpc_server:
            auth_grpc_server.stop(grace=5)
        print("Shutdown complete.")


if __name__ == '__main__':
    main()

