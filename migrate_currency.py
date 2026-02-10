"""
Migration script to add currency tracking to orders.
Run this once against an existing database.
"""
import os
import sqlite3

db_path = os.getenv('DATABASE_PATH', 'instance/atelier.db')

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    raise SystemExit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Starting currency migration...")

try:
    cursor.execute("ALTER TABLE 'order' ADD COLUMN currency VARCHAR(10) DEFAULT 'GBP'")
    print("\u2713 Added currency column")
except sqlite3.OperationalError as exc:
    if "duplicate column name" in str(exc):
        print("- currency column already exists")
    else:
        raise

try:
    cursor.execute("ALTER TABLE 'order' ADD COLUMN fx_rate FLOAT DEFAULT 1.0")
    print("\u2713 Added fx_rate column")
except sqlite3.OperationalError as exc:
    if "duplicate column name" in str(exc):
        print("- fx_rate column already exists")
    else:
        raise

conn.commit()
conn.close()

print("\n\u2713 Migration completed successfully!")
