"""
client.py - gRPC Client for Cloud Security Authentication Service

This module provides a command-line interface to interact with the
Cloud Security gRPC server for authentication operations.

Usage:
    python client.py <command> [arguments]

Examples:
    python client.py signup newuser user@example.com mypassword123
    python client.py verify newuser 123456 signup
    python client.py login johndoe 1234567890
    python client.py verify johndoe 654321 login
"""

import sys
import grpc

import cloudsecurity_pb2
import cloudsecurity_pb2_grpc
from params import GRPC_SERVER_PORT


# Server connection settings
SERVER_ADDRESS = f'localhost:{GRPC_SERVER_PORT}'


def print_usage():
    """Print usage instructions for the CLI."""
    print("""
Cloud Security CLI Client
=========================

Usage:
    python client.py <command> [arguments]

Commands:
    signup <username> <email> <password>     Create a new account
    verify <username> <otp> <type>           Verify OTP (type: signup, login, reset)
    resend <username> <type>                 Resend OTP (type: signup, login, reset)
    login <username> <password>              Login with username and password
    forgot <email>                           Request password reset OTP
    reset <email> <otp> <new_password>       Reset password with OTP
    validate <access_token>                  Validate a JWT access token
    refresh <refresh_token>                  Get new access token using refresh token

    Session Management:
    logout <access_token>                    Logout (revoke current session)
    sessions <access_token>                  View all active sessions
    revoke <access_token> <token_id>         Revoke a specific session
    logoutall <access_token> [keep_current]  Logout from all devices

    Audit Logs:
    logs <access_token> [limit] [event_type] View your audit log history

Examples:
    # Create a new account
    python client.py signup newuser user@example.com mypassword123

    # Verify email after signup
    python client.py verify newuser 123456 signup

    # Login (sends OTP to email)
    python client.py login johndoe 1234567890

    # Verify login OTP
    python client.py verify johndoe 654321 login

    # Resend OTP if expired
    python client.py resend johndoe login

    # Forgot password - request reset OTP
    python client.py forgot user@example.com

    # Reset password with OTP
    python client.py reset user@example.com 123456 newpassword123

    # Validate a JWT token
    python client.py validate <access_token>

    # Refresh access token
    python client.py refresh <refresh_token>
""")


def get_stub():
    """Get a gRPC stub connected to the server."""
    channel = grpc.insecure_channel(SERVER_ADDRESS)
    return cloudsecurity_pb2_grpc.UserServiceStub(channel), channel


def print_response(title: str, message: str, success: bool = None):
    """Print formatted response from server."""
    print(f"\n{'='*50}")
    print(f"{title}")
    print(f"{'='*50}")
    if success is not None:
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"Status: {status}")
    print(f"Message: {message}")
    print(f"{'='*50}\n")


def do_signup(username: str, email: str, password: str) -> None:
    """
    Perform signup request to the gRPC server.

    Args:
        username: Desired username.
        email: Email address.
        password: Password for the account.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Creating account for: {username}")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.Signup(
            cloudsecurity_pb2.SignupRequest(
                username=username,
                email=email,
                password=password
            )
        )

        print_response("Signup Response", response.message, response.success)

        if response.success:
            print("Next step: Check your email and run:")
            print(f"  python client.py verify {username} <OTP_CODE> signup")

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print(f"Make sure the server is running: python cloud.py")


def do_verify(username: str, otp_code: str, otp_type: str) -> None:
    """
    Perform OTP verification request.

    Args:
        username: Username to verify OTP for.
        otp_code: The 6-digit OTP code.
        otp_type: Type of OTP (signup, login, reset).
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Verifying OTP for: {username} (type: {otp_type})")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.VerifyOTP(
            cloudsecurity_pb2.VerifyOTPRequest(
                username=username,
                otp_code=otp_code,
                otp_type=otp_type
            )
        )

        print_response("Verification Response", response.message, response.success)

        if response.success and otp_type == 'signup':
            print("Your email is verified! You can now login:")
            print(f"  python client.py login {username} <your_password>")

        # Display JWT tokens if login verification successful
        if response.success and otp_type == 'login':
            if response.access_token:
                print("="*50)
                print("JWT TOKENS (Save these securely!)")
                print("="*50)
                print(f"\nAccess Token (expires in 15 min):")
                print(f"  {response.access_token[:50]}...")
                print(f"\nRefresh Token (expires in 7 days):")
                print(f"  {response.refresh_token[:50]}...")
                print("\n" + "="*50)
                print("Use these commands with your tokens:")
                print(f"  python client.py validate <access_token>")
                print(f"  python client.py refresh <refresh_token>")
                print("="*50)

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print(f"Make sure the server is running: python cloud.py")


