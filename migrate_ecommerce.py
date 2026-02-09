"""
Migration script to add e-commerce features:
- Product variants, images, inventory
- Shopping cart
- Orders and checkout
- Rich text fields
"""
import sqlite3
import os

db_path = 'instance/atelier.db'

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    print("Run python app.py first to create the database")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Starting e-commerce migration...")

# 1. Add new columns to product table
product_columns = [
    ("short_description", "TEXT"),
    ("full_description", "TEXT"),
    ("track_inventory", "BOOLEAN DEFAULT 0"),
    ("stock_quantity", "INTEGER DEFAULT 0"),
    ("allow_backorder", "BOOLEAN DEFAULT 0"),
    ("slug", "VARCHAR(250) UNIQUE"),
]

for column_name, column_type in product_columns:
    try:
        cursor.execute(f"ALTER TABLE product ADD COLUMN {column_name} {column_type}")
        print(f"✓ Added {column_name} to product table")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"- {column_name} already exists in product")
        else:
            print(f"✗ Error adding {column_name}: {e}")

# Rename description to short_description if needed
try:
    cursor.execute("UPDATE product SET short_description = description WHERE short_description IS NULL")
    print("✓ Migrated description to short_description")
except Exception as e:
    print(f"- Description migration: {e}")

# 2. Create ProductVariant table
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_variant (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            price_modifier FLOAT DEFAULT 0.0,
            stock_quantity INTEGER DEFAULT 0,
            sku VARCHAR(100),
            is_active BOOLEAN DEFAULT 1,
            "order" INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES product (id)
        )
    """)
    print("✓ Created product_variant table")
except Exception as e:
    print(f"✗ Error creating product_variant: {e}")

# 3. Create ProductImage table
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_image (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            image_url VARCHAR(500) NOT NULL,
            "order" INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES product (id)
        )
    """)
    print("✓ Created product_image table")
except Exception as e:
    print(f"✗ Error creating product_image: {e}")

# 4. Create Cart table
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(100),
            user_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES user (id)
        )
    """)
    print("✓ Created cart table")
except Exception as e:
    print(f"✗ Error creating cart: {e}")

# 5. Create CartItem table
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cart_item (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            cart_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            variant_id INTEGER,
            quantity INTEGER DEFAULT 1,
            price_at_add FLOAT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(cart_id) REFERENCES cart (id),
            FOREIGN KEY(product_id) REFERENCES product (id),
            FOREIGN KEY(variant_id) REFERENCES product_variant (id)
        )
    """)
    print("✓ Created cart_item table")
except Exception as e:
    print(f"✗ Error creating cart_item: {e}")

# 6. Create Order table
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS "order" (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            order_number VARCHAR(50) UNIQUE NOT NULL,
            customer_name VARCHAR(200) NOT NULL,
            customer_email VARCHAR(120) NOT NULL,
            customer_phone VARCHAR(50),
            pickup_date DATE NOT NULL,
            pickup_time VARCHAR(20) NOT NULL,
            subtotal FLOAT NOT NULL,
            tax FLOAT DEFAULT 0.0,
            total FLOAT NOT NULL,
            payment_method VARCHAR(50),
            payment_status VARCHAR(50) DEFAULT 'pending',
            payment_intent_id VARCHAR(200),
            status VARCHAR(50) DEFAULT 'pending',
            notes TEXT,
            admin_notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("✓ Created order table")
except Exception as e:
    print(f"✗ Error creating order: {e}")

# 7. Create OrderItem table
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_item (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            variant_id INTEGER,
            product_name VARCHAR(200) NOT NULL,
            variant_name VARCHAR(100),
            quantity INTEGER NOT NULL,
            unit_price FLOAT NOT NULL,
            total_price FLOAT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES "order" (id),
            FOREIGN KEY(product_id) REFERENCES product (id),
            FOREIGN KEY(variant_id) REFERENCES product_variant (id)
        )
    """)
    print("✓ Created order_item table")
except Exception as e:
    print(f"✗ Error creating order_item: {e}")

# Generate slugs for existing products
try:
    cursor.execute("SELECT id, name FROM product WHERE slug IS NULL")
    products = cursor.fetchall()
    for product_id, name in products:
        slug = name.lower().replace(' ', '-').replace('é', 'e').replace('è', 'e')
        # Remove special characters
        slug = ''.join(c for c in slug if c.isalnum() or c == '-')
        cursor.execute("UPDATE product SET slug = ? WHERE id = ?", (slug, product_id))
    print(f"✓ Generated slugs for {len(products)} products")
except Exception as e:
    print(f"- Slug generation: {e}")

conn.commit()
conn.close()

print("\n✓ Migration completed successfully!")
print("\nNew features available:")
print("  - Product variants (sizes, flavors, etc.)")
print("  - Multiple product images")
print("  - Inventory tracking")
print("  - Shopping cart")
print("  - Checkout and orders")
print("  - Rich text editing for content")
print("\nRestart your Flask application to use the new features.")
