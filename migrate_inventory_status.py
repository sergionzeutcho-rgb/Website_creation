"""
Add product_status to products and maintenance fields to site_settings.
"""
import os
import sqlite3

env_db_url = os.getenv('DATABASE_URL')
if env_db_url and env_db_url.startswith('sqlite:///'):
    DB_PATH = env_db_url.replace('sqlite:///', '', 1)
elif env_db_url and env_db_url.endswith('.db'):
    DB_PATH = env_db_url
else:
    DB_PATH = os.path.join('instance', 'atelier.db')

PRODUCT_COLUMN = ('product_status', 'VARCHAR(20) DEFAULT "active"')
SITE_COLUMNS = [
    ('maintenance_enabled', 'BOOLEAN DEFAULT 0'),
    ('maintenance_message', 'TEXT'),
    ('maintenance_image_url', 'VARCHAR(500)'),
]

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info('{table}')")
    return any(row[1] == column for row in cursor.fetchall())

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        col, ctype = PRODUCT_COLUMN
        if not column_exists(cur, 'product', col):
            cur.execute(f"ALTER TABLE product ADD COLUMN {col} {ctype}")
            print(f"✓ Added {col} to product")
        else:
            print(f"✓ {col} already exists on product")
        for col, ctype in SITE_COLUMNS:
            if not column_exists(cur, 'site_settings', col):
                cur.execute(f"ALTER TABLE site_settings ADD COLUMN {col} {ctype}")
                print(f"✓ Added {col} to site_settings")
            else:
                print(f"✓ {col} already exists on site_settings")
        conn.commit()
        print('Migration completed successfully.')
    except Exception as exc:
        print(f'Error: {exc}')
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    main()
