"""
REST API Gateway for Cloud Security Authentication & Storage System.

This module provides HTTP REST endpoints that wrap around the existing
gRPC authentication logic and storage system, making it accessible from web browsers.

Run with: python rest_api.py
API Docs: http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import uvicorn
import os
import sys
import uuid
import hashlib
import io

# Add storage system to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'cloudstoragesimulation1744 (3)'))

# Import existing modules
from database import get_database
from jwt_utils import generate_token_pair, validate_token, TokenError
from utils import send_otp, generate_otp, hash_password, verify_password
from params import (
    MAX_LOGIN_ATTEMPTS, LOCKOUT_DURATION_MINUTES
)
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# FastAPI App Setup
# =============================================================================
app = FastAPI(
    title="Cloud Security REST API",
    description="REST API Gateway for Authentication System",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware - Allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and dashboard
from fastapi.staticfiles import StaticFiles
from pathlib import Path

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the dashboard."""
    dashboard_path = static_dir / "dashboard.html"
    if dashboard_path.exists():
        try:
            return HTMLResponse(content=dashboard_path.read_text(encoding='utf-8'), status_code=200)
        except Exception as e:
            return HTMLResponse(f"<h1>Error loading dashboard</h1><p>{str(e)}</p>", status_code=500)
    return HTMLResponse("<h1>Cloud Security API</h1><p>Visit <a href='/docs'>/docs</a> for API documentation.</p>")

# =============================================================================
# Pydantic Models (Request/Response Schemas)
# =============================================================================

# Auth Request Models
class SignupRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class VerifyOTPRequest(BaseModel):
    username: str
    otp_code: str
    otp_type: str  # signup, login, reset

class ResendOTPRequest(BaseModel):
    username: str
    otp_type: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class ValidateTokenRequest(BaseModel):
    access_token: str

class LogoutAllRequest(BaseModel):
    keep_current: bool = False

class RevokeSessionRequest(BaseModel):
    token_id: str

# Response Models
class MessageResponse(BaseModel):
    success: bool
    message: str

class TokenResponse(BaseModel):
    success: bool
    message: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None

class UserInfoResponse(BaseModel):
    success: bool
    message: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    email: Optional[str] = None

class SessionInfo(BaseModel):
    token_id: str
    device_info: str
    created_at: str
    expires_at: str
    is_current: bool = False

class SessionsResponse(BaseModel):
    success: bool
    message: str
    sessions: List[SessionInfo] = []

class AuditLogInfo(BaseModel):
    id: int
    event_type: str
    details: str
    success: bool
    created_at: str

class AuditLogsResponse(BaseModel):
    success: bool
    message: str
    logs: List[AuditLogInfo] = []

# Storage Models
class StorageFileInfo(BaseModel):
    file_id: str
    file_name: str
    file_size: int
    checksum: str
    status: str
    created_at: str
    nodes: List[str] = []

class StorageFilesResponse(BaseModel):
    success: bool
    message: str
    files: List[StorageFileInfo] = []
    total_count: int = 0

class QuotaInfo(BaseModel):
    total_quota: int
    used_storage: int
    available: int
    usage_percent: float

class QuotaResponse(BaseModel):
    success: bool
    message: str
    quota: Optional[QuotaInfo] = None

class UploadResponse(BaseModel):
    success: bool
    message: str
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None

# =============================================================================
# Helper Functions
# =============================================================================
def get_db():
    """Get database instance."""
    return get_database()

