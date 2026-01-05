"""
migrate_to_db.py - Migration Script for Cloud Security gRPC Simulator

This script migrates existing credentials from the file-based system
to the SQLite database.

It reads from:
- 'credentials' file (format: username,email,hashed_password)
- 'ids' file (format: username,email,plaintext_password) - if credentials doesn't exist

And writes to:
- SQLite database (cloudsecurity.db)

Usage:
    python migrate_to_db.py

The script is idempotent - running it multiple times won't create duplicates.
"""

import sys
import logging
from pathlib import Path

# Set up logging before importing other modules
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

from database import Database
from utils import hash_password


def migrate_from_credentials_file(db: Database, filepath: str = 'credentials') -> int:
    """
    Migrate users from credentials file (already hashed passwords).
    
    Args:
        db: Database instance
        filepath: Path to credentials file
        
    Returns:
        Number of users migrated
    """
    if not Path(filepath).exists():
        logger.warning(f"Credentials file '{filepath}' not found")
        return 0
    
    migrated = 0
    skipped = 0
    
    with open(filepath, 'r') as file:
        for line_num, line in enumerate(file, 1):
            line = line.strip()
            if not line:
                continue
            
            parts = line.split(',')
            if len(parts) != 3:
                logger.warning(f"Line {line_num}: Invalid format, skipping")
                continue
            
            username, email, password_hash = parts
            
            # Check if user already exists
            if db.user_exists(username=username):
                logger.debug(f"User '{username}' already exists, skipping")
                skipped += 1
                continue
            
            if db.user_exists(email=email):
                logger.debug(f"Email '{email}' already exists, skipping")
                skipped += 1
                continue
            
            # Create user (already verified since they were in old system)
            user_id = db.create_user(username, email, password_hash, is_verified=True)
            if user_id:
                logger.info(f"Migrated user: {username} ({email})")
                migrated += 1
            else:
                logger.error(f"Failed to migrate user: {username}")
    
    if skipped > 0:
        logger.info(f"Skipped {skipped} existing users")
    
    return migrated


def migrate_from_ids_file(db: Database, filepath: str = 'ids') -> int:
    """
    Migrate users from ids file (plaintext passwords - will be hashed).
    
    Args:
        db: Database instance
        filepath: Path to ids file
        
    Returns:
        Number of users migrated
    """
    if not Path(filepath).exists():
        logger.warning(f"IDs file '{filepath}' not found")
        return 0
    
    migrated = 0
    skipped = 0
    
    with open(filepath, 'r') as file:
        for line_num, line in enumerate(file, 1):
            line = line.strip()
            if not line:
                continue
            
            parts = line.split(',')
            
            # Support both formats
            if len(parts) == 2:
                username, password = parts
                email = f"{username}@example.com"
                logger.warning(f"Line {line_num}: No email for '{username}', using placeholder")
            elif len(parts) == 3:
                username, email, password = parts
            else:
                logger.warning(f"Line {line_num}: Invalid format, skipping")
                continue
            
            # Check if user already exists
            if db.user_exists(username=username):
                logger.debug(f"User '{username}' already exists, skipping")
                skipped += 1
                continue
            
            if db.user_exists(email=email):
                logger.debug(f"Email '{email}' already exists, skipping")
                skipped += 1
                continue
            
            # Hash password and create user
            password_hash = hash_password(password)
            user_id = db.create_user(username, email, password_hash, is_verified=True)
            if user_id:
                logger.info(f"Migrated user: {username} ({email})")
                migrated += 1
            else:
                logger.error(f"Failed to migrate user: {username}")
    
    if skipped > 0:
        logger.info(f"Skipped {skipped} existing users")
    
    return migrated


def main():
    """Main migration function."""
    print("=" * 60)
    print("Database Migration Script")
    print("Cloud Security gRPC Simulator")
    print("=" * 60)
    print()
    
    # Initialize database (creates tables if they don't exist)
    logger.info("Initializing database...")
    db = Database()
    
    total_migrated = 0
    
    # Try credentials file first (already hashed)
    if Path('credentials').exists():
        logger.info("Found 'credentials' file, migrating...")
        count = migrate_from_credentials_file(db)
        total_migrated += count
        logger.info(f"Migrated {count} users from credentials file")
    
    # Also try ids file (will hash passwords)
    if Path('ids').exists():
        logger.info("Found 'ids' file, migrating...")
        count = migrate_from_ids_file(db)
        total_migrated += count
        logger.info(f"Migrated {count} users from ids file")
    
    print()
    print("=" * 60)
    print(f"Migration complete! Total users migrated: {total_migrated}")
    print()
    
    # Show current users in database
    users = db.get_all_users()
    print(f"Current users in database ({len(users)}):")
    print("-" * 60)
    for user in users:
        status = "✓ verified" if user['is_verified'] else "○ unverified"
        print(f"  [{user['id']}] {user['username']} - {user['email']} ({status})")
    print("=" * 60)


if __name__ == '__main__':
    main()

