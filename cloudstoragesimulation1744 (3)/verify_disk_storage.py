#!/usr/bin/env python3
"""
Simple script to verify that files are actually stored on disk.
Run this after creating files through the main.py interface.
"""

import os
import json

def show_storage_structure():
    """Display the storage directory structure and file contents"""
    print("=" * 70)
    print("DISK STORAGE VERIFICATION")
    print("=" * 70)
    
    storage_dir = "storage_data"
    
    if not os.path.exists(storage_dir):
        print(f"\n[!] Storage directory '{storage_dir}' does not exist yet.")
        print("    Create some files first using the main.py interface.")
        return
    
    print(f"\n📁 Storage Directory: {storage_dir}/")
    print("-" * 70)
    
    # Check network registry
    registry_path = os.path.join(storage_dir, "network_registry.json")
    if os.path.exists(registry_path):
        print(f"\n📄 Network Registry: {registry_path}")
        size = os.path.getsize(registry_path)
        print(f"   Size: {size:,} bytes")
        
        try:
            with open(registry_path, 'r') as f:
                registry = json.load(f)
            print(f"   Files tracked: {len(registry.get('file_registry', {}))}")
            print(f"   Nodes tracked: {len(registry.get('node_files', {}))}")
        except Exception as e:
            print(f"   Error reading registry: {e}")
    
    # List all node directories
    total_files = 0
    total_size = 0
    
    for item in os.listdir(storage_dir):
        item_path = os.path.join(storage_dir, item)
        
        if os.path.isdir(item_path):
            print(f"\n📁 Node Directory: {item}/")
            print("   " + "-" * 66)
            
            # Check for metadata
            metadata_path = os.path.join(item_path, "metadata.json")
            metadata = {}
            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                    print(f"   📄 metadata.json ({os.path.getsize(metadata_path):,} bytes)")
                    print(f"      Files in metadata: {len(metadata)}")
                except Exception as e:
                    print(f"   ⚠️  Error reading metadata: {e}")
            
            # List data files
            data_files = [f for f in os.listdir(item_path) if f.endswith('.dat')]
            
            if data_files:
                print(f"\n   💾 Data Files ({len(data_files)} files):")
                for filename in sorted(data_files):
                    file_path = os.path.join(item_path, filename)
                    file_size = os.path.getsize(file_path)
                    total_files += 1
                    total_size += file_size
                    
                    file_id = filename[:-4]  # Remove .dat extension
                    
                    # Get metadata for this file
                    if file_id in metadata:
                        meta = metadata[file_id]
                        original_name = meta.get('file_name', 'unknown')
                        checksum = meta.get('checksum', 'N/A')[:8]
                        print(f"      • {filename}")
                        print(f"        Original name: {original_name}")
                        print(f"        Size: {file_size:,} bytes")
                        print(f"        Checksum: {checksum}...")
                    else:
                        print(f"      • {filename} ({file_size:,} bytes) [no metadata]")
            else:
                print(f"\n   (No .dat files)")
            
            # Check for backup files
            backup_files = [f for f in os.listdir(item_path) if f.endswith('.backup')]
            if backup_files:
                print(f"\n   🔄 Backup Files: {len(backup_files)}")
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total data files: {total_files}")
    print(f"Total storage used: {total_size:,} bytes ({total_size / 1024:.2f} KB)")
    
    if total_files > 0:
        print("\n✅ Files are being stored on disk!")
        print("   You can find them in the storage_data/ directory.")
        print("   These files will persist even after the program stops.")
    else:
        print("\n⚠️  No data files found.")
        print("   Create some files using the main.py interface first.")

def show_file_content(node_id, file_id):
    """Show the content of a specific file"""
    file_path = f"storage_data/{node_id}/{file_id}.dat"
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return
    
    print(f"\n📄 File Content: {file_path}")
    print("-" * 70)
    
    try:
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # Try to decode as text
        try:
            text = content.decode('utf-8')
            print(text)
        except:
            print(f"Binary content ({len(content)} bytes)")
            print(f"First 100 bytes: {content[:100]}")
    except Exception as e:
        print(f"Error reading file: {e}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 2:
        # Show specific file content
        node_id = sys.argv[1]
        file_id = sys.argv[2]
        show_file_content(node_id, file_id)
    else:
        # Show storage structure
        show_storage_structure()
        
        print("\n💡 TIP: To view a specific file's content, run:")
        print("   python verify_disk_storage.py <node_id> <file_id>")