def get_token_from_header(authorization: str = Header(None)) -> str:
    """Extract token from Authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format. Use: Bearer <token>")
    return authorization[7:]

def get_current_user(authorization: str = Header(None)) -> dict:
    """Get current user from JWT token."""
    token = get_token_from_header(authorization)
    try:
        payload = validate_token(token, expected_type='access')
        return {
            'user_id': payload.get('user_id'),
            'username': payload.get('username'),
            'email': payload.get('email')
        }
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))

# =============================================================================
# AUTH ENDPOINTS
# =============================================================================

@app.post("/api/auth/signup", response_model=MessageResponse)
async def signup(request: SignupRequest):
    """Create a new user account. Sends OTP to email for verification."""
    db = get_db()

    # Check if user already exists
    existing = db.get_user_by_username(request.username)
    if existing:
        db.log_event("SIGNUP_FAILED", None, request.username, "Username already exists")
        raise HTTPException(status_code=400, detail="Username already exists")

    existing_email = db.get_user_by_email(request.email)
    if existing_email:
        db.log_event("SIGNUP_FAILED", None, request.username, "Email already registered")
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user (unverified)
    password_hash = hash_password(request.password)
    user_id = db.create_user(request.username, request.email, password_hash)

    # Generate and store OTP
    otp_code = generate_otp()
    db.create_otp(user_id, otp_code, "signup")

    # Send OTP email
    try:
        send_otp(request.email, otp_code)
        db.log_event("SIGNUP", user_id, request.username, f"Account created. OTP sent to {request.email}")
        return MessageResponse(success=True, message=f"Account created! OTP sent to {request.email}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        db.log_event("SIGNUP", user_id, request.username, "Account created but email failed", success=False)
        return MessageResponse(success=True, message="Account created! OTP email failed - use resend.")

@app.post("/api/auth/login", response_model=MessageResponse)
async def login(request: LoginRequest):
    """Login with username/password. Sends OTP for 2FA."""
    db = get_db()

    # Get user first
    user = db.get_user_by_username(request.username)
    if not user:
        db.record_login_attempt(request.username, None, None, False, "User not found")
        db.log_event("LOGIN_FAILED", None, request.username, "User not found", success=False)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Check if account is locked
    is_locked, locked_until = db.is_account_locked(user['id'])
    if is_locked:
        remaining_minutes = int((locked_until - datetime.now()).total_seconds() / 60) + 1
        db.log_event("ACCOUNT_LOCKED", user['id'], request.username, f"Login blocked. Locked for {remaining_minutes} min")
        raise HTTPException(status_code=429, detail=f"Account locked. Try again in {remaining_minutes} minute(s).")

    # Check if verified
    if not user['is_verified']:
        raise HTTPException(status_code=403, detail="Email not verified. Please verify your email first.")

    # Verify password
    if not verify_password(request.password, user['password_hash']):
        # Increment failed login attempts
        failed_count = db.increment_failed_login(user['id'])
        attempts_remaining = MAX_LOGIN_ATTEMPTS - failed_count

        db.record_login_attempt(request.username, user['id'], None, False, "Invalid password")
        db.log_event("LOGIN_FAILED", user['id'], request.username, f"Invalid password. Attempt {failed_count}/{MAX_LOGIN_ATTEMPTS}", success=False)

        if attempts_remaining <= 0:
            raise HTTPException(status_code=429, detail=f"Account locked for {LOCKOUT_DURATION_MINUTES} minutes.")
        elif attempts_remaining <= 2:
            raise HTTPException(status_code=401, detail=f"Invalid password. {attempts_remaining} attempt(s) remaining.")
        else:
            raise HTTPException(status_code=401, detail="Invalid username or password")

    # Generate OTP for 2FA
    otp_code = generate_otp()
    db.create_otp(user['id'], otp_code, "login")

    # Send OTP
    try:
        send_otp(user['email'], otp_code)
        db.log_event("LOGIN_OTP_SENT", user['id'], request.username, "Password verified, OTP sent for 2FA")
        return MessageResponse(success=True, message=f"OTP sent to {user['email']}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send OTP email")

@app.post("/api/auth/verify", response_model=TokenResponse)
async def verify_otp_endpoint(request: VerifyOTPRequest):
    """Verify OTP code. Returns JWT tokens on login verification."""
    db = get_db()

    user = db.get_user_by_username(request.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify OTP (this also marks it as used internally)
    is_valid = db.verify_otp(user['id'], request.otp_code, request.otp_type)
    if not is_valid:
        db.log_event("OTP_FAILED", user['id'], request.username, f"Invalid/expired OTP for {request.otp_type}", success=False)
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    if request.otp_type == "signup":
        # Verify email
        db.verify_user(user['id'])
        db.log_event("EMAIL_VERIFIED", user['id'], request.username, "Email verified successfully")
        return TokenResponse(success=True, message="Email verified successfully! You can now login.")

    elif request.otp_type == "login":
        # Generate JWT tokens and create session
        access_token, refresh_token, token_id, expires_at = generate_token_pair(
            user['id'], user['username'], user['email']
        )

        # Create session (user_id, token_id, expires_at, device_info)
        db.create_session(user['id'], token_id, expires_at, "REST API Client")

        # Reset failed login attempts
        db.reset_failed_login(user['id'])
        db.record_login_attempt(request.username, user['id'], None, True)

        db.log_event("LOGIN_SUCCESS", user['id'], request.username, f"Login successful. Session: {token_id[:8]}...")

        return TokenResponse(
            success=True,
            message="Login successful!",
            access_token=access_token,
            refresh_token=refresh_token
        )

    elif request.otp_type == "reset":
        return TokenResponse(success=True, message="OTP verified. You can now reset your password.")

    return TokenResponse(success=True, message="OTP verified")

@app.post("/api/auth/resend", response_model=MessageResponse)
async def resend_otp(request: ResendOTPRequest):
    """Resend OTP code."""
    db = get_db()

    user = db.get_user_by_username(request.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Generate new OTP
    otp_code = generate_otp()
    db.create_otp(user['id'], otp_code, request.otp_type)

    try:
        send_otp(user['email'], otp_code)
        return MessageResponse(success=True, message=f"New OTP sent to {user['email']}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send OTP email")

@app.post("/api/auth/forgot", response_model=MessageResponse)
async def forgot_password(request: ForgotPasswordRequest):
    """Request password reset OTP."""
    db = get_db()

    user = db.get_user_by_email(request.email)
    if not user:
        # Don't reveal if email exists
        return MessageResponse(success=True, message="If the email exists, an OTP has been sent.")

    otp_code = generate_otp()
    db.create_otp(user['id'], otp_code, "reset")

    try:
        send_otp(request.email, otp_code)
        return MessageResponse(success=True, message="Password reset OTP sent to your email.")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send OTP email")

@app.post("/api/auth/reset", response_model=MessageResponse)
async def reset_password(request: ResetPasswordRequest):
    """Reset password with OTP verification."""
    db = get_db()

    user = db.get_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify OTP
    otp_record = db.get_valid_otp(user['id'], request.otp_code, "reset")
    if not otp_record:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    # Mark OTP as used
    db.mark_otp_used(otp_record['id'])

    # Update password
    new_hash = hash_password(request.new_password)
    db.update_password(user['id'], new_hash)

    db.log_event("PASSWORD_RESET", user['id'], user['username'], "Password reset successfully")

    return MessageResponse(success=True, message="Password reset successfully!")

# =============================================================================
# TOKEN ENDPOINTS
# =============================================================================

@app.post("/api/auth/validate", response_model=UserInfoResponse)
async def validate_access_token(request: ValidateTokenRequest):
    """Validate an access token and return user info."""
    payload = validate_token(request.access_token, "access")

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return UserInfoResponse(
        success=True,
        message="Token is valid",
        user_id=payload.get('user_id'),
        username=payload.get('username'),
        email=payload.get('email')
    )

@app.post("/api/auth/refresh", response_model=TokenResponse)
async def refresh_access_token(request: RefreshTokenRequest):
    """Get a new access token using a refresh token."""
    db = get_db()

    payload = validate_token(request.refresh_token, "refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user_id = payload.get('user_id')
    username = payload.get('username')
    email = payload.get('email')

    # Generate new token pair
    access_token, refresh_token, token_id, expires_at = generate_token_pair(user_id, username, email)

    # Create new session (user_id, token_id, expires_at, device_info)
    db.create_session(user_id, token_id, expires_at, "REST API Client (refreshed)")

    return TokenResponse(
        success=True,
        message="Token refreshed successfully",
        access_token=access_token,
        refresh_token=refresh_token
    )

@app.post("/api/auth/logout", response_model=MessageResponse)
async def logout(authorization: str = Header(None)):
    """Logout (revoke current session)."""
    token = get_token_from_header(authorization)
    db = get_db()

    payload = validate_token(token, "access")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    token_id = payload.get('jti')
    user_id = payload.get('user_id')
    username = payload.get('username')

    if token_id:
        db.revoke_session(token_id)
        db.log_event("LOGOUT", user_id, username, f"Session {token_id[:8]}... revoked")

    return MessageResponse(success=True, message="Logged out successfully")

# =============================================================================
# SESSION ENDPOINTS
# =============================================================================

@app.get("/api/auth/sessions", response_model=SessionsResponse)
async def get_sessions(authorization: str = Header(None)):
    """Get all active sessions for the current user."""
    token = get_token_from_header(authorization)
    db = get_db()

    payload = validate_token(token, "access")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get('user_id')
    current_token_id = payload.get('jti')

    sessions = db.get_user_sessions(user_id)

    session_list = []
    for s in sessions:
        session_list.append(SessionInfo(
            token_id=s['token_id'],
            device_info=s['device_info'] or "Unknown",
            created_at=s['created_at'],
            expires_at=s['expires_at'],
            is_current=(s['token_id'] == current_token_id)
        ))

    return SessionsResponse(
        success=True,
        message=f"Found {len(session_list)} active session(s)",
        sessions=session_list
    )

@app.delete("/api/auth/sessions/{token_id}", response_model=MessageResponse)
async def revoke_session(token_id: str, authorization: str = Header(None)):
    """Revoke a specific session by token_id."""
    token = get_token_from_header(authorization)
    db = get_db()

    payload = validate_token(token, "access")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get('user_id')

    # Verify the session belongs to this user
    sessions = db.get_user_sessions(user_id)
    session_ids = [s['token_id'] for s in sessions]

    if token_id not in session_ids:
        raise HTTPException(status_code=404, detail="Session not found")

    db.revoke_session(token_id)
    db.log_event("LOGOUT", user_id, payload.get('username'), f"Session {token_id[:8]}... revoked")

    return MessageResponse(success=True, message="Session revoked successfully")

@app.post("/api/auth/logout-all", response_model=MessageResponse)
async def logout_all(request: LogoutAllRequest, authorization: str = Header(None)):
    """Logout from all devices."""
    token = get_token_from_header(authorization)
    db = get_db()

    payload = validate_token(token, "access")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get('user_id')
    username = payload.get('username')
    current_token_id = payload.get('jti')

    sessions = db.get_user_sessions(user_id)
    revoked_count = 0

    for session in sessions:
        if request.keep_current and session['token_id'] == current_token_id:
            continue
        db.revoke_session(session['token_id'])
        revoked_count += 1

    db.log_event("LOGOUT_ALL", user_id, username, f"Revoked {revoked_count} session(s)")

    return MessageResponse(success=True, message=f"Logged out from {revoked_count} device(s)")

# =============================================================================
# AUDIT LOGS ENDPOINT
# =============================================================================

@app.get("/api/auth/logs", response_model=AuditLogsResponse)
async def get_audit_logs(
    limit: int = 50,
    event_type: Optional[str] = None,
    authorization: str = Header(None)
):
    """Get audit logs for the current user."""
    token = get_token_from_header(authorization)
    db = get_db()

    payload = validate_token(token, "access")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get('user_id')

    # Limit to max 100
    limit = min(limit, 100)

    logs = db.get_user_logs(user_id, limit=limit, event_type=event_type if event_type else None)

    log_list = []
    for log in logs:
        log_list.append(AuditLogInfo(
            id=log['id'],
            event_type=log['event_type'],
            details=log['details'] or "",
            success=bool(log['success']),
            created_at=log['created_at']
        ))

    return AuditLogsResponse(
        success=True,
        message=f"Found {len(log_list)} log(s)",
        logs=log_list
    )

# =============================================================================
# STORAGE ENDPOINTS
# =============================================================================

@app.get("/api/storage/quota", response_model=QuotaResponse, tags=["Storage"])
async def get_quota(user: dict = Depends(get_current_user)):
    """Get user's storage quota information."""
    db = get_db()
    user_id = user['user_id']

    # get_user_quota creates default quota if not exists
    quota = db.get_user_quota(user_id)

    total = quota['quota_bytes']
    used = quota['used_bytes']
    available = quota['available_bytes']
    usage_percent = (used / total * 100) if total > 0 else 0

    return QuotaResponse(
        success=True,
        message="Quota retrieved successfully",
        quota=QuotaInfo(
            total_quota=total,
            used_storage=used,
            available=available,
            usage_percent=round(usage_percent, 2)
        )
    )