def do_resend(username: str, otp_type: str) -> None:
    """
    Resend OTP to user's email.

    Args:
        username: Username to resend OTP for.
        otp_type: Type of OTP (signup, login, reset).
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Resending OTP for: {username} (type: {otp_type})")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.ResendOTP(
            cloudsecurity_pb2.ResendOTPRequest(
                username=username,
                otp_type=otp_type
            )
        )

        print_response("Resend OTP Response", response.message, response.success)

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print(f"Make sure the server is running: python cloud.py")


def do_login(username: str, password: str) -> None:
    """
    Perform login request to the gRPC server.

    Args:
        username: The username to login with.
        password: The password to authenticate.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        print(f"Sending login request for user: {username}")
        response = stub.login(
            cloudsecurity_pb2.Request(login=username, password=password)
        )

        print(f"\n{'='*50}")
        print(f"Server Response:")
        print(f"{'='*50}")
        print(f"{response.result}")
        print(f"{'='*50}\n")

        if "OTP sent" in response.result:
            print("Next step: Check your email and run:")
            print(f"  python client.py verify {username} <OTP_CODE> login")

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")

    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print(f"Make sure the server is running: python cloud.py")


def do_forgot(email: str) -> None:
    """
    Request password reset OTP.

    Args:
        email: Email address to send reset OTP to.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Requesting password reset for: {email}")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.ForgotPassword(
            cloudsecurity_pb2.ForgotPasswordRequest(
                email=email
            )
        )

        print_response("Forgot Password Response", response.message, response.success)

        if response.success:
            print("Next step: Check your email and run:")
            print(f"  python client.py reset {email} <OTP_CODE> <new_password>")

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print(f"Make sure the server is running: python cloud.py")


def do_reset(email: str, otp_code: str, new_password: str) -> None:
    """
    Reset password with OTP verification.

    Args:
        email: Email address.
        otp_code: The 6-digit OTP code from email.
        new_password: New password to set.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Resetting password for: {email}")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.ResetPassword(
            cloudsecurity_pb2.ResetPasswordRequest(
                email=email,
                otp_code=otp_code,
                new_password=new_password
            )
        )

        print_response("Reset Password Response", response.message, response.success)

        if response.success:
            print("You can now login with your new password!")

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print(f"Make sure the server is running: python cloud.py")


def do_validate(access_token: str) -> None:
    """
    Validate a JWT access token.

    Args:
        access_token: The JWT access token to validate.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Validating access token...")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.ValidateToken(
            cloudsecurity_pb2.ValidateTokenRequest(
                access_token=access_token
            )
        )

        if response.valid:
            print(f"\n{'='*50}")
            print("Token Validation Result")
            print(f"{'='*50}")
            print(f"Status: ✓ VALID")
            print(f"Username: {response.username}")
            print(f"Email: {response.email}")
            print(f"User ID: {response.user_id}")
            print(f"{'='*50}\n")
        else:
            print_response("Token Validation Result", response.message, False)

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print(f"Make sure the server is running: python cloud.py")


def do_refresh(refresh_token: str) -> None:
    """
    Refresh access token using refresh token.

    Args:
        refresh_token: The JWT refresh token.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Refreshing access token...")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.RefreshToken(
            cloudsecurity_pb2.RefreshTokenRequest(
                refresh_token=refresh_token
            )
        )

        print_response("Token Refresh Result", response.message, response.success)

        if response.success:
            print("="*50)
            print("NEW ACCESS TOKEN")
            print("="*50)
            print(f"\nAccess Token (expires in 15 min):")
            print(f"  {response.access_token[:50]}...")
            print("\n" + "="*50)

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print(f"Make sure the server is running: python cloud.py")


