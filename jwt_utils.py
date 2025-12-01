"""
jwt_utils.py - JWT Token Utilities for Cloud Security gRPC Simulator

This module provides functions for generating and validating JWT tokens.
Uses HS256 algorithm with secret key from environment configuration.

Token Types:
    - Access Token: Short-lived (15 min), used for API authentication
    - Refresh Token: Long-lived (7 days), used to get new access tokens
"""

import jwt
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

from params import (
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_ACCESS_EXPIRY_MINUTES,
    JWT_REFRESH_EXPIRY_MINUTES
)

# Configure logging
logger = logging.getLogger(__name__)


class TokenError(Exception):
    """Custom exception for token-related errors."""
    pass


def generate_token_id() -> str:
    """Generate a unique token ID (jti claim) for session tracking."""
    return str(uuid.uuid4())


def generate_access_token(user_id: int, username: str, email: str,
                          token_id: str = None) -> Tuple[str, str, datetime]:
    """
    Generate a short-lived access token for API authentication.

    Args:
        user_id: Database user ID
        username: User's username
        email: User's email address
        token_id: Optional token ID (generated if not provided)

    Returns:
        Tuple of (JWT access token string, token_id, expiry datetime)
    """
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=JWT_ACCESS_EXPIRY_MINUTES)

    if token_id is None:
        token_id = generate_token_id()

    payload = {
        'type': 'access',
        'jti': token_id,  # JWT ID for session tracking
        'user_id': user_id,
        'username': username,
        'email': email,
        'iat': now,  # Issued at
        'exp': expiry,  # Expiration
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.info(f"Generated access token for user: {username} (jti: {token_id[:8]}...)")

    return token, token_id, expiry


def generate_refresh_token(user_id: int, username: str, token_id: str = None) -> Tuple[str, str, datetime]:
    """
    Generate a long-lived refresh token for obtaining new access tokens.

    Args:
        user_id: Database user ID
        username: User's username
        token_id: Optional token ID (generated if not provided)

    Returns:
        Tuple of (JWT refresh token string, token_id, expiry datetime)
    """
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=JWT_REFRESH_EXPIRY_MINUTES)

    if token_id is None:
        token_id = generate_token_id()

    payload = {
        'type': 'refresh',
        'jti': token_id,
        'user_id': user_id,
        'username': username,
        'iat': now,
        'exp': expiry,
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.info(f"Generated refresh token for user: {username} (jti: {token_id[:8]}...)")

    return token, token_id, expiry


def generate_token_pair(user_id: int, username: str, email: str) -> Tuple[str, str, str, datetime]:
    """
    Generate both access and refresh tokens with shared token_id for session tracking.

    Args:
        user_id: Database user ID
        username: User's username
        email: User's email address

    Returns:
        Tuple of (access_token, refresh_token, token_id, expiry)
    """
    # Use same token_id for both tokens (session identifier)
    token_id = generate_token_id()

    access_token, _, _ = generate_access_token(user_id, username, email, token_id)
    refresh_token, _, expiry = generate_refresh_token(user_id, username, token_id)

    return access_token, refresh_token, token_id, expiry


def validate_token(token: str, expected_type: str = 'access') -> Dict[str, Any]:
    """
    Validate and decode a JWT token.
    
    Args:
        token: JWT token string
        expected_type: Expected token type ('access' or 'refresh')
        
    Returns:
        Decoded token payload as dictionary
        
    Raises:
        TokenError: If token is invalid, expired, or wrong type
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        # Verify token type
        if payload.get('type') != expected_type:
            raise TokenError(f"Invalid token type. Expected '{expected_type}' token.")
        
        logger.info(f"Token validated for user: {payload.get('username')}")
        return payload
        
    except jwt.ExpiredSignatureError:
        logger.warning("Token validation failed: Token has expired")
        raise TokenError("Token has expired. Please login again.")
        
    except jwt.InvalidTokenError as e:
        logger.warning(f"Token validation failed: {str(e)}")
        raise TokenError("Invalid token. Please login again.")


def refresh_access_token(refresh_token: str, email: str) -> str:
    """
    Generate a new access token using a valid refresh token.
    Uses the same token_id as the refresh token to maintain session.

    Args:
        refresh_token: Valid refresh token
        email: User's email (required for new access token)

    Returns:
        New access token

    Raises:
        TokenError: If refresh token is invalid or expired
    """
    # Validate the refresh token
    payload = validate_token(refresh_token, expected_type='refresh')

    # Generate new access token with SAME token_id (session continuity)
    new_access_token, _, _ = generate_access_token(
        user_id=payload['user_id'],
        username=payload['username'],
        email=email,
        token_id=payload.get('jti')  # Keep same session ID
    )

    logger.info(f"Refreshed access token for user: {payload['username']}")
    return new_access_token


def get_token_id(token: str) -> Optional[str]:
    """
    Extract token ID (jti claim) from a token.

    Args:
        token: JWT token string

    Returns:
        Token ID (jti) if present and valid, None otherwise
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get('jti')
    except jwt.InvalidTokenError:
        return None


def get_token_info(token: str) -> Optional[Dict[str, Any]]:
    """
    Get information about a token without raising exceptions.
    Useful for debugging and logging.

    Args:
        token: JWT token string

    Returns:
        Token payload if valid, None if invalid
    """
    try:
        # Decode without verification to see contents (for debugging)
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            'type': payload.get('type'),
            'jti': payload.get('jti'),
            'username': payload.get('username'),
            'user_id': payload.get('user_id'),
            'email': payload.get('email'),
            'issued_at': payload.get('iat'),
            'expires_at': payload.get('exp'),
            'is_valid': True
        }
    except jwt.ExpiredSignatureError:
        return {'is_valid': False, 'error': 'Token expired'}
    except jwt.InvalidTokenError:
        return {'is_valid': False, 'error': 'Invalid token'}