@app.get("/api/storage/files", response_model=StorageFilesResponse, tags=["Storage"])
async def list_files(user: dict = Depends(get_current_user)):
    """List all files owned by the current user."""
    db = get_db()
    user_id = user['user_id']

    files = db.list_storage_files(owner_id=user_id)

    file_list = []
    for f in files:
        nodes_dict = db.get_file_nodes(f['file_id'])
        # get_file_nodes returns {'primary_nodes': [...], 'replica_nodes': [...]}
        all_nodes = nodes_dict.get('primary_nodes', []) + nodes_dict.get('replica_nodes', [])
        file_list.append(StorageFileInfo(
            file_id=f['file_id'],
            file_name=f['file_name'],
            file_size=f['file_size'],
            checksum=f['checksum'] or "",
            status=f['status'],
            created_at=f['created_at'],
            nodes=all_nodes
        ))

    return StorageFilesResponse(
        success=True,
        message=f"Found {len(file_list)} file(s)",
        files=file_list,
        total_count=len(file_list)
    )

@app.post("/api/storage/upload", response_model=UploadResponse, tags=["Storage"])
async def upload_file(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user)
):
    """Upload a file to storage."""
    db = get_db()
    user_id = user['user_id']

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Check quota
    has_space, available = db.check_quota_available(user_id, file_size)
    if not has_space:
        raise HTTPException(
            status_code=413,
            detail=f"Insufficient storage quota. Available: {available} bytes, Required: {file_size} bytes"
        )

    # Generate file ID and checksum
    file_id = str(uuid.uuid4())
    checksum = hashlib.sha256(content).hexdigest()

    # Store file metadata in database
    db.create_storage_file(
        file_id=file_id,
        file_name=file.filename,
        file_size=file_size,
        checksum=checksum,
        owner_id=user_id
    )

    # Update quota usage
    db.update_user_used_storage(user_id, file_size)

    # Log the upload
    db.log_event(
        event_type='file_upload',
        user_id=user_id,
        username=user['username'],
        details=f"Uploaded file: {file.filename} ({file_size} bytes)",
        success=True
    )

    return UploadResponse(
        success=True,
        message="File uploaded successfully",
        file_id=file_id,
        file_name=file.filename,
        file_size=file_size
    )