# =============================================================================
# Session Management Functions
# =============================================================================

def do_logout(access_token: str) -> None:
    """
    Logout and revoke the current session.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Logging out...")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.Logout(
            cloudsecurity_pb2.LogoutRequest(access_token=access_token)
        )

        print_response("Logout Result", response.message, response.success)
        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")


def do_sessions(access_token: str) -> None:
    """
    Get all active sessions for the current user.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Fetching active sessions...")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.GetSessions(
            cloudsecurity_pb2.GetSessionsRequest(access_token=access_token)
        )

        print_response("Sessions Result", response.message, response.success)

        if response.success and response.sessions:
            print("\n" + "="*60)
            print("ACTIVE SESSIONS")
            print("="*60)
            for i, s in enumerate(response.sessions, 1):
                current = " (CURRENT)" if s.is_current else ""
                print(f"\n  Session #{i}{current}")
                print(f"  Token ID:      {s.token_id[:8]}...")
                print(f"  Device:        {s.device_info}")
                print(f"  IP:            {s.ip_address}")
                print(f"  Created:       {s.created_at}")
                print(f"  Last Activity: {s.last_activity}")
            print("\n" + "="*60)
            print(f"\nTo revoke a session: python client.py revoke <token> <token_id>")

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")


def do_revoke(access_token: str, token_id: str) -> None:
    """
    Revoke a specific session by token_id.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Revoking session: {token_id[:8]}...")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.RevokeSession(
            cloudsecurity_pb2.RevokeSessionRequest(
                access_token=access_token,
                token_id=token_id
            )
        )

        print_response("Revoke Session Result", response.message, response.success)
        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")


def do_logoutall(access_token: str, keep_current: bool = False) -> None:
    """
    Logout from all devices.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Logging out from all devices...")
    if keep_current:
        print("(Keeping current session active)")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.LogoutAll(
            cloudsecurity_pb2.LogoutAllRequest(
                access_token=access_token,
                keep_current=keep_current
            )
        )

        print_response("Logout All Result", response.message, response.success)
        if response.success:
            print(f"Sessions revoked: {response.sessions_revoked}")
        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")


def do_get_logs(access_token: str, limit: int = 50, event_type: str = "") -> None:
    """
    Get audit logs for the current user.
    """
    print(f"\n{'='*50}")
    print(f"Connecting to server at {SERVER_ADDRESS}...")
    print(f"Fetching audit logs (limit: {limit})...")
    if event_type:
        print(f"Filtering by event type: {event_type}")
    print(f"{'='*50}")

    try:
        stub, channel = get_stub()

        response = stub.GetAuditLogs(
            cloudsecurity_pb2.GetAuditLogsRequest(
                access_token=access_token,
                limit=limit,
                event_type=event_type
            )
        )

        print_response("Audit Logs Result", response.message, response.success)

        if response.success and response.logs:
            print(f"\n{'─'*70}")
            print(f"{'ID':<6} {'Event Type':<20} {'Success':<8} {'Timestamp':<20}")
            print(f"{'─'*70}")
            for log in response.logs:
                success_str = "✓" if log.success else "✗"
                print(f"{log.id:<6} {log.event_type:<20} {success_str:<8} {log.created_at:<20}")
                if log.details:
                    print(f"       └─ {log.details}")
            print(f"{'─'*70}")
        elif response.success:
            print("\nNo audit logs found.")

        channel.close()

    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC Error: {e.code().name}")
        print(f"Details: {e.details()}")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")


