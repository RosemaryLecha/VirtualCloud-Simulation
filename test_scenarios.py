#!/usr/bin/env python3
"""Additional Scenario Tests for Cloud Security & Storage System"""

import sys
import os
import uuid
sys.path.insert(0, 'cloudstoragesimulation1744 (3)')

from database import get_database
from jwt_utils import generate_token_pair, validate_token
from utils import hash_password, verify_password

def print_result(name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}: {name}")
    if details:
        print(f"         {details}")

def test_rate_limiting():
    print("\n--- SCENARIO 1: Rate Limiting ---")
    db = get_database()

    # Create a test user first
    test_user = f'ratelimit_test_{uuid.uuid4().hex[:6]}'
    test_email = f'{test_user}@test.com'
    password_hash = hash_password('TestPass123!')
    user_id = db.create_user(test_user, test_email, password_hash)

    # Simulate 5 failed login attempts (max is 5, lockout is 15 min)
    for i in range(5):
        attempts, is_locked = db.increment_failed_attempts(user_id, 5, 15)

    is_locked, locked_until = db.is_account_locked(user_id)
    print_result("Account locked after 5 attempts", is_locked, f"locked_until={locked_until}")

    # Cleanup
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM login_attempts WHERE username LIKE 'ratelimit_test_%'")
        cursor.execute("DELETE FROM users WHERE username LIKE 'ratelimit_test_%'")
    return is_locked

def test_session_management():
    print("\n--- SCENARIO 2: Session Management ---")
    from datetime import datetime, timedelta
    db = get_database()
    user_id = 999
    token_id = str(uuid.uuid4())
    expires_at = datetime.now() + timedelta(hours=1)

    db.create_session(user_id, token_id, expires_at, device_info='Test Device')
    sessions = db.get_active_sessions(user_id)
    print_result("Session created", len(sessions) > 0, f"count={len(sessions)}")

    db.revoke_session(token_id)
    sessions = db.get_active_sessions(user_id)
    print_result("Session revoked", len(sessions) == 0)

    with db._get_connection() as conn:
        conn.cursor().execute("DELETE FROM sessions WHERE user_id = 999")
    return True

def test_otp_handling():
    print("\n--- SCENARIO 3: OTP Handling ---")
    db = get_database()

    # Create test user for OTP
    test_user = f'otp_test_{uuid.uuid4().hex[:6]}'
    test_email = f'{test_user}@test.com'
    password_hash = hash_password('TestPass123!')
    user_id = db.create_user(test_user, test_email, password_hash)

    # Create OTP for user
    db.create_otp(user_id, '123456', 'signup')

    valid = db.verify_otp(user_id, '123456', 'signup')
    print_result("Correct OTP verified", valid)

    # Wrong OTP should fail (also OTP is already used)
    db.create_otp(user_id, '654321', 'login')
    invalid = db.verify_otp(user_id, '000000', 'login')
    print_result("Wrong OTP rejected", not invalid)

    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM otps WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return valid and not invalid

def test_audit_logging():
    print("\n--- SCENARIO 4: Audit Logging ---")
    db = get_database()
    user_id = 998
    
    events = ['login', 'file_upload', 'file_download', 'logout']
    for event in events:
        db.log_event(event, user_id, 'audituser', f'Test {event}', True)
    
    logs = db.get_user_logs(user_id, limit=10)
    print_result("All events logged", len(logs) >= len(events), f"logged={len(logs)}")
    
    with db._get_connection() as conn:
        conn.cursor().execute("DELETE FROM audit_logs WHERE user_id = 998")
    return len(logs) >= len(events)

def test_jwt_tokens():
    print("\n--- SCENARIO 5: JWT Token Validation ---")
    access, refresh, tid, exp = generate_token_pair(100, 'tokenuser', 'token@test.com')
    
    try:
        payload = validate_token(access, 'access')
        print_result("Access token valid", True, f"user={payload['username']}")
    except Exception as e:
        print_result("Access token valid", False, str(e))
        return False
    
    try:
        payload = validate_token(refresh, 'refresh')
        print_result("Refresh token valid", True)
    except Exception as e:
        print_result("Refresh token valid", False, str(e))
        return False
    
    try:
        validate_token(access, 'refresh')  # Wrong type
        print_result("Wrong type rejected", False)
        return False
    except:
        print_result("Wrong type rejected", True)
    
    return True

def test_quota_edge_cases():
    print("\n--- SCENARIO 6: Storage Quota Edge Cases ---")
    db = get_database()
    user_id = 997
    
    db.set_user_quota(user_id, 1000)
    
    has_space, _ = db.check_quota_available(user_id, 1000)
    print_result("Exact quota allowed", has_space, "1000/1000 bytes")
    
    over, _ = db.check_quota_available(user_id, 1001)
    print_result("Over quota rejected", not over, "1001/1000 bytes")
    
    with db._get_connection() as conn:
        conn.cursor().execute("DELETE FROM user_storage_quotas WHERE user_id = 997")
    return has_space and not over

def main():
    print("\n" + "="*60)
    print("  ADDITIONAL SCENARIO TESTS")
    print("="*60)
    
    results = []
    results.append(("Rate Limiting", test_rate_limiting()))
    results.append(("Session Management", test_session_management()))
    results.append(("OTP Handling", test_otp_handling()))
    results.append(("Audit Logging", test_audit_logging()))
    results.append(("JWT Tokens", test_jwt_tokens()))
    results.append(("Quota Edge Cases", test_quota_edge_cases()))
    
    print("\n" + "="*60)
    print("  SUMMARY")
    print("="*60)
    all_passed = True
    for name, passed in results:
        status = "✅" if passed else "❌"
        print(f"  {status} {name}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("  ALL SCENARIO TESTS PASSED! ✅")
    else:
        print("  SOME TESTS FAILED ❌")
    print("="*60 + "\n")
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())

