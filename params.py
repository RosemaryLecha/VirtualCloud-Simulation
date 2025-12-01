"""
params.py - Configuration parameters for Cloud Security gRPC Simulator

All configuration is loaded from environment variables (.env file).
This ensures secrets are never hardcoded in the codebase.

Usage:
    1. Copy .env.example to .env
    2. Fill in your actual values in .env
    3. Import settings from this module: from params import SMTP_EMAIL, ...
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# =============================================================================
# Load environment variables from .env file
# =============================================================================
# Find the .env file in the same directory as this script
ENV_PATH = Path(__file__).parent / '.env'
load_dotenv(ENV_PATH)

# =============================================================================
# SMTP Email Configuration (Gmail)
# =============================================================================
SMTP_EMAIL = os.getenv('SMTP_EMAIL', 'your-email@gmail.com')
SMTP_APP_PASSWORD = os.getenv('SMTP_APP_PASSWORD', '')

# Backward compatibility aliases
from_email = SMTP_EMAIL
app_password = SMTP_APP_PASSWORD

# =============================================================================
# Server Configuration
# =============================================================================
GRPC_SERVER_HOST = os.getenv('GRPC_SERVER_HOST', '[::]')
GRPC_SERVER_PORT = int(os.getenv('GRPC_SERVER_PORT', '51234'))
GRPC_MAX_WORKERS = int(os.getenv('GRPC_MAX_WORKERS', '10'))

# =============================================================================
# Security Configuration
# =============================================================================
OTP_EXPIRY_MINUTES = int(os.getenv('OTP_EXPIRY_MINUTES', '10'))

# JWT Configuration
JWT_SECRET = os.getenv('JWT_SECRET', 'change-this-in-production')
JWT_ALGORITHM = 'HS256'
JWT_ACCESS_EXPIRY_MINUTES = int(os.getenv('JWT_ACCESS_EXPIRY_MINUTES', '15'))
JWT_REFRESH_EXPIRY_MINUTES = int(os.getenv('JWT_REFRESH_EXPIRY_MINUTES', '10080'))  # 7 days

# Rate Limiting Configuration
MAX_LOGIN_ATTEMPTS = int(os.getenv('MAX_LOGIN_ATTEMPTS', '5'))  # Max failed attempts before lockout
LOCKOUT_DURATION_MINUTES = int(os.getenv('LOCKOUT_DURATION_MINUTES', '15'))  # Account lockout duration

# =============================================================================
# Database Configuration
# =============================================================================
DATABASE_PATH = os.getenv('DATABASE_PATH', 'cloudsecurity.db')

# =============================================================================
# Logging Configuration
# =============================================================================
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')


# =============================================================================
# Validation - Warn if critical settings are missing
# =============================================================================
def validate_config():
    """Validate that critical configuration is set."""
    warnings = []

    if not SMTP_EMAIL or SMTP_EMAIL == 'your-email@gmail.com':
        warnings.append("SMTP_EMAIL is not configured")

    if not SMTP_APP_PASSWORD:
        warnings.append("SMTP_APP_PASSWORD is not configured")

    if JWT_SECRET == 'change-this-in-production':
        warnings.append("JWT_SECRET should be changed for production")

    return warnings


# Run validation on import (optional - can be called manually)
_config_warnings = validate_config()
if _config_warnings:
    import sys
    for warning in _config_warnings:
        print(f"[CONFIG WARNING] {warning}", file=sys.stderr)