def main():
    """
    Main entry point for the CLI client.

    Parses command-line arguments and dispatches to the appropriate handler.
    """
    # Check minimum arguments
    if len(sys.argv) < 2:
        print("[ERROR] No command specified.")
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    # -------------------------------------------------------------------------
    # SIGNUP command
    # -------------------------------------------------------------------------
    if command == "signup":
        if len(sys.argv) != 5:
            print("[ERROR] Invalid arguments for signup command.")
            print("Usage: python client.py signup <username> <email> <password>")
            sys.exit(1)

        username = sys.argv[2]
        email = sys.argv[3]
        password = sys.argv[4]

        if not username.strip():
            print("[ERROR] Username cannot be empty.")
            sys.exit(1)
        if not email.strip() or '@' not in email:
            print("[ERROR] Invalid email address.")
            sys.exit(1)
        if not password.strip():
            print("[ERROR] Password cannot be empty.")
            sys.exit(1)

        do_signup(username, email, password)

    # -------------------------------------------------------------------------
    # VERIFY command
    # -------------------------------------------------------------------------
    elif command == "verify":
        if len(sys.argv) != 5:
            print("[ERROR] Invalid arguments for verify command.")
            print("Usage: python client.py verify <username> <otp_code> <type>")
            print("Types: signup, login, reset")
            sys.exit(1)

        username = sys.argv[2]
        otp_code = sys.argv[3]
        otp_type = sys.argv[4].lower()

        if not username.strip():
            print("[ERROR] Username cannot be empty.")
            sys.exit(1)
        if not otp_code.strip() or len(otp_code) != 6:
            print("[ERROR] OTP must be exactly 6 digits.")
            sys.exit(1)
        if otp_type not in ['signup', 'login', 'reset']:
            print("[ERROR] Invalid OTP type. Use: signup, login, or reset")
            sys.exit(1)

        do_verify(username, otp_code, otp_type)

    # -------------------------------------------------------------------------
    # RESEND command
    # -------------------------------------------------------------------------
    elif command == "resend":
        if len(sys.argv) != 4:
            print("[ERROR] Invalid arguments for resend command.")
            print("Usage: python client.py resend <username> <type>")
            print("Types: signup, login, reset")
            sys.exit(1)

        username = sys.argv[2]
        otp_type = sys.argv[3].lower()

        if not username.strip():
            print("[ERROR] Username cannot be empty.")
            sys.exit(1)
        if otp_type not in ['signup', 'login', 'reset']:
            print("[ERROR] Invalid OTP type. Use: signup, login, or reset")
            sys.exit(1)

        do_resend(username, otp_type)

    # -------------------------------------------------------------------------
    # LOGIN command
    # -------------------------------------------------------------------------
    elif command == "login":
        if len(sys.argv) != 4:
            print("[ERROR] Invalid arguments for login command.")
            print("Usage: python client.py login <username> <password>")
            sys.exit(1)

        username = sys.argv[2]
        password = sys.argv[3]

        if not username.strip():
            print("[ERROR] Username cannot be empty.")
            sys.exit(1)
        if not password.strip():
            print("[ERROR] Password cannot be empty.")
            sys.exit(1)

        do_login(username, password)

    # -------------------------------------------------------------------------
    # FORGOT command
    # -------------------------------------------------------------------------
    elif command == "forgot":
        if len(sys.argv) != 3:
            print("[ERROR] Invalid arguments for forgot command.")
            print("Usage: python client.py forgot <email>")
            sys.exit(1)

        email = sys.argv[2]

        if not email.strip() or '@' not in email:
            print("[ERROR] Invalid email address.")
            sys.exit(1)

        do_forgot(email)

    # -------------------------------------------------------------------------
    # RESET command
    # -------------------------------------------------------------------------
    elif command == "reset":
        if len(sys.argv) != 5:
            print("[ERROR] Invalid arguments for reset command.")
            print("Usage: python client.py reset <email> <otp_code> <new_password>")
            sys.exit(1)

        email = sys.argv[2]
        otp_code = sys.argv[3]
        new_password = sys.argv[4]

        if not email.strip() or '@' not in email:
            print("[ERROR] Invalid email address.")
            sys.exit(1)
        if not otp_code.strip() or len(otp_code) != 6:
            print("[ERROR] OTP must be exactly 6 digits.")
            sys.exit(1)
        if not new_password.strip() or len(new_password) < 6:
            print("[ERROR] Password must be at least 6 characters.")
            sys.exit(1)

        do_reset(email, otp_code, new_password)

    # -------------------------------------------------------------------------
    # VALIDATE command (JWT token validation)
    # -------------------------------------------------------------------------
    elif command == "validate":
        if len(sys.argv) != 3:
            print("[ERROR] Invalid arguments for validate command.")
            print("Usage: python client.py validate <access_token>")
            sys.exit(1)

        access_token = sys.argv[2]

        if not access_token.strip():
            print("[ERROR] Access token is required.")
            sys.exit(1)

        do_validate(access_token)

    # -------------------------------------------------------------------------
    # REFRESH command (refresh access token)
    # -------------------------------------------------------------------------
    elif command == "refresh":
        if len(sys.argv) != 3:
            print("[ERROR] Invalid arguments for refresh command.")
            print("Usage: python client.py refresh <refresh_token>")
            sys.exit(1)

        refresh_token = sys.argv[2]

        if not refresh_token.strip():
            print("[ERROR] Refresh token is required.")
            sys.exit(1)

        do_refresh(refresh_token)

    # -------------------------------------------------------------------------
    # LOGOUT command (session management)
    # -------------------------------------------------------------------------
    elif command == "logout":
        if len(sys.argv) != 3:
            print("[ERROR] Invalid arguments for logout command.")
            print("Usage: python client.py logout <access_token>")
            sys.exit(1)

        access_token = sys.argv[2]
        do_logout(access_token)

    # -------------------------------------------------------------------------
    # SESSIONS command (view active sessions)
    # -------------------------------------------------------------------------
    elif command == "sessions":
        if len(sys.argv) != 3:
            print("[ERROR] Invalid arguments for sessions command.")
            print("Usage: python client.py sessions <access_token>")
            sys.exit(1)

        access_token = sys.argv[2]
        do_sessions(access_token)

    # -------------------------------------------------------------------------
    # REVOKE command (revoke specific session)
    # -------------------------------------------------------------------------
    elif command == "revoke":
        if len(sys.argv) != 4:
            print("[ERROR] Invalid arguments for revoke command.")
            print("Usage: python client.py revoke <access_token> <token_id>")
            sys.exit(1)

        access_token = sys.argv[2]
        token_id = sys.argv[3]
        do_revoke(access_token, token_id)

    # -------------------------------------------------------------------------
    # LOGOUTALL command (logout from all devices)
    # -------------------------------------------------------------------------
    elif command == "logoutall":
        if len(sys.argv) < 3:
            print("[ERROR] Invalid arguments for logoutall command.")
            print("Usage: python client.py logoutall <access_token> [keep_current]")
            sys.exit(1)

        access_token = sys.argv[2]
        keep_current = len(sys.argv) > 3 and sys.argv[3].lower() in ['true', 'yes', '1', 'keep']
        do_logoutall(access_token, keep_current)

    # -------------------------------------------------------------------------
    # LOGS command (view audit logs)
    # -------------------------------------------------------------------------
    elif command == "logs":
        if len(sys.argv) < 3:
            print("[ERROR] Invalid arguments for logs command.")
            print("Usage: python client.py logs <access_token> [limit] [event_type]")
            sys.exit(1)

        access_token = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 50
        event_type = sys.argv[4] if len(sys.argv) > 4 else ""
        do_get_logs(access_token, limit, event_type)

    # -------------------------------------------------------------------------
    # HELP command
    # -------------------------------------------------------------------------
    elif command == "help" or command == "--help" or command == "-h":
        print_usage()

    else:
        print(f"[ERROR] Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == '__main__':
    main()