@app.delete("/api/storage/files/{file_id}", response_model=MessageResponse, tags=["Storage"])
async def delete_file(file_id: str, user: dict = Depends(get_current_user)):
    """Delete a file from storage."""
    db = get_db()
    user_id = user['user_id']

    # Get file info
    file_info = db.get_storage_file(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail="File not found")

    # Check ownership
    if file_info['owner_id'] != user_id:
        raise HTTPException(status_code=403, detail="You don't have permission to delete this file")

    # Delete file
    db.delete_storage_file(file_id)

    # Update quota (subtract file size)
    db.update_user_used_storage(user_id, -file_info['file_size'])

    # Log the deletion
    db.log_event(
        event_type='file_delete',
        user_id=user_id,
        username=user['username'],
        details=f"Deleted file: {file_info['file_name']}",
        success=True
    )

    return MessageResponse(
        success=True,
        message=f"File '{file_info['file_name']}' deleted successfully"
    )


@app.get("/api/storage/files/{file_id}/download", tags=["Storage"])
async def download_file(file_id: str, user: dict = Depends(get_current_user)):
    """Download a file from storage."""
    db = get_db()
    user_id = user['user_id']

    # Get file info
    file_info = db.get_storage_file(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail="File not found")

    # Check ownership
    if file_info['owner_id'] != user_id:
        raise HTTPException(status_code=403, detail="You don't have permission to download this file")

    # For now, return metadata since actual file content is in storage nodes
    # In production, this would stream from the storage nodes
    db.log_event(
        event_type='file_download',
        user_id=user_id,
        username=user['username'],
        details=f"Downloaded file: {file_info['file_name']}",
        success=True
    )

    # Return file info as JSON (actual streaming would require storage node integration)
    return {
        "success": True,
        "message": "File download initiated",
        "file": {
            "file_id": file_info['file_id'],
            "file_name": file_info['file_name'],
            "file_size": file_info['file_size'],
            "checksum": file_info['checksum'],
            "status": "Note: For full download, use gRPC StreamDownload with storage nodes"
        }
    }

# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "Cloud Security REST API"}


@app.get("/api/health/detailed")
async def detailed_health_check():
    """Detailed health check with component status."""
    db = get_db()

    # Check database
    db_status = "healthy"
    try:
        with db._get_connection() as conn:
            conn.cursor().execute("SELECT 1")
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "service": "Cloud Security REST API",
        "components": {
            "database": db_status,
            "auth_grpc": "check port 51234",
            "storage_controller": "check port 5000",
            "storage_grpc": "check port 50051"
        },
        "version": "1.0.0"
    }

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Cloud Security REST API Server")
    print("=" * 60)
    print("Starting server on http://localhost:8000")
    print("API Docs: http://localhost:8000/docs")
    print("ReDoc: http://localhost:8000/redoc")
    print("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")
