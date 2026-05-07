#!/usr/bin/env python3
"""
Check if server and database are working
"""
import os
import sys
from models import Database

print("=" * 60)
print("TITAN-NET SERVER CHECK")
print("=" * 60)

# 1. Check if database file exists
db_file = "titan_net.db"
if os.path.exists(db_file):
    print(f"[OK] Database file exists: {db_file}")
    print(f"     Size: {os.path.getsize(db_file)} bytes")
else:
    print(f"[ERROR] Database file missing: {db_file}")
    print("        Creating new database...")

# 2. Test database connection
try:
    db = Database()
    print("[OK] Database connection successful")
except Exception as e:
    print(f"[ERROR] Database connection failed: {e}")
    sys.exit(1)

# 3. Test database operations
try:
    # Count users
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM users")
    count = cursor.fetchone()['count']
    conn.close()
    print(f"[OK] Database has {count} users")
except Exception as e:
    print(f"[ERROR] Database query failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 4. Test user creation
try:
    import random
    test_username = f"test{random.randint(10000, 99999)}"
    print(f"[TEST] Creating test user: {test_username}")
    result = db.create_user(test_username, "testpass123", "Test User")
    if result['success']:
        print(f"[OK] Test user created successfully")
        print(f"     User ID: {result['user_id']}")
        print(f"     Titan Number: {result['titan_number']}")
    else:
        print(f"[ERROR] Failed to create test user: {result.get('error')}")
except Exception as e:
    print(f"[ERROR] User creation test failed: {e}")
    import traceback
    traceback.print_exc()

print("=" * 60)
print("CHECK COMPLETE")
print("=" * 60)
