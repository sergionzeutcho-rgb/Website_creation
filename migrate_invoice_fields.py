"""
Add invoicing and company fields to site_settings.
"""
import sqlite3
import os

# Prefer DATABASE_URL if present; fall back to instance/atelier.db
# Accept both "sqlite:///path" and bare paths
env_db_url = os.getenv('DATABASE_URL')
if env_db_url and env_db_url.startswith('sqlite:///'):
    DB_PATH = env_db_url.replace('sqlite:///', '', 1)
elif env_db_url and env_db_url.endswith('.db'):
    DB_PATH = env_db_url
else:
    DB_PATH = os.path.join('instance', 'atelier.db')

COLUMNS = [
    ('company_name', 'VARCHAR(200)'),
    ('company_vat_number', 'VARCHAR(100)'),
    ('company_registration', 'VARCHAR(100)'),
    ('company_invoice_email', 'VARCHAR(120)'),
    ('company_invoice_phone', 'VARCHAR(50)'),
    ('company_invoice_address', 'TEXT'),
    ('company_bank_name', 'VARCHAR(200)'),
    ('company_bank_account', 'VARCHAR(100)'),
    ('company_sort_code', 'VARCHAR(50)'),
    ('company_iban', 'VARCHAR(100)'),
    ('company_swift', 'VARCHAR(100)'),
    ('invoice_notes', 'TEXT'),
]


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
        for col, col_type in COLUMNS:
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
