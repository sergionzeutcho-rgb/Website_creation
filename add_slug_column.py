"""
Add slug column to product table
"""
import sqlite3
import os

db_path = os.path.join('instance', 'atelier.db')

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check if slug column exists
    cursor.execute("PRAGMA table_info(product)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'slug' in columns:
        print("✓ Slug column already exists!")
    else:
        print("Adding slug column to product table...")
        cursor.execute("ALTER TABLE product ADD COLUMN slug VARCHAR(200)")
        conn.commit()
        print("✓ Slug column added successfully!")
    
except Exception as e:
    print(f"Error: {e}")
    conn.rollback()
finally:
    conn.close()

print("\nNow run 'python generate_slugs.py' to populate slugs for existing products.")
