"""
Add invoice_template_path column to site_settings for custom invoice HTML uploads.
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

COLUMN = ('invoice_template_path', 'VARCHAR(255)')

def column_exists(cursor, table, column):
    safe_table = table.replace('"', '""')
    cursor.execute(f'PRAGMA table_info("{safe_table}")')
    return any(row[1] == column for row in cursor.fetchall())


def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        col, col_type = COLUMN
        if not column_exists(cursor, 'site_settings', col):
            cursor.execute(f'ALTER TABLE site_settings ADD COLUMN {col} {col_type}')
            print(f'✓ Added {col}')
        else:
            print(f'✓ {col} already exists')
        conn.commit()
        print('Migration completed successfully.')
    except Exception as exc:
        print(f'Error: {exc}')
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    main()
