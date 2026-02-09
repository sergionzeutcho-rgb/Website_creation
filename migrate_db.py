"""
Database migration script to add new columns to existing database.
Run this script to update the database schema without losing existing data.
"""
import sqlite3
import os

db_path = 'instance/atelier.db'

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Starting database migration...")

# Add columns to hero_section table
try:
    cursor.execute("ALTER TABLE hero_section ADD COLUMN video_url VARCHAR(500)")
    print("✓ Added video_url column to hero_section")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("- video_url column already exists in hero_section")
    else:
        print(f"✗ Error adding video_url: {e}")

try:
    cursor.execute("ALTER TABLE hero_section ADD COLUMN media_type VARCHAR(20) DEFAULT 'image'")
    print("✓ Added media_type column to hero_section")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("- media_type column already exists in hero_section")
    else:
        print(f"✗ Error adding media_type: {e}")

# Add columns to site_settings table
new_columns = [
    ("logo_url", "VARCHAR(500)"),
    ("tiktok", "VARCHAR(200)"),
    ("facebook", "VARCHAR(200)"),
    ("youtube", "VARCHAR(200)"),
    ("stripe_public_key", "VARCHAR(200)"),
    ("stripe_secret_key", "VARCHAR(200)"),
    ("paypal_client_id", "VARCHAR(200)"),
    ("whatsapp_number", "VARCHAR(20)"),
    ("chatway_widget", "TEXT"),
    ("custom_chat_widget", "TEXT"),
]

for column_name, column_type in new_columns:
    try:
        cursor.execute(f"ALTER TABLE site_settings ADD COLUMN {column_name} {column_type}")
        print(f"✓ Added {column_name} column to site_settings")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"- {column_name} column already exists in site_settings")
        else:
            print(f"✗ Error adding {column_name}: {e}")

# Create site_settings table if it doesn't exist
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS site_settings (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            company_name VARCHAR(100),
            contact_email VARCHAR(100),
            phone VARCHAR(20),
            address TEXT,
            instagram VARCHAR(200),
            logo_url VARCHAR(500),
            tiktok VARCHAR(200),
            facebook VARCHAR(200),
            youtube VARCHAR(200),
            stripe_public_key VARCHAR(200),
            stripe_secret_key VARCHAR(200),
            paypal_client_id VARCHAR(200),
            whatsapp_number VARCHAR(20),
            chatway_widget TEXT,
            custom_chat_widget TEXT,
            updated_at DATETIME
        )
    """)
    print("✓ Ensured site_settings table exists")
except sqlite3.OperationalError as e:
    print(f"✗ Error with site_settings table: {e}")

# Create default site settings if none exist
cursor.execute("SELECT COUNT(*) FROM site_settings")
if cursor.fetchone()[0] == 0:
    cursor.execute("""
        INSERT INTO site_settings (company_name, contact_email, instagram, updated_at) 
        VALUES ('Atelier Gourmand by OC', 'hello@ateliergourmandbyoc.co.uk', '@ateliergourmandbyoc', CURRENT_TIMESTAMP)
    """)
    print("✓ Created default site settings")

conn.commit()
conn.close()

print("\n✓ Migration completed successfully!")
print("You can now start your Flask application.")
