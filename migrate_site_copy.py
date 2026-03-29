"""
Add copy fields, footer fields, and detail grid fields to site_settings.
"""
import sqlite3
import os

DB_PATH = os.path.join('instance', 'atelier.db')

COLUMNS = [
    ('booking_heading', 'VARCHAR(200)'),
    ('booking_body', 'TEXT'),
    ('booking_kicker', 'VARCHAR(200)'),
    ('booking_date_note', 'TEXT'),
    ('booking_detail_description', 'TEXT'),
    ('seasonal_heading', 'VARCHAR(200)'),
    ('seasonal_body', 'TEXT'),
    ('seasonal_kicker', 'VARCHAR(200)'),
    ('maison_kicker', 'VARCHAR(200)'),
    ('pickup_card_title', 'VARCHAR(200)'),
    ('pickup_card_note', 'TEXT'),
    ('confirmation_title', 'VARCHAR(200)'),
    ('confirmation_subtitle', 'TEXT'),
    ('allow_test_checkout', 'BOOLEAN DEFAULT 0'),
    ('detail_next_drop_label', 'VARCHAR(100)'),
    ('detail_next_drop_value', 'VARCHAR(200)'),
    ('detail_pickup_window_label', 'VARCHAR(100)'),
    ('detail_pickup_window_value', 'VARCHAR(200)'),
    ('detail_order_deadline_label', 'VARCHAR(100)'),
    ('detail_order_deadline_value', 'VARCHAR(200)'),
    ('footer_name', 'VARCHAR(200)'),
    ('footer_copyright', 'TEXT'),
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
