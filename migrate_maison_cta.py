"""
Add CTA label and URL to maison_section.
"""
import sqlite3
import os

DB_PATH = os.path.join('instance', 'atelier.db')

ADD_CTA_LABEL = 'ALTER TABLE maison_section ADD COLUMN cta_label VARCHAR(200)'
ADD_CTA_URL = 'ALTER TABLE maison_section ADD COLUMN cta_url VARCHAR(500)'

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
        if not column_exists(cursor, 'maison_section', 'cta_label'):
            cursor.execute(ADD_CTA_LABEL)
            print('✓ Added cta_label to maison_section')
        else:
            print('✓ cta_label already present on maison_section')

        if not column_exists(cursor, 'maison_section', 'cta_url'):
            cursor.execute(ADD_CTA_URL)
            print('✓ Added cta_url to maison_section')
        else:
            print('✓ cta_url already present on maison_section')

        conn.commit()
        print('Migration completed successfully.')
    except Exception as exc:
        print(f'Error: {exc}')
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    main()
