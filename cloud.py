"""
cloud.py - gRPC Server for Cloud Security Authentication Service

This module implements the UserService gRPC server that handles:
- User login with password verification
- OTP generation and email delivery

Usage:
    python cloud.py

The server listens on port 51234 by default.
"""

import grpc
import logging
import re
import sys
from concurrent import futures
from typing import Optional

import cloudsecurity_pb2
import cloudsecurity_pb2_grpc
from utils import send_otp, verify_password, generate_otp, hash_password
from database import get_database
from params import (
    GRPC_SERVER_PORT, GRPC_MAX_WORKERS, LOG_LEVEL,
    MAX_LOGIN_ATTEMPTS, LOCKOUT_DURATION_MINUTES
)
from jwt_utils import (
    generate_token_pair, validate_token, refresh_access_token,
    TokenError, get_token_id
)

# =============================================================================
# Logging Configuration
# =============================================================================
def setup_logging():
    """Configure logging for the application."""
    # Map string log level to logging constant
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    level = level_map.get(LOG_LEVEL.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=level,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Reduce noise from grpc internals
    logging.getLogger('grpc').setLevel(logging.WARNING)

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)


class UserServiceSkeleton(cloudsecurity_pb2_grpc.UserServiceServicer):
    """
    Implementation of the UserService gRPC service.

    Handles authentication requests including login with password
    verification and OTP delivery.
    """

    def __init__(self):
        """Initialize the UserService with database connection."""
        self.db = get_database()
        logger.debug("UserService initialized with database connection")

    def login(self, request, context) -> cloudsecurity_pb2.Response:
        """
        Handle login RPC request.

        Validates user credentials and sends OTP if successful.

        Args:
            request: LoginRequest containing 'login' (username) and 'password'.
            context: gRPC context for the request.

        Returns:
            Response with result message indicating success or failure.
        """
        logger.info(f"Login request received for user: {request.login}")

        # Validate input
        if not request.login or not request.password:
            logger.warning("Login failed: Empty username or password")
            return cloudsecurity_pb2.Response(
                result="Error: Username and password are required."
            )

        # Verify credentials and send OTP
        result = self._verify_and_send_otp(request.login, request.password)
        return cloudsecurity_pb2.Response(result=result)

    def _verify_and_send_otp(self, username: str, password: str) -> str:
        """
        Verify user credentials and send OTP if valid.

        Implements rate limiting and account lockout for security.

        Args:
            username: The username to authenticate.
            password: The plaintext password to verify.

        Returns:
            Success message with OTP status, or error message.
        """
        try:
            # Load user from database
            user = self.db.get_user_by_username(username)

            if user is None:
                # Record failed attempt even for non-existent users (security audit)
                self.db.record_login_attempt(
                    username=username,
                    user_id=None,
                    success=False,
                    failure_reason="User not found"
                )
                logger.warning(f"Login failed: User '{username}' not found")
                return "Unauthorized: Invalid username or password."

            user_id = user['id']
            email = user['email']
            password_hash = user['password_hash']
            failed_attempts = user.get('failed_login_attempts', 0)

            # Check if account is locked
            is_locked, locked_until = self.db.is_account_locked(user_id)
            if is_locked:
                # Record the attempt
                self.db.record_login_attempt(
                    username=username,
                    user_id=user_id,
                    success=False,
                    failure_reason="Account locked"
                )
                # Calculate remaining lockout time
                from datetime import datetime
                remaining = locked_until - datetime.now()
                remaining_mins = max(1, int(remaining.total_seconds() / 60))
                logger.warning(f"Login blocked: Account locked for '{username}' ({remaining_mins} min remaining)")
                return f"Error: Account is temporarily locked. Try again in {remaining_mins} minute(s)."

            # Check if account is active
            if not user['is_active']:
                self.db.record_login_attempt(
                    username=username,
                    user_id=user_id,
                    success=False,
                    failure_reason="Account disabled"
                )
                logger.warning(f"Login failed: Account disabled for '{username}'")
                return "Error: Account is disabled. Please contact support."

            # Verify password using bcrypt
            if verify_password(password, password_hash):
                logger.info(f"Password verified for user '{username}'")

                # Record successful login attempt
                self.db.record_login_attempt(
                    username=username,
                    user_id=user_id,
                    success=True
                )

                # Reset failed login attempts on successful login
                self.db.reset_failed_login(user_id)

                # Generate OTP and store in database
                otp_code = generate_otp()
                self.db.create_otp(user_id, otp_code, otp_type='login')

                # Audit log: LOGIN_OTP_SENT
                self.db.log_event(
                    event_type='LOGIN_OTP_SENT',
                    user_id=user_id,
                    username=username,
                    details="Password verified, OTP sent for 2FA",
                    success=True
                )

                # Send OTP via email
                logger.debug(f"Sending OTP to {email}")
                return send_otp(email, otp_code)
            else:
                # Increment failed login attempts
                failed_count = self.db.increment_failed_login(user_id)
                attempts_remaining = MAX_LOGIN_ATTEMPTS - failed_count

                # Record failed attempt
                self.db.record_login_attempt(
                    username=username,
                    user_id=user_id,
                    success=False,
                    failure_reason="Invalid password"
                )

                # Audit log: LOGIN_FAILED
                self.db.log_event(
                    event_type='LOGIN_FAILED',
                    user_id=user_id,
                    username=username,
                    details=f"Invalid password. Attempt {failed_count}/{MAX_LOGIN_ATTEMPTS}",
                    success=False
                )

                logger.warning(f"Login failed: Invalid password for '{username}' (attempt {failed_count}/{MAX_LOGIN_ATTEMPTS})")

                # Check if account is now locked
                if failed_count >= MAX_LOGIN_ATTEMPTS:
                    # Audit log: ACCOUNT_LOCKED
                    self.db.log_event(
                        event_type='ACCOUNT_LOCKED',
                        user_id=user_id,
                        username=username,
                        details=f"Account locked after {MAX_LOGIN_ATTEMPTS} failed attempts",
                        success=False
                    )
                    return f"Error: Account locked due to too many failed attempts. Try again in {LOCKOUT_DURATION_MINUTES} minutes."
                elif attempts_remaining <= 2:
                    # Warn user they're close to lockout
                    return f"Unauthorized: Invalid password. Warning: {attempts_remaining} attempt(s) remaining before lockout."
                else:
                    return "Unauthorized: Invalid username or password."

        except Exception as e:
            logger.exception(f"Unexpected error during login: {e}")
            return "Error: An unexpected error occurred. Please try again."

    # =========================================================================
    # Signup RPC
    # =========================================================================

    def Signup(self, request, context) -> cloudsecurity_pb2.SignupResponse:
        """
        Handle Signup RPC request.

        Creates a new user account and sends verification OTP.

        Args:
            request: SignupRequest with username, email, password.
            context: gRPC context.

        Returns:
            SignupResponse with success status and message.
        """
        logger.info(f"Signup request received for: {request.username}")

        # Validate input
        validation_error = self._validate_signup_input(
            request.username, request.email, request.password
        )
        if validation_error:
            logger.warning(f"Signup validation failed: {validation_error}")
            return cloudsecurity_pb2.SignupResponse(
                success=False,
                message=validation_error,
                user_id=0
            )

        try:
            # Check if username already exists
            if self.db.user_exists(username=request.username):
                logger.warning(f"Signup failed: Username '{request.username}' already exists")
                return cloudsecurity_pb2.SignupResponse(
                    success=False,
                    message="Error: Username already taken.",
                    user_id=0
                )

            # Check if email already exists
            if self.db.user_exists(email=request.email):
                logger.warning(f"Signup failed: Email '{request.email}' already exists")
                return cloudsecurity_pb2.SignupResponse(
                    success=False,
                    message="Error: Email already registered.",
                    user_id=0
                )

            # Hash password and create user
            password_hash = hash_password(request.password)
            user_id = self.db.create_user(
                username=request.username,
                email=request.email,
                password_hash=password_hash,
                is_verified=False  # Not verified until OTP confirmed
            )

            if not user_id:
                logger.error(f"Signup failed: Could not create user '{request.username}'")
                return cloudsecurity_pb2.SignupResponse(
                    success=False,
                    message="Error: Could not create account. Please try again.",
                    user_id=0
                )

            # Generate and send verification OTP
            otp_code = generate_otp()
            self.db.create_otp(user_id, otp_code, otp_type='signup')

            email_result = send_otp(request.email, otp_code)
            logger.info(f"Signup successful for '{request.username}', verification OTP sent")

            # Audit log: SIGNUP
            self.db.log_event(
                event_type='SIGNUP',
                user_id=user_id,
                username=request.username,
                details=f"Account created. Email: {request.email}",
                success=True
            )

            return cloudsecurity_pb2.SignupResponse(
                success=True,
                message=f"Account created! {email_result} Please verify your email.",
                user_id=user_id
            )

        except Exception as e:
            logger.exception(f"Unexpected error during signup: {e}")
            # Audit log: SIGNUP_FAILED
            self.db.log_event(
                event_type='SIGNUP_FAILED',
                username=request.username,
                details=f"Signup error: {str(e)}",
                success=False
            )
            return cloudsecurity_pb2.SignupResponse(
                success=False,
                message="Error: An unexpected error occurred. Please try again.",
                user_id=0
            )

    def _validate_signup_input(self, username: str, email: str, password: str) -> Optional[str]:
        """
        Validate signup input fields.

        Returns:
            Error message string if validation fails, None if valid.
        """
        # Username validation
        if not username or len(username) < 3:
            return "Error: Username must be at least 3 characters."
        if len(username) > 50:
            return "Error: Username must be less than 50 characters."
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return "Error: Username can only contain letters, numbers, and underscores."

        # Email validation
        if not email:
            return "Error: Email is required."
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return "Error: Invalid email format."

        # Password validation
        if not password or len(password) < 6:
            return "Error: Password must be at least 6 characters."
        if len(password) > 128:
            return "Error: Password must be less than 128 characters."

        return None

    # =========================================================================
    # VerifyOTP RPC
    # =========================================================================

    def VerifyOTP(self, request, context) -> cloudsecurity_pb2.VerifyOTPResponse:
        """
        Handle VerifyOTP RPC request.

        Verifies an OTP code for signup, login, or password reset.

        Args:
            request: VerifyOTPRequest with username, otp_code, otp_type.
            context: gRPC context.

        Returns:
            VerifyOTPResponse with success status and message.
        """
        logger.info(f"VerifyOTP request for user: {request.username}, type: {request.otp_type}")

        # Validate input
        if not request.username:
            return cloudsecurity_pb2.VerifyOTPResponse(
                success=False,
                message="Error: Username is required."
            )

        if not request.otp_code or len(request.otp_code) != 6:
            return cloudsecurity_pb2.VerifyOTPResponse(
                success=False,
                message="Error: Invalid OTP code. Must be 6 digits."
            )

        otp_type = request.otp_type if request.otp_type else 'login'
        if otp_type not in ['signup', 'login', 'reset']:
            return cloudsecurity_pb2.VerifyOTPResponse(
                success=False,
                message="Error: Invalid OTP type."
            )

        try:
            # Get user
            user = self.db.get_user_by_username(request.username)
            if not user:
                logger.warning(f"VerifyOTP failed: User '{request.username}' not found")
                return cloudsecurity_pb2.VerifyOTPResponse(
                    success=False,
                    message="Error: User not found."
                )

            user_id = user['id']

            # Verify OTP
            if self.db.verify_otp(user_id, request.otp_code, otp_type):
                logger.info(f"OTP verified for user '{request.username}', type: {otp_type}")

                # If signup verification, mark user as verified
                if otp_type == 'signup':
                    self.db.verify_user_email(user_id)
                    # Audit log: EMAIL_VERIFIED
                    self.db.log_event(
                        event_type='EMAIL_VERIFIED',
                        user_id=user_id,
                        username=request.username,
                        details="Email verification completed",
                        success=True
                    )
                    return cloudsecurity_pb2.VerifyOTPResponse(
                        success=True,
                        message="Email verified successfully! You can now login."
                    )

                # If login verification, generate JWT tokens and create session
                elif otp_type == 'login':
                    # Generate JWT token pair with session token_id
                    access_token, refresh_token, token_id, expiry = generate_token_pair(
                        user_id=user_id,
                        username=user['username'],
                        email=user['email']
                    )

                    # Create session in database
                    self.db.create_session(
                        user_id=user_id,
                        token_id=token_id,
                        expires_at=expiry,
                        device_info="gRPC Client"  # Could be extracted from metadata
                    )
                    logger.info(f"Session created for user '{request.username}' (token_id: {token_id[:8]}...)")

                    # Audit log: LOGIN_SUCCESS
                    self.db.log_event(
                        event_type='LOGIN_SUCCESS',
                        user_id=user_id,
                        username=request.username,
                        details=f"Login successful. Session: {token_id[:8]}...",
                        success=True
                    )

                    return cloudsecurity_pb2.VerifyOTPResponse(
                        success=True,
                        message="Login successful! Welcome.",
                        access_token=access_token,
                        refresh_token=refresh_token
                    )

                # Password reset verification
                else:
                    return cloudsecurity_pb2.VerifyOTPResponse(
                        success=True,
                        message="OTP verified. You can now reset your password."
                    )
            else:
                logger.warning(f"VerifyOTP failed: Invalid or expired OTP for '{request.username}'")
                # Audit log: OTP_FAILED
                self.db.log_event(
                    event_type='OTP_FAILED',
                    user_id=user_id,
                    username=request.username,
                    details=f"Invalid/expired OTP for {otp_type}",
                    success=False
                )
                return cloudsecurity_pb2.VerifyOTPResponse(
                    success=False,
                    message="Error: Invalid or expired OTP code."
                )

        except Exception as e:
            logger.exception(f"Unexpected error during OTP verification: {e}")
            return cloudsecurity_pb2.VerifyOTPResponse(
                success=False,
                message="Error: An unexpected error occurred. Please try again."
            )

    # =========================================================================
    # ResendOTP RPC
    # =========================================================================

    def ResendOTP(self, request, context) -> cloudsecurity_pb2.ResendOTPResponse:
        """
        Handle ResendOTP RPC request.

        Generates a new OTP and sends it to the user's email.

        Args:
            request: ResendOTPRequest with username and otp_type.
            context: gRPC context.

        Returns:
            ResendOTPResponse with success status and message.
        """
        logger.info(f"ResendOTP request for user: {request.username}, type: {request.otp_type}")

        # Validate input
        if not request.username:
            return cloudsecurity_pb2.ResendOTPResponse(
                success=False,
                message="Error: Username is required."
            )

        otp_type = request.otp_type if request.otp_type else 'login'
        if otp_type not in ['signup', 'login', 'reset']:
            return cloudsecurity_pb2.ResendOTPResponse(
                success=False,
                message="Error: Invalid OTP type."
            )

        try:
            # Get user
            user = self.db.get_user_by_username(request.username)
            if not user:
                logger.warning(f"ResendOTP failed: User '{request.username}' not found")
                return cloudsecurity_pb2.ResendOTPResponse(
                    success=False,
                    message="Error: User not found."
                )

            user_id = user['id']
            email = user['email']

            # Generate and send new OTP
            otp_code = generate_otp()
            self.db.create_otp(user_id, otp_code, otp_type=otp_type)

            email_result = send_otp(email, otp_code)
            logger.info(f"OTP resent to '{request.username}' for {otp_type}")

            return cloudsecurity_pb2.ResendOTPResponse(
                success=True,
                message=f"New OTP sent! {email_result}"
            )

        except Exception as e:
            logger.exception(f"Unexpected error during OTP resend: {e}")
            return cloudsecurity_pb2.ResendOTPResponse(
                success=False,
                message="Error: An unexpected error occurred. Please try again."
            )

    # =========================================================================
    # ForgotPassword RPC
    # =========================================================================

    def ForgotPassword(self, request, context) -> cloudsecurity_pb2.ForgotPasswordResponse:
        """
        Handle ForgotPassword RPC request.

        Sends a password reset OTP to the user's email.

        Args:
            request: ForgotPasswordRequest with email.
            context: gRPC context.

        Returns:
            ForgotPasswordResponse with success status and message.
        """
        logger.info(f"ForgotPassword request for email: {request.email}")

        # Validate email
        if not request.email:
            return cloudsecurity_pb2.ForgotPasswordResponse(
                success=False,
                message="Error: Email is required."
            )

        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, request.email):
            return cloudsecurity_pb2.ForgotPasswordResponse(
                success=False,
                message="Error: Invalid email format."
            )

        try:
            # Get user by email
            user = self.db.get_user_by_email(request.email)
            if not user:
                # Don't reveal if email exists or not (security best practice)
                logger.warning(f"ForgotPassword: Email '{request.email}' not found")
                return cloudsecurity_pb2.ForgotPasswordResponse(
                    success=True,
                    message="If this email is registered, a reset OTP has been sent."
                )

            user_id = user['id']

            # Generate and send reset OTP
            otp_code = generate_otp()
            self.db.create_otp(user_id, otp_code, otp_type='reset')

            email_result = send_otp(request.email, otp_code)
            logger.info(f"Password reset OTP sent to '{request.email}'")

            return cloudsecurity_pb2.ForgotPasswordResponse(
                success=True,
                message=f"Password reset OTP sent! {email_result}"
            )

        except Exception as e:
            logger.exception(f"Unexpected error during forgot password: {e}")
            return cloudsecurity_pb2.ForgotPasswordResponse(
                success=False,
                message="Error: An unexpected error occurred. Please try again."
            )

    # =========================================================================
    # ResetPassword RPC
    # =========================================================================

    def ResetPassword(self, request, context) -> cloudsecurity_pb2.ResetPasswordResponse:
        """
        Handle ResetPassword RPC request.

        Verifies the reset OTP and updates the user's password.

        Args:
            request: ResetPasswordRequest with email, otp_code, new_password.
            context: gRPC context.

        Returns:
            ResetPasswordResponse with success status and message.
        """
        logger.info(f"ResetPassword request for email: {request.email}")

        # Validate inputs
        if not request.email:
            return cloudsecurity_pb2.ResetPasswordResponse(
                success=False,
                message="Error: Email is required."
            )

        if not request.otp_code or len(request.otp_code) != 6:
            return cloudsecurity_pb2.ResetPasswordResponse(
                success=False,
                message="Error: Invalid OTP code. Must be 6 digits."
            )

        if not request.new_password or len(request.new_password) < 6:
            return cloudsecurity_pb2.ResetPasswordResponse(
                success=False,
                message="Error: Password must be at least 6 characters."
            )

        if len(request.new_password) > 128:
            return cloudsecurity_pb2.ResetPasswordResponse(
                success=False,
                message="Error: Password must be less than 128 characters."
            )

        try:
            # Get user by email
            user = self.db.get_user_by_email(request.email)
            if not user:
                logger.warning(f"ResetPassword failed: Email '{request.email}' not found")
                return cloudsecurity_pb2.ResetPasswordResponse(
                    success=False,
                    message="Error: Invalid email or OTP."
                )

            user_id = user['id']

            # Verify reset OTP
            if not self.db.verify_otp(user_id, request.otp_code, 'reset'):
                logger.warning(f"ResetPassword failed: Invalid OTP for '{request.email}'")
                return cloudsecurity_pb2.ResetPasswordResponse(
                    success=False,
                    message="Error: Invalid or expired OTP code."
                )

            # Hash new password and update
            new_password_hash = hash_password(request.new_password)
            if self.db.update_user(user_id, password_hash=new_password_hash):
                logger.info(f"Password reset successful for '{request.email}'")
                # Audit log: PASSWORD_RESET
                self.db.log_event(
                    event_type='PASSWORD_RESET',
                    user_id=user_id,
                    username=user['username'],
                    details="Password changed via reset flow",
                    success=True
                )
                return cloudsecurity_pb2.ResetPasswordResponse(
                    success=True,
                    message="Password reset successful! You can now login with your new password."
                )
            else:
                logger.error(f"ResetPassword failed: Could not update password for '{request.email}'")
                return cloudsecurity_pb2.ResetPasswordResponse(
                    success=False,
                    message="Error: Could not update password. Please try again."
                )

        except Exception as e:
            logger.exception(f"Unexpected error during password reset: {e}")
            return cloudsecurity_pb2.ResetPasswordResponse(
                success=False,
                message="Error: An unexpected error occurred. Please try again."
            )

    # =========================================================================
    # ValidateToken RPC
    # =========================================================================

    def ValidateToken(self, request, context) -> cloudsecurity_pb2.ValidateTokenResponse:
        """
        Handle ValidateToken RPC request.

        Validates a JWT access token and returns user information if valid.

        Args:
            request: ValidateTokenRequest with access_token.
            context: gRPC context.

        Returns:
            ValidateTokenResponse with validation result and user info.
        """
        logger.info("ValidateToken request received")

        if not request.access_token:
            return cloudsecurity_pb2.ValidateTokenResponse(
                valid=False,
                message="Error: Access token is required."
            )

        try:
            # Validate the token
            payload = validate_token(request.access_token, expected_type='access')

            logger.info(f"Token validated for user: {payload.get('username')}")
            return cloudsecurity_pb2.ValidateTokenResponse(
                valid=True,
                message="Token is valid.",
                username=payload.get('username', ''),
                email=payload.get('email', ''),
                user_id=payload.get('user_id', 0)
            )

        except TokenError as e:
            logger.warning(f"Token validation failed: {str(e)}")
            return cloudsecurity_pb2.ValidateTokenResponse(
                valid=False,
                message=str(e)
            )

        except Exception as e:
            logger.exception(f"Unexpected error during token validation: {e}")
            return cloudsecurity_pb2.ValidateTokenResponse(
                valid=False,
                message="Error: An unexpected error occurred."
            )

    # =========================================================================
    # RefreshToken RPC
    # =========================================================================

    def RefreshToken(self, request, context) -> cloudsecurity_pb2.RefreshTokenResponse:
        """
        Handle RefreshToken RPC request.

        Uses a valid refresh token to generate a new access token.

        Args:
            request: RefreshTokenRequest with refresh_token.
            context: gRPC context.

        Returns:
            RefreshTokenResponse with new access token if successful.
        """
        logger.info("RefreshToken request received")

        if not request.refresh_token:
            return cloudsecurity_pb2.RefreshTokenResponse(
                success=False,
                message="Error: Refresh token is required."
            )

        try:
            # Validate refresh token and get payload
            payload = validate_token(request.refresh_token, expected_type='refresh')

            # Get user from database to get current email
            user = self.db.get_user_by_username(payload.get('username'))
            if not user:
                logger.warning(f"RefreshToken failed: User not found")
                return cloudsecurity_pb2.RefreshTokenResponse(
                    success=False,
                    message="Error: User not found."
                )

            # Generate new access token
            new_access_token = refresh_access_token(
                refresh_token=request.refresh_token,
                email=user['email']
            )

            logger.info(f"Access token refreshed for user: {payload.get('username')}")
            return cloudsecurity_pb2.RefreshTokenResponse(
                success=True,
                message="Token refreshed successfully.",
                access_token=new_access_token
            )

        except TokenError as e:
            logger.warning(f"Token refresh failed: {str(e)}")
            return cloudsecurity_pb2.RefreshTokenResponse(
                success=False,
                message=str(e)
            )

        except Exception as e:
            logger.exception(f"Unexpected error during token refresh: {e}")
            return cloudsecurity_pb2.RefreshTokenResponse(
                success=False,
                message="Error: An unexpected error occurred."
            )

    # =========================================================================
    # Session Management RPCs
    # =========================================================================

    def Logout(self, request, context) -> cloudsecurity_pb2.LogoutResponse:
        """
        Handle Logout RPC request.

        Revokes the current session/token.
        """
        logger.info("Logout request received")

        if not request.access_token:
            return cloudsecurity_pb2.LogoutResponse(
                success=False,
                message="Error: Access token is required."
            )

        try:
            # Validate token to get token_id
            payload = validate_token(request.access_token, expected_type='access')
            token_id = payload.get('jti')

            if token_id:
                # Revoke the session
                if self.db.revoke_session(token_id):
                    logger.info(f"User '{payload.get('username')}' logged out successfully")
                    # Audit log: LOGOUT
                    self.db.log_event(
                        event_type='LOGOUT',
                        user_id=payload.get('user_id'),
                        username=payload.get('username'),
                        details=f"Session {token_id[:8]}... revoked",
                        success=True
                    )
                    return cloudsecurity_pb2.LogoutResponse(
                        success=True,
                        message="Logged out successfully."
                    )

            return cloudsecurity_pb2.LogoutResponse(
                success=False,
                message="Error: Session not found."
            )

        except TokenError as e:
            return cloudsecurity_pb2.LogoutResponse(
                success=False,
                message=str(e)
            )
        except Exception as e:
            logger.exception(f"Logout error: {e}")
            return cloudsecurity_pb2.LogoutResponse(
                success=False,
                message="Error: An unexpected error occurred."
            )

    def GetSessions(self, request, context) -> cloudsecurity_pb2.GetSessionsResponse:
        """
        Handle GetSessions RPC request.

        Returns all active sessions for the authenticated user.
        """
        logger.info("GetSessions request received")

        if not request.access_token:
            return cloudsecurity_pb2.GetSessionsResponse(
                success=False,
                message="Error: Access token is required."
            )

        try:
            # Validate token
            payload = validate_token(request.access_token, expected_type='access')
            user_id = payload.get('user_id')
            current_token_id = payload.get('jti')

            # Get active sessions
            sessions = self.db.get_active_sessions(user_id)

            # Convert to proto message format
            session_list = []
            for s in sessions:
                session_info = cloudsecurity_pb2.SessionInfo(
                    session_id=s['id'],
                    token_id=s['token_id'],
                    device_info=s.get('device_info') or 'Unknown',
                    ip_address=s.get('ip_address') or 'Unknown',
                    created_at=str(s['created_at']),
                    last_activity=str(s['last_activity']),
                    is_current=(s['token_id'] == current_token_id)
                )
                session_list.append(session_info)

            logger.info(f"Retrieved {len(session_list)} sessions for user {payload.get('username')}")
            return cloudsecurity_pb2.GetSessionsResponse(
                success=True,
                message=f"Found {len(session_list)} active session(s).",
                sessions=session_list
            )

        except TokenError as e:
            return cloudsecurity_pb2.GetSessionsResponse(
                success=False,
                message=str(e)
            )
        except Exception as e:
            logger.exception(f"GetSessions error: {e}")
            return cloudsecurity_pb2.GetSessionsResponse(
                success=False,
                message="Error: An unexpected error occurred."
            )

    def RevokeSession(self, request, context) -> cloudsecurity_pb2.RevokeSessionResponse:
        """
        Handle RevokeSession RPC request.

        Revokes a specific session by token_id.
        """
        logger.info(f"RevokeSession request for token_id: {request.token_id[:8] if request.token_id else 'None'}...")

        if not request.access_token:
            return cloudsecurity_pb2.RevokeSessionResponse(
                success=False,
                message="Error: Access token is required."
            )

        if not request.token_id:
            return cloudsecurity_pb2.RevokeSessionResponse(
                success=False,
                message="Error: Token ID is required."
            )

        try:
            # Validate token
            payload = validate_token(request.access_token, expected_type='access')
            user_id = payload.get('user_id')

            # Verify session belongs to user
            session = self.db.get_session_by_token_id(request.token_id)
            if not session or session['user_id'] != user_id:
                return cloudsecurity_pb2.RevokeSessionResponse(
                    success=False,
                    message="Error: Session not found or not authorized."
                )

            # Revoke the session
            if self.db.revoke_session(request.token_id):
                logger.info(f"Session revoked: {request.token_id[:8]}...")
                return cloudsecurity_pb2.RevokeSessionResponse(
                    success=True,
                    message="Session revoked successfully."
                )

            return cloudsecurity_pb2.RevokeSessionResponse(
                success=False,
                message="Error: Failed to revoke session."
            )

        except TokenError as e:
            return cloudsecurity_pb2.RevokeSessionResponse(
                success=False,
                message=str(e)
            )
        except Exception as e:
            logger.exception(f"RevokeSession error: {e}")
            return cloudsecurity_pb2.RevokeSessionResponse(
                success=False,
                message="Error: An unexpected error occurred."
            )

    def LogoutAll(self, request, context) -> cloudsecurity_pb2.LogoutAllResponse:
        """
        Handle LogoutAll RPC request.

        Revokes all sessions for the authenticated user.
        """
        logger.info("LogoutAll request received")

        if not request.access_token:
            return cloudsecurity_pb2.LogoutAllResponse(
                success=False,
                message="Error: Access token is required."
            )

        try:
            # Validate token
            payload = validate_token(request.access_token, expected_type='access')
            user_id = payload.get('user_id')
            current_token_id = payload.get('jti') if request.keep_current else None

            # Revoke all sessions
            count = self.db.revoke_all_sessions(user_id, except_token_id=current_token_id)

            msg = f"Logged out from {count} device(s)."
            if request.keep_current:
                msg += " Current session kept active."

            logger.info(f"User '{payload.get('username')}' logged out from {count} devices")

            # Audit log: LOGOUT_ALL
            self.db.log_event(
                event_type='LOGOUT_ALL',
                user_id=payload.get('user_id'),
                username=payload.get('username'),
                details=f"Revoked {count} session(s). Keep current: {request.keep_current}",
                success=True
            )

            return cloudsecurity_pb2.LogoutAllResponse(
                success=True,
                message=msg,
                sessions_revoked=count
            )

        except TokenError as e:
            return cloudsecurity_pb2.LogoutAllResponse(
                success=False,
                message=str(e)
            )
        except Exception as e:
            logger.exception(f"LogoutAll error: {e}")
            return cloudsecurity_pb2.LogoutAllResponse(
                success=False,
                message="Error: An unexpected error occurred."
            )

    # =========================================================================
    # GetAuditLogs RPC
    # =========================================================================

    def GetAuditLogs(self, request, context) -> cloudsecurity_pb2.GetAuditLogsResponse:
        """
        Get audit logs for the current user.

        Args:
            request: GetAuditLogsRequest with access_token, limit, event_type.
            context: gRPC context.

        Returns:
            GetAuditLogsResponse with list of audit log entries.
        """
        logger.info("GetAuditLogs request received")

        if not request.access_token:
            return cloudsecurity_pb2.GetAuditLogsResponse(
                success=False,
                message="Error: Access token is required."
            )

        try:
            # Validate token
            payload = validate_token(request.access_token, expected_type='access')
            user_id = payload.get('user_id')

            # Get limit (default 50, max 100)
            limit = request.limit if request.limit > 0 else 50
            limit = min(limit, 100)

            # Get event type filter (optional)
            event_type = request.event_type if request.event_type else None

            # Fetch logs from database
            logs = self.db.get_user_logs(
                user_id=user_id,
                limit=limit,
                event_type=event_type
            )

            # Convert to proto messages
            log_entries = []
            for log in logs:
                entry = cloudsecurity_pb2.AuditLogEntry(
                    id=log['id'],
                    event_type=log['event_type'],
                    details=log.get('details') or '',
                    success=bool(log.get('success', True)),
                    created_at=str(log['created_at'])
                )
                log_entries.append(entry)

            logger.info(f"Retrieved {len(log_entries)} audit logs for user {payload.get('username')}")
            return cloudsecurity_pb2.GetAuditLogsResponse(
                success=True,
                message=f"Found {len(log_entries)} log(s).",
                logs=log_entries
            )

        except TokenError as e:
            return cloudsecurity_pb2.GetAuditLogsResponse(
                success=False,
                message=str(e)
            )
        except Exception as e:
            logger.exception(f"GetAuditLogs error: {e}")
            return cloudsecurity_pb2.GetAuditLogsResponse(
                success=False,
                message="Error: An unexpected error occurred."
            )


def run():
    """
    Start the gRPC server.

    Creates a thread pool executor and starts listening for
    incoming RPC requests on the configured port.
    """
    logger.info("=" * 60)
    logger.info("Cloud Security gRPC Server Starting")
    logger.info("=" * 60)

    # Create gRPC server with thread pool
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=GRPC_MAX_WORKERS))
    logger.debug(f"Created thread pool with {GRPC_MAX_WORKERS} workers")

    # Register the UserService implementation
    cloudsecurity_pb2_grpc.add_UserServiceServicer_to_server(
        UserServiceSkeleton(),
        server
    )
    logger.debug("Registered UserService servicer")

    # Bind to port (insecure for now - TLS added in Phase 9)
    server_address = f'[::]:{GRPC_SERVER_PORT}'
    server.add_insecure_port(server_address)

    # Start server
    server.start()
    logger.info(f"Server started on port {GRPC_SERVER_PORT}")
    logger.info("Server is running. Press Ctrl+C to stop.")
    logger.info("=" * 60)

    # Wait for termination
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Shutdown signal received...")
        server.stop(grace=5)
        logger.info("Server stopped gracefully.")


if __name__ == '__main__':
    run()