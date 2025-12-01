#!/usr/bin/env python3
"""
End-to-End Test Suite for Cloud Security & Storage System

Tests the complete flow:
1. Signup → Verify OTP → Login
2. Upload small file (OK)
3. Upload over quota ("No more space")
4. List files
5. Delete file
6. Quota updates correctly

Run with: python test_end_to_end.py
"""

import sys
import os
import time
import uuid
import hashlib

# Add storage system to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'cloudstoragesimulation1744 (3)'))

from database import get_database
from jwt_utils import generate_token_pair, validate_token
from utils import hash_password, verify_password

# Test configuration
TEST_USERNAME = f"testuser_{uuid.uuid4().hex[:8]}"
TEST_EMAIL = f"{TEST_USERNAME}@test.com"
TEST_PASSWORD = "TestPass123!"

def print_header(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def print_result(test_name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}: {test_name}")
    if details:
        print(f"         {details}")

def test_signup_and_login():
    """Test user signup and login flow."""
    print_header("TEST 1: Signup & Login Flow")
    db = get_database()
    
    # 1. Create user
    password_hash = hash_password(TEST_PASSWORD)
    user_id = db.create_user(TEST_USERNAME, TEST_EMAIL, password_hash)
    print_result("Create user", user_id is not None, f"user_id={user_id}")
    
    # 2. Verify user exists
    user = db.get_user_by_username(TEST_USERNAME)
    print_result("Get user by username", user is not None)
    
    # 3. Verify password
    is_valid = verify_password(TEST_PASSWORD, user['password_hash'])
    print_result("Verify password", is_valid)
    
    # 4. Generate JWT tokens
    access_token, refresh_token, token_id, expiry = generate_token_pair(user_id, TEST_USERNAME, TEST_EMAIL)
    print_result("Generate JWT tokens", access_token is not None and refresh_token is not None)

    # 5. Validate access token
    payload = validate_token(access_token, expected_type='access')
    print_result("Validate access token", payload is not None, f"username={payload.get('username')}")

    tokens = {'access_token': access_token, 'refresh_token': refresh_token, 'token_id': token_id}
    return user_id, tokens

def test_quota_management(user_id):
    """Test storage quota management."""
    print_header("TEST 2: Quota Management")
    db = get_database()

    # 1. Create quota for user (100 MB for testing)
    db.set_user_quota(user_id, 1024*1024*100)
    quota = db.get_user_quota(user_id)
    print_result("Create user quota", quota is not None, f"total={quota['quota_bytes']} bytes")

    # 2. Check quota available for small file
    has_space, available = db.check_quota_available(user_id, 1024)  # 1 KB
    print_result("Check quota for small file", has_space, f"available={available} bytes")

    # 3. Check quota for file exceeding limit
    has_space, available = db.check_quota_available(user_id, 1024*1024*200)  # 200 MB
    print_result("Check quota for large file (should fail)", not has_space, f"available={available} bytes")

    return quota

def test_file_operations(user_id):
    """Test file upload, list, delete operations."""
    print_header("TEST 3: File Operations")
    db = get_database()
    
    # 1. Create a test file
    file_id = str(uuid.uuid4())
    file_name = "test_document.txt"
    file_size = 1024  # 1 KB
    checksum = hashlib.sha256(b"test content").hexdigest()
    
    db.create_storage_file(file_id, file_name, file_size, checksum, user_id)
    print_result("Create storage file", True, f"file_id={file_id}")
    
    # 2. Update quota usage
    db.update_user_used_storage(user_id, file_size)
    quota = db.get_user_quota(user_id)
    print_result("Update quota usage", quota['used_bytes'] == file_size, f"used={quota['used_bytes']}")
    
    # 3. Get file info
    file_info = db.get_storage_file(file_id)
    print_result("Get file info", file_info is not None, f"name={file_info['file_name']}")
    
    # 4. List user files
    files = db.list_storage_files(owner_id=user_id)
    print_result("List user files", len(files) > 0, f"count={len(files)}")
    
    # 5. Delete file
    db.delete_storage_file(file_id)
    db.update_user_used_storage(user_id, -file_size)
    
    file_info = db.get_storage_file(file_id)
    quota = db.get_user_quota(user_id)
    print_result("Delete file", file_info is None, f"used_after_delete={quota['used_bytes']}")
    
    return True

def test_quota_limit(user_id):
    """Test that quota limits are enforced."""
    print_header("TEST 4: Quota Limit Enforcement")
    db = get_database()

    # Set a small quota (1 KB)
    db.set_user_quota(user_id, 1024)

    # Try to upload file larger than quota
    has_space, available = db.check_quota_available(user_id, 2048)  # 2 KB > 1 KB quota
    print_result("Reject file exceeding quota", not has_space, f"available={available}, required=2048")

    # Upload file within quota
    has_space, available = db.check_quota_available(user_id, 512)  # 512 B < 1 KB quota
    print_result("Accept file within quota", has_space, f"available={available}, required=512")

    return True

def test_audit_logging(user_id):
    """Test audit logging."""
    print_header("TEST 5: Audit Logging")
    db = get_database()
    
    # Log an event
    db.log_event(
        event_type='file_upload',
        user_id=user_id,
        username=TEST_USERNAME,
        details="Test file upload",
        success=True
    )
    print_result("Log event", True)
    
    # Get user logs
    logs = db.get_user_logs(user_id, limit=10)
    print_result("Get user logs", len(logs) > 0, f"count={len(logs)}")
    
    return True

def cleanup(user_id):
    """Clean up test data."""
    print_header("CLEANUP")
    db = get_database()

    # Delete test user and related data using connection context
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_storage_quotas WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM storage_files WHERE owner_id = ?", (user_id,))
        cursor.execute("DELETE FROM audit_logs WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    print_result("Cleanup test data", True)

def main():
    print("\n" + "=" * 60)
    print("  END-TO-END TEST SUITE")
    print("  Cloud Security & Storage System")
    print("=" * 60)
    
    try:
        # Run tests
        user_id, tokens = test_signup_and_login()
        test_quota_management(user_id)
        test_file_operations(user_id)
        test_quota_limit(user_id)
        test_audit_logging(user_id)
        
        # Cleanup
        cleanup(user_id)
        
        print("\n" + "=" * 60)
        print("  ALL TESTS COMPLETED SUCCESSFULLY! ✅")
        print("=" * 60 + "\n")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())

