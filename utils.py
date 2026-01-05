"""
utils.py - Utility functions for Cloud Security gRPC Simulator

This module provides:
- Password hashing using bcrypt
- OTP generation and email sending via Gmail SMTP
- Credential migration script (when run directly)
"""

import bcrypt
import random
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from params import SMTP_EMAIL, SMTP_APP_PASSWORD, OTP_EXPIRY_MINUTES

# Set up logger for this module
logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Args:
        password: The plaintext password to hash.

    Returns:
        The bcrypt hashed password as a UTF-8 string.
    """
    return bcrypt.hashpw(password.encode('utf-8'),
                         bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.

    Args:
        plain_password: The plaintext password to verify.
        hashed_password: The bcrypt hash to check against.

    Returns:
        True if password matches, False otherwise.
    """
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def generate_otp() -> str:
    """
    Generate a random 6-digit OTP code.

    Returns:
        A 6-digit string (e.g., "847293").
    """
    return str(random.randint(100000, 999999))


def send_otp(to_email: str, otp_code: str = None) -> str:
    """
    Send an OTP to the specified email address.

    Uses Gmail SMTP with TLS encryption to send the OTP email.
    Credentials are loaded from environment variables via params.py.

    Args:
        to_email: The recipient's email address.
        otp_code: The OTP code to send. If None, generates a new one.

    Returns:
        Success message string if email sent successfully.
        Error message string if sending failed.
    """
    otp = otp_code if otp_code else generate_otp()

    # Email content
    subject = "Your OTP Code for the Cloud Security Simulator"
    body = f"Your OTP code is: {otp}\n\nThis code will expire in {OTP_EXPIRY_MINUTES} minutes."

    # Create the email message
    msg = MIMEMultipart()
    msg['From'] = SMTP_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Connect and send email via Gmail SMTP
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            logger.debug("Starting TLS session on smtp.gmail.com:587")
            server.starttls()
            logger.info("TLS session started successfully")

            logger.debug(f"Logging in to SMTP server as {SMTP_EMAIL}")
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            logger.info("SMTP login successful")

            logger.debug(f"Sending OTP to {to_email}")
            server.send_message(msg)
            logger.info(f"OTP sent to {to_email} successfully")

            return f"OTP sent to your email: {to_email} successfully!"

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP Authentication failed: {e}")
        return "Error: Email authentication failed. Please contact support."

    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"Recipient refused: {e}")
        return f"Error: Could not send email to {to_email}. Invalid address."

    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        return "Error: Failed to send OTP email. Please try again later."

    except Exception as e:
        logger.exception(f"Unexpected error sending email: {e}")
        return "Error: An unexpected error occurred. Please try again later."


# =============================================================================
# Migration Script - Run directly to hash passwords from 'ids' file
# =============================================================================
if __name__ == '__main__':
    """
    Credential Migration Script

    Reads from 'ids' file (format: username,email,plaintext_password)
    Writes to 'credentials' file (format: username,email,hashed_password)

    Usage: python utils.py
    """
    print("=" * 60)
    print("Credential Migration Script")
    print("=" * 60)

    ids_file = 'ids'
    credentials_file = 'credentials'

    try:
        users = []
        with open(ids_file, 'r') as file:
            for line_num, line in enumerate(file, 1):
                line = line.strip()
                if not line:
                    continue

                parts = line.split(',')

                # Support both old format (username,password)
                # and new format (username,email,password)
                if len(parts) == 2:
                    username, password = parts
                    email = f"{username}@example.com"  # Placeholder email
                    print(f"  [WARN] Line {line_num}: No email for '{username}', using placeholder")
                elif len(parts) == 3:
                    username, email, password = parts
                else:
                    print(f"  [SKIP] Line {line_num}: Invalid format - {line}")
                    continue

                users.append((username, email, password))

        print(f"\nFound {len(users)} users to migrate.")

        with open(credentials_file, 'w') as file:
            for username, email, password in users:
                hashed = hash_password(password)
                file.write(f'{username},{email},{hashed}\n')
                print(f"  [OK] Migrated: {username} ({email})")

        print(f"\nMigration complete! Credentials written to '{credentials_file}'")
        print("=" * 60)

    except FileNotFoundError:
        print(f"[ERROR] File '{ids_file}' not found.")
        print(f"Create '{ids_file}' with format: username,email,plaintext_password")
    except Exception as e:
        print(f"[ERROR] Migration failed: {e}")