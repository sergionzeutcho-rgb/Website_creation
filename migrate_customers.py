"""
Add customers table and customer_id to orders.
"""
import sqlite3
import os

db_path = os.path.join('instance', 'atelier.db')

schema_customer = (
    "CREATE TABLE IF NOT EXISTS customer ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "email VARCHAR(120) UNIQUE NOT NULL,"
    "password_hash VARCHAR(256) NOT NULL,"
    "name VARCHAR(200),"
    "phone VARCHAR(50),"
    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    ")"
)

add_customer_id = 'ALTER TABLE "order" ADD COLUMN customer_id INTEGER'


def column_exists(cursor, table, column):
    safe_table = table.replace('"', '""')
    cursor.execute(f'PRAGMA table_info("{safe_table}")')
    return any(row[1] == column for row in cursor.fetchall())


def main():
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(schema_customer)
        print('✓ Ensured customer table exists')

        if not column_exists(cursor, 'order', 'customer_id'):
            cursor.execute(add_customer_id)
            print('✓ Added customer_id to order table')
        else:
            print('✓ customer_id already present on order table')

        conn.commit()
        print('Migration completed successfully.')
    except Exception as exc:
        print(f'Error: {exc}')
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    main()
