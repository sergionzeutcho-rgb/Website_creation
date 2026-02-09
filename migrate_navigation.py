"""
Create navigation_item table and populate with default items
"""
import sqlite3
import os
from datetime import datetime

db_path = os.path.join('instance', 'atelier.db')

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Create navigation_item table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS navigation_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label VARCHAR(100) NOT NULL,
            url VARCHAR(500) NOT NULL,
            is_cta BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            "order" INTEGER DEFAULT 0,
            target VARCHAR(20) DEFAULT '_self',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Check if we already have navigation items
    cursor.execute("SELECT COUNT(*) FROM navigation_item")
    count = cursor.fetchone()[0]
    
    if count == 0:
        # Insert default navigation items
        default_items = [
            ("Click & Collect", "#collect", 0, 1, 1, "_self"),
            ("Seasonal", "#seasonal", 0, 1, 2, "_self"),
            ("Our Maison", "#maison", 0, 1, 3, "_self"),
            ("Book a slot", "#booking", 1, 1, 4, "_self"),
        ]
        
        cursor.executemany("""
            INSERT INTO navigation_item (label, url, is_cta, is_active, "order", target)
            VALUES (?, ?, ?, ?, ?, ?)
        """, default_items)
        
        print(f"✓ Created navigation_item table and added {len(default_items)} default items")
    else:
        print(f"✓ Navigation_item table exists with {count} items")
    
    conn.commit()
    
except Exception as e:
    print(f"Error: {e}")
    conn.rollback()
finally:
    conn.close()

print("\nNavigation management is now available in the admin panel!")
