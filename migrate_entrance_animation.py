"""
Add entrance animation customization fields to site_settings.
"""
import sqlite3
import os

DB_PATH = os.path.join('instance', 'atelier.db')

COLUMNS = [
    ('entrance_enabled', "BOOLEAN", "1"),
    ('entrance_title', "VARCHAR(200)", None),
    ('entrance_subtitle', "VARCHAR(200)", None),
    ('entrance_description', "TEXT", None),
    ('entrance_extra_text', "VARCHAR(200)", None),
    ('entrance_logo_url', "VARCHAR(500)", None),
    ('entrance_duration_ms', "INTEGER", "2000"),
    ('entrance_fade_ms', "INTEGER", "800"),
]

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        for name, col_type, default in COLUMNS:
            if column_exists(cursor, 'site_settings', name):
                print(f"✓ Column {name} already exists")
                continue
            default_clause = f" DEFAULT {default}" if default is not None else ""
            cursor.execute(f"ALTER TABLE site_settings ADD COLUMN {name} {col_type}{default_clause}")
            print(f"✓ Added column {name}")
        conn.commit()
        print("Entrance animation columns added successfully.")
    except Exception as exc:
        print(f"Error: {exc}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    main()
