#!/usr/bin/env python3
"""
Script to generate gRPC Python files from proto definitions.
Run this script to generate cloud_storage_pb2.py and cloud_storage_pb2_grpc.py
"""

import subprocess
import sys
import os

def generate_grpc_files():
    """Generate Python gRPC files from proto definition"""
    try:
        # Check if grpcio-tools is available
        import grpc_tools.protoc
        
        # Generate the Python files
        command = [
            sys.executable, '-m', 'grpc_tools.protoc',
            '--proto_path=.',
            '--python_out=.',
            '--grpc_python_out=.',
            'cloud_storage.proto'
        ]
        
        result = subprocess.run(command, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Successfully generated gRPC files:")
            print("- cloud_storage_pb2.py")
            print("- cloud_storage_pb2_grpc.py")
            
            # Create __init__.py if it doesn't exist
            if not os.path.exists('__init__.py'):
                with open('__init__.py', 'w') as f:
                    f.write('# Cloud Storage Simulation Package\n')
                print("- __init__.py")
                
        else:
            print("Error generating gRPC files:")
            print(result.stderr)
            return False
            
    except ImportError:
        print("Error: grpcio-tools not found.")
        print("Please install it with: pip install grpcio-tools")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False
    
    return True

if __name__ == '__main__':
    print("Generating gRPC Python files...")
    if generate_grpc_files():
        print("\nTo use the gRPC services, make sure you have installed:")
        print("pip install grpcio grpcio-tools")
        print("\nYou can now run the cloud storage simulation with gRPC support!")
    else:
        print("\nFailed to generate gRPC files. Please check the error messages above.")
        sys.exit(1